#!/usr/bin/env python3
"""Opt-in encrypted Kopia snapshot + isolated Git recovery acceptance.

Requires an externally installed, reviewed Kopia executable. Only synthetic
repositories and short-lived secrets are used. No actual private GoreeCloud
repository or existing Backup/Kopia repository is accessed or modified.
This is local, offline recovery evidence, NOT off-host disaster recovery.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from goreecloud_git.core import GitError, Store, git

FIXTURE_CONTENT = "GoreeCloud Git private-restore fixture " + "r8jGfDHf8bAc7efz"
DEFAULT_TIMEOUT = 90


def execute(cmd: list[str], *, env=None, timeout: int = DEFAULT_TIMEOUT,
            success: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True,
                            env=env, timeout=timeout)
    if success and result.returncode:
        # Never include process environment, synthetic password or archive
        # bytes in error messages; CLI arguments contain only test paths.
        raise RuntimeError(
            f"Fixture command failed ({result.returncode}): {Path(cmd[0]).name}; "
            f"diagnostic: {result.stderr[-280:]}"
        )
    return result


def reserve_empty_restore(path: Path) -> None:
    """Refuse existing paths and aliases; never overwrite a restore target."""
    if path.exists() or path.is_symlink():
        raise ValueError("Isolated restore destination already exists.")
    path.mkdir(mode=0o700)


def kopia_run(binary: str, config: Path, *args: str, env: dict[str, str],
              success: bool = True, timeout: int = DEFAULT_TIMEOUT):
    return execute([binary, "--config-file=" + str(config), *args],
                   env=env, success=success, timeout=timeout)


def fixture(binary: str) -> None:
    with tempfile.TemporaryDirectory(prefix="gcgit-kopia-acceptance-") as temp:
        root = Path(temp)
        os.chmod(root, 0o700)
        source = root / "private-source"
        store = Store(source)
        store.init()
        bare = store.create("project", max_push_mib=32)
        token = store.rotate_token()
        work = root / "working"
        execute(["git", "init", "-b", "main", str(work)])
        (work / "README.fixture").write_text(FIXTURE_CONTENT + "\n")
        execute(["git", "-C", str(work), "add", "README.fixture"])
        execute(["git", "-C", str(work), "-c", "user.name=Fixture",
                 "-c", "user.email=fixture@example.invalid",
                 "commit", "-m", "private synthetic fixture"])
        execute(["git", "-C", str(work), "push", str(bare), "main"])
        original_ref = git("--git-dir", str(bare), "rev-parse", "refs/heads/main")
        original_settings = {
            key: git("--git-dir", str(bare), "config", "--get", key)
            for key in ("receive.denyDeletes", "receive.denyNonFastForwards",
                        "receive.maxInputSize")
        }
        store.verify("project")
        if not source.is_dir() or not bare.is_dir():
            raise RuntimeError("Synthetic Git source was not created.")

        # Kopia uses its own encryption, credentials, repository and cache.
        # No backup password is passed in argv, logged or stored in Git.
        env = dict(os.environ)
        env["KOPIA_PASSWORD"] = secrets.token_hex(32)
        repository = root / "encrypted-repository"
        config = root / "kopia-config.json"
        cache = root / "kopia-cache"
        kopia_run(
            binary, config, "repository", "create", "filesystem",
            "--path=" + str(repository),
            "--cache-directory=" + str(cache), "--no-check-for-updates",
            env=env, timeout=120,
        )
        status = kopia_run(binary, config, "repository", "status", env=env)
        if not status.stdout.strip():
            raise RuntimeError("Encrypted Kopia repository status is missing.")

        # Source is quiesced before snapshot: no Git writes or ref updates
        # occur while Kopia reads the bare repository.
        manifest = kopia_run(
            binary, config, "snapshot", "create", str(source), "--json",
            env=env, timeout=120,
        )
        try:
            snapshot = json.loads(manifest.stdout)
            object_id = snapshot["rootEntry"]["obj"]
            if not isinstance(object_id, str) or not object_id:
                raise KeyError("rootEntry.obj")
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError("Kopia snapshot lacks the restore root object.") from exc

        # Explicitly test structural and 100% file verification using a
        # newly connected config + fresh cache, not the snapshot writer cache.
        check_config = root / "kopia-check-config.json"
        kopia_run(
            binary, check_config, "repository", "connect", "filesystem",
            "--path=" + str(repository),
            "--cache-directory=" + str(root / "fresh-verification-cache"),
            env=env, timeout=120,
        )
        kopia_run(
            binary, check_config, "snapshot", "verify",
            "--verify-files-percent=0", "--file-parallelism=2",
            env=env, timeout=120,
        )
        kopia_run(
            binary, check_config, "snapshot", "verify",
            "--verify-files-percent=100", "--file-parallelism=2",
            env=env, timeout=120,
        )

        # A wrong password and a pre-existing destination must fail closed.
        wrong_env = dict(env)
        wrong_env["KOPIA_PASSWORD"] = "deliberately-invalid-password"
        wrong_result = kopia_run(
            binary, root / "wrong-password-config.json",
            "repository", "connect", "filesystem",
            "--path=" + str(repository),
            "--cache-directory=" + str(root / "wrong-password-cache"),
            env=wrong_env, success=False, timeout=45,
        )
        if wrong_result.returncode == 0:
            raise RuntimeError("Incorrect encrypted repository credentials were accepted.")

        occupied = root / "preexisting-destination"
        occupied.mkdir(mode=0o700)
        sentinel = occupied / "sentinel"
        sentinel.write_text("Must not overwrite\n")
        try:
            reserve_empty_restore(occupied)
        except ValueError:
            pass
        else:
            raise RuntimeError("Pre-existing destination was not rejected.")
        if sentinel.read_text() != "Must not overwrite\n":
            raise RuntimeError("Existing restore destination was changed.")

        restored = root / "isolated-restored-root"
        reserve_empty_restore(restored)
        kopia_run(
            binary, check_config, "snapshot", "restore",
            "--no-overwrite-files", "--no-overwrite-directories",
            "--no-overwrite-symlinks", "--write-files-atomically",
            object_id, str(restored), env=env, timeout=120,
        )

        # Do not chmod or repair an invalid restore to get a passing result.
        recovered = Store(restored)
        recovered.ready()
        recovered_bare = recovered.existing("project")
        recovered.verify("project")
        if git("--git-dir", str(recovered_bare),
               "rev-parse", "refs/heads/main") != original_ref:
            raise RuntimeError("Restored Git ref does not match the snapshot.")
        for key, expected in original_settings.items():
            observed = git("--git-dir", str(recovered_bare),
                           "config", "--get", key)
            if observed != expected:
                raise RuntimeError("Restored repository protection settings differ.")
        if recovered.read_token() != token:
            raise RuntimeError("Restored web token differs from the encrypted snapshot.")
        rotated = recovered.rotate_token()
        if rotated == token:
            raise RuntimeError("Restored web token was not rotated.")

        clone = root / "recovered-clone"
        execute(["git", "clone", str(recovered_bare), str(clone)])
        if (clone / "README.fixture").read_text() != FIXTURE_CONTENT + "\n":
            raise RuntimeError("Restored native Git clone differs from source fixture.")

        # A byte-search is an additional leak smoke only, not an assertion
        # about cryptographic security or archive confidentiality.
        for file in repository.rglob("*"):
            if file.is_file() and FIXTURE_CONTENT.encode() in file.read_bytes():
                raise RuntimeError("Synthetic fixture plaintext appears in Kopia ciphertext.")

        print("PASS: disposable encrypted Kopia repository; Git bare-repository "
              "snapshot; fresh-cache structural and full verification; "
              "wrong-password and existing-target rejection; restored refs, "
              "protection config, web-token rotation, Git fsck and native clone.")
        print("Not verified: off-host replication, Backup alpha API, production RPO/RTO.")


def main() -> int:
    if len(sys.argv) > 1:
        raise ValueError("No arguments accepted; use KOPIA_BIN to choose reviewed executable.")
    binary = os.environ.get("KOPIA_BIN") or shutil.which("kopia")
    if binary and not Path(binary).is_file():
        binary = shutil.which(binary)
    if not binary or not Path(binary).is_file():
        print("SKIP: external Kopia CLI is not available.", file=sys.stderr)
        return 77
    fixture(str(Path(binary).resolve()))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, GitError, OSError, RuntimeError,
            subprocess.SubprocessError) as exc:
        print("FAIL:", str(exc), file=sys.stderr)
        raise SystemExit(1)
