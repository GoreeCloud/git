"""Filesystem storage for owner-operated, SSH-hosted, private Git repositories."""
from __future__ import annotations
import os
from pathlib import Path
import re
import secrets
import selectors
import signal
import stat
import subprocess
import tempfile
import time
from urllib.parse import quote

from .git_environment import git_binary, git_environment

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}\Z", re.ASCII)
SSH_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}\Z")
SSH_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}\Z")

class GitError(RuntimeError):
    pass

def check_name(name: str) -> str:
    if (not isinstance(name, str) or not NAME.fullmatch(name)
            or name in (".", "..") or name.endswith((".", ".git"))):
        raise ValueError("Invalid name: use 1-63 letters, numbers, dots, dashes or underscores; no .git suffix.")
    return name

def git(*args: str, timeout: int = 12, max_output: int = 1048576) -> str:
    """Run a bounded Git metadata/admin command without shell or environment overrides.

    Git's SSH transport has a separate streaming entrypoint. This helper is
    for short owner-initiated metadata/configuration commands, never for
    receiving or sending Git pack streams.
    """
    if timeout <= 0 or not 1 <= max_output <= 1048576:
        raise ValueError("Invalid Git command budget.")
    executable = git_binary()
    if executable is None:
        raise GitError("Git is not installed in the trusted system path.")
    try:
        proc = subprocess.Popen(
            [executable, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=git_environment(), start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise GitError("Git is not installed.") from exc
    except OSError as exc:
        raise GitError("Cannot start Git command.") from exc

    deadline = time.monotonic() + timeout
    chunks: list[bytes] = []
    size = 0
    completed = False
    try:
        assert proc.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise GitError("Git command timed out.")
                chunk = os.read(proc.stdout.fileno(), min(65536, max_output + 1 - size))
                if not chunk:
                    selector.unregister(proc.stdout)
                    break
                size += len(chunk)
                if size > max_output:
                    raise GitError("Git output exceeded the permitted size.")
                chunks.append(chunk)
        try:
            status = proc.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise GitError("Git command timed out.") from exc
        if status:
            raise GitError(f"Git operation failed (exit {status}).")
        completed = True
        return b"".join(chunks).decode("utf-8", errors="replace").strip()
    finally:
        if not completed:
            # An exited Git parent may have left a child holding stdout open.
            # Kill the whole session group on failure or output exhaustion.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if proc.stdout is not None:
            proc.stdout.close()
        proc.wait()

def private_directory(path: Path) -> None:
    # Inspect the directory entry itself. A private mode alone is not proof
    # that the service account owns this restored or reattached storage.
    try:
        entry = path.lstat()
    except OSError as exc:
        raise GitError(f"Missing or unsafe storage directory: {path}") from exc
    if not stat.S_ISDIR(entry.st_mode):
        raise GitError(f"Missing or unsafe storage directory: {path}")
    if entry.st_uid != os.geteuid():
        raise GitError(f"Storage directory must belong to the current account: {path}")
    if stat.S_IMODE(entry.st_mode) & 0o077:
        raise GitError(f"Storage directory must be private (0700): {path}")

class Store:
    def __init__(self, root: str | Path | None = None):
        specified = root if root is not None else os.environ.get("GC_GIT_ROOT")
        self.root = Path(specified).expanduser().absolute() if specified else Path.home() / ".local/share/goreecloud-git"
        self.repos = self.root / "repos"

    def init(self) -> Path:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        private_directory(self.root)
        self.repos.mkdir(mode=0o700, exist_ok=True)
        private_directory(self.repos)
        return self.root

    def ready(self) -> None:
        private_directory(self.root)
        private_directory(self.repos)

    def path(self, name: str) -> Path:
        return self.repos / (check_name(name) + ".git")

    def create(self, name: str, max_push_mib: int = 1024) -> Path:
        # Git defaults to unlimited incoming pack sizes. Validate before
        # reserving a private name so bad inputs never leave a partial repo.
        if (isinstance(max_push_mib, bool) or not isinstance(max_push_mib, int)
                or not 1 <= max_push_mib <= 16384):
            raise ValueError("Max push size must be 1-16384 MiB.")
        self.ready()
        path = self.path(name)
        # Reserve the name *atomically*, and private from its first moment.
        # A check-then-init sequence allows two creators to race. Never chmod
        # or overwrite somebody else's pre-existing path (including symlinks).
        try:
            path.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise GitError("Repository already exists.") from exc
        # A failed Git initialization intentionally leaves a private, reserved
        # directory for owner inspection; never delete an unknown directory.
        git("init", "--bare", "--initial-branch=main", str(path))
        git("--git-dir", str(path), "config", "receive.denyDeletes", "true")
        git("--git-dir", str(path), "config", "receive.denyNonFastForwards", "true")
        git("--git-dir", str(path), "config", "receive.maxInputSize", str(max_push_mib * 1048576))
        return path

    def existing(self, name: str) -> Path:
        self.ready()
        path = self.path(name)
        if path.is_symlink() or not path.is_dir():
            raise GitError("Repository not found.")
        # The root being private is not sufficient if a bare repository was
        # restored or chmodded with overly broad permissions. Reject it, do
        # not silently repair unknown owner state or expose Git metadata.
        private_directory(path)
        if (path / "HEAD").is_symlink() or (path / "config").is_symlink():
            raise GitError("Unsafe repository control-file symlink.")
        if git("--git-dir", str(path), "rev-parse", "--is-bare-repository") != "true":
            raise GitError("Not a valid bare repository.")
        return path

    def names(self) -> list[str]:
        self.ready()
        result: list[str] = []
        for candidate in self.repos.iterdir():
            if candidate.is_symlink() or not candidate.is_dir() or not candidate.name.endswith(".git"):
                continue
            try:
                name = check_name(candidate.name[:-4])
            except ValueError:
                continue
            # An interrupted create may leave a reserved empty directory.
            # Do not present that incomplete directory as a usable repository.
            if not (candidate / "HEAD").is_file() or not (candidate / "config").is_file():
                continue
            result.append(name)
        return sorted(result, key=str.casefold)

    def inventory_issues(self) -> list[str]:
        """Read-only preflight for unsafe or unfinished managed repo entries.

        Unlike names(), inspect incomplete reservations and symlinks too. This
        is a basic control/permission check, not a replacement for Git fsck.
        """
        self.ready()
        issues: list[str] = []
        for candidate in self.repos.iterdir():
            if not candidate.name.endswith(".git"):
                continue
            name = candidate.name[:-4]
            try:
                check_name(name)
            except ValueError:
                # Never print a path containing unknown/control characters.
                issues.append("(invalid repository filename)")
                continue
            try:
                self.existing(name)
            except (GitError, OSError, ValueError):
                issues.append(name)
        return sorted(set(issues), key=str.casefold)

    def info(self, name: str) -> dict[str, object]:
        path = self.existing(name)
        refs = git("--git-dir", str(path), "for-each-ref", "--format=%(refname:short)", "refs/heads")
        commits = git("--git-dir", str(path), "rev-list", "--count", "--all")
        return {"name": name, "path": str(path),
                "branches": refs.splitlines() if refs else [], "commits": int(commits)}

    def recent(self, name: str, limit: int = 15) -> list[dict[str, str]]:
        path = self.existing(name)
        if not 1 <= limit <= 100:
            raise ValueError("Invalid history limit.")
        output = git("--git-dir", str(path), "log", "--all", "-n", str(limit),
                     "--pretty=format:%h%x1f%s%x1f%aI")
        records = []
        for line in output.splitlines():
            parts = line.split("\x1f", 2)
            if len(parts) == 3:
                records.append({"sha": parts[0], "subject": parts[1][:240], "date": parts[2]})
        return records

    def verify(self, name: str) -> None:
        """Check Git object/ref integrity without modifying the repository."""
        path = self.existing(name)
        git("--git-dir", str(path), "fsck", "--full", "--no-reflogs", timeout=60)

    def ssh_url(self, name: str, host: str, user: str = "gcgit", port: int = 22) -> str:
        path = self.existing(name)
        if not SSH_HOST.fullmatch(host) or ".." in host or not SSH_USER.fullmatch(user):
            raise ValueError("Invalid SSH host or username.")
        if not 1 <= port <= 65535:
            raise ValueError("Invalid SSH port.")
        return f"ssh://{user}@{host}:{port}{quote(str(path), safe='/')}"

    def token_path(self) -> Path:
        self.ready()
        return self.root / ".web-token"

    def rotate_token(self) -> str:
        dest = self.token_path()
        if dest.is_symlink():
            raise GitError("Web token path is a symlink.")
        if dest.exists():
            existing = dest.lstat()
            if not stat.S_ISREG(existing.st_mode) or existing.st_uid != os.geteuid():
                raise GitError("Unsafe or foreign-owned web token path.")
        token = secrets.token_urlsafe(36)
        fd, tmp = tempfile.mkstemp(prefix=".web-token-", dir=self.root)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as f:
                f.write(token + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dest)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return token

    def read_token(self) -> str:
        dest = self.token_path()
        try:
            entry = dest.lstat()
        except OSError as exc:
            raise GitError("Missing or exposed web token. Run 'gcgit web-token'.") from exc
        if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != os.geteuid()
                or stat.S_IMODE(entry.st_mode) & 0o077):
            raise GitError("Missing or exposed web token. Run 'gcgit web-token'.")
        token = dest.read_text(encoding="ascii").strip()
        if len(token) < 40:
            raise GitError("Invalid web token.")
        return token