#!/usr/bin/env python3
"""Opt-in encrypted Git backup/restore through the real GoreeCloud Backup API.

Operates only on disposable repositories and an independently built local
GoreeCloud Backup server binary and independently reviewed Kopia binary.
The caller MUST provide network isolation; no off-host or production API use.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from goreecloud_git.core import Store, git


def required_executable(variable: str) -> str | None:
    supplied = os.environ.get(variable, "")
    if not supplied:
        return None
    path = Path(supplied)
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        return None
    return str(path.resolve())


def encrypted_repository_digests(directory: Path) -> dict[str, str]:
    """Compare each encrypted object file before accepting a copied repository."""
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*")) if path.is_file()
    }


def run(argv: list[str], *, env: dict[str, str] | None = None,
        success: bool = True, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
    if success and result.returncode:
        # Do not print CLI environment, auth tokens, Kopia passwords or full paths.
        raise RuntimeError(f"Synthetic command failed: {Path(argv[0]).name}, "
                           f"exit={result.returncode}")
    return result


def api_request(endpoint: str, token: str, method: str, suffix: str,
                payload: dict | None = None, *, authenticated: bool = True):
    headers = {"Content-Type": "application/json"}
    if authenticated:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        endpoint + suffix,
        method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.load(response)


def expect_http_status(code: int, endpoint: str, token: str, method: str,
                       suffix: str, payload: dict | None = None,
                       *, authenticated: bool = True) -> None:
    try:
        api_request(endpoint, token, method, suffix, payload,
                    authenticated=authenticated)
    except urllib.error.HTTPError as exc:
        if exc.code == code:
            return
        raise RuntimeError(f"Expected HTTP {code}, got HTTP {exc.code}.") from exc
    raise RuntimeError(f"Expected HTTP {code} but request succeeded.")


def wait_for_job(endpoint: str, token: str, kind: str, **parameters):
    status, pending = api_request(
        endpoint, token, "POST", "jobs", {"type": kind, **parameters}
    )
    if status != 202 or "id" not in pending:
        raise RuntimeError(f"Synthetic {kind} job was not accepted.")
    for _ in range(175):
        time.sleep(.2)
        _, current = api_request(endpoint, token, "GET", "jobs/" + pending["id"])
        if current.get("status") == "completed":
            return current
        if current.get("status") in ("failed", "cancelled", "interrupted"):
            raise RuntimeError(f"Synthetic {kind} job did not complete successfully.")
    raise RuntimeError(f"Synthetic {kind} job timed out.")


def exercise(kopia: str, backup_service: str) -> None:
    with tempfile.TemporaryDirectory(prefix="gcgit-backup-api-") as temp:
        root = Path(temp)
        root.chmod(0o700)
        source = root / "private-source"
        store = Store(source)
        store.init()
        bare = store.create("example", max_push_mib=16)
        original_token = store.rotate_token()
        work = root / "commit-source"
        run(["git", "init", "-b", "main", str(work)])
        marker = "GC Git Backup API synthetic private fixture"
        (work / "fixture.txt").write_text(marker + "\n", encoding="utf-8")
        run(["git", "-C", str(work), "add", "fixture.txt"])
        run(["git", "-C", str(work), "-c", "user.name=Fixture",
             "-c", "user.email=fixture@example.invalid", "commit", "-m", "backup fixture"])
        run(["git", "-C", str(work), "push", str(bare), "main"])
        original_ref = git("--git-dir", str(bare), "rev-parse", "refs/heads/main")
        original_config = {
            key: git("--git-dir", str(bare), "config", "--get", key)
            for key in ("receive.denyDeletes", "receive.denyNonFastForwards",
                        "receive.maxInputSize")
        }
        store.verify("example")

        bin_dir = root / "bin"
        bin_dir.mkdir(mode=0o700)
        wrapper = bin_dir / "kopia"
        config = root / "kopia-config.json"
        # Wrapper exposes Kopia to Backup's strict executable allowlist without
        # changing system PATH or connecting to any preexisting repository.
        wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(kopia) +
                           " --config-file=" + shlex.quote(str(config)) +
                           ' "$@"\n', encoding="utf-8")
        wrapper.chmod(0o700)
        env = dict(os.environ)
        env["KOPIA_PASSWORD"] = secrets.token_hex(32)
        env["PATH"] = str(bin_dir) + os.pathsep + os.defpath
        env["GOREECLOUD_BACKUP_TOKEN"] = secrets.token_urlsafe(32)
        env.pop("GOREECLOUD_BACKUP_STATE_DIR", None)
        env.pop("KOPIA_CONFIG_PATH", None)
        env.pop("KOPIA_CACHE_DIRECTORY", None)
        # Original owner credentials and cloud config must never be injected.
        env["RCLONE_CONFIG"] = os.devnull
        repository = root / "encrypted-kopia-repository"
        run([str(wrapper), "repository", "create", "filesystem",
             "--path=" + str(repository),
             "--cache-directory=" + str(root / "kopia-cache"),
             "--no-check-for-updates"], env=env, timeout=120)

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env["GOREECLOUD_BACKUP_ADDR"] = f"127.0.0.1:{port}"
        endpoint = f"http://127.0.0.1:{port}/api/v1/"
        service = subprocess.Popen([backup_service], env=env,
                                   stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        try:
            for _ in range(90):
                if service.poll() is not None:
                    raise RuntimeError("Synthetic Backup API service unexpectedly exited.")
                try:
                    status, health = api_request(
                        endpoint, env["GOREECLOUD_BACKUP_TOKEN"], "GET", "health")
                    if status == 200:
                        break
                except (urllib.error.URLError, ConnectionError, TimeoutError):
                    time.sleep(.15)
            else:
                raise RuntimeError("Synthetic loopback Backup API did not start.")
            if not health.get("engines", {}).get("kopia"):
                raise RuntimeError("Synthetic Backup API cannot find the Kopia engine.")
            token = env["GOREECLOUD_BACKUP_TOKEN"]
            expect_http_status(401, endpoint, token, "GET", "health",
                               authenticated=False)
            expect_http_status(422, endpoint, token, "POST", "jobs",
                               {"type": "restore", "snapshot_id": "invalid",
                                "destination": str(root / "preliminary")})
            # Stop writes before snapshot; the disposable source is quiescent.
            wait_for_job(endpoint, token, "backup", source=str(source))
            wait_for_job(endpoint, token, "verify-structure")
            expect_http_status(422, endpoint, token, "POST", "jobs",
                               {"type": "verify-full"})
            wait_for_job(endpoint, token, "verify-full",
                         confirm="VERIFY ALL BACKUPS")
            snapshots = wait_for_job(endpoint, token, "snapshots")
            items = json.loads(snapshots.get("output", ""))
            if not items:
                raise RuntimeError("No synthetic encrypted snapshot listed.")
            root_object_id = items[0]["rootEntry"]["obj"]

            occupied = root / "occupied"
            occupied.mkdir(mode=0o700)
            keep = occupied / "keep.txt"
            keep.write_text("preserve me")
            expect_http_status(422, endpoint, token, "POST", "jobs", {
                "type": "restore", "snapshot_id": root_object_id,
                "destination": str(occupied), "confirm": "RESTORE"
            })
            if keep.read_text() != "preserve me":
                raise RuntimeError("Existing restore destination changed.")

            destination = root / "restored"
            wait_for_job(endpoint, token, "restore",
                         snapshot_id=root_object_id,
                         destination=str(destination), confirm="RESTORE")
            recovered = Store(destination)
            recovered.ready()
            recovered_bare = recovered.existing("example")
            recovered.verify("example")
            if git("--git-dir", str(recovered_bare),
                   "rev-parse", "refs/heads/main") != original_ref:
                raise RuntimeError("Restored Git branch object ID differs.")
            for key, expected in original_config.items():
                if git("--git-dir", str(recovered_bare),
                       "config", "--get", key) != expected:
                    raise RuntimeError("Restored Git receive protection differs.")
            if recovered.read_token() != original_token:
                raise RuntimeError("Restored owner web token is incorrect.")
            if recovered.rotate_token() == original_token:
                raise RuntimeError("Restored owner web token was not rotated.")
            clone = root / "restored-clone"
            run(["git", "clone", str(recovered_bare), str(clone)])
            if (clone / "fixture.txt").read_text() != marker + "\n":
                raise RuntimeError("Restored native Git clone does not match.")
            for candidate in repository.rglob("*"):
                if candidate.is_file() and marker.encode() in candidate.read_bytes():
                    raise RuntimeError("Unencrypted synthetic marker found in Kopia repository.")
            # Do not announce overall success until the separate encrypted
            # repository-copy recovery phase has also passed.
        finally:
            service.terminate()
            try:
                service.wait(timeout=5)
            except subprocess.TimeoutExpired:
                service.kill()
                service.wait(timeout=5)

        # A new disposable *local* encrypted repository copy stands in for
        # separately retained storage. Never touch a real provider or remote.
        copied_repo = root / "copied-encrypted-kopia-repository"
        shutil.copytree(repository, copied_repo, symlinks=False)
        original_hashes = encrypted_repository_digests(repository)
        if not original_hashes or encrypted_repository_digests(copied_repo) != original_hashes:
            raise RuntimeError("Encrypted Kopia repository copy differs from its source.")
        # Quiesce/stop the original service first, then make its original
        # data, repository and client config paths unavailable *inside only
        # this temporary test*. No user files are deleted or overwritten.
        repository.rename(root / "unavailable-original-repository")
        source.rename(root / "unavailable-original-source")
        config.rename(root / "unavailable-original-config.json")
        if any(path.exists() for path in (repository, source, config)):
            raise RuntimeError("Original synthetic backup paths remain accessible.")

        # A fresh Kopia connection, cache, Backup API process and bearer token
        # must recover from the independent copy, not from original paths.
        copied_config = root / "copied-kopia-config.json"
        copied_bin = root / "copied-bin"
        copied_bin.mkdir(mode=0o700)
        copied_wrapper = copied_bin / "kopia"
        copied_wrapper.write_text(
            "#!/bin/sh\nexec " + shlex.quote(kopia)
            + " --config-file=" + shlex.quote(str(copied_config))
            + ' "$@"\n', encoding="utf-8"
        )
        copied_wrapper.chmod(0o700)
        recovery_env = dict(env)
        recovery_env["PATH"] = str(copied_bin) + os.pathsep + os.defpath
        recovery_env["GOREECLOUD_BACKUP_TOKEN"] = secrets.token_urlsafe(32)

        wrong_env = dict(recovery_env)
        wrong_env["KOPIA_PASSWORD"] = secrets.token_hex(32)
        bad = run(
            [kopia, "--config-file=" + str(root / "bad-password-config.json"),
             "repository", "connect", "filesystem", "--path=" + str(copied_repo),
             "--cache-directory=" + str(root / "bad-password-cache"),
             "--no-check-for-updates"],
            env=wrong_env, success=False, timeout=45,
        )
        if bad.returncode == 0:
            raise RuntimeError("Copied encrypted repository accepted an incorrect password.")
        run(
            [str(copied_wrapper), "repository", "connect", "filesystem",
             "--path=" + str(copied_repo),
             "--cache-directory=" + str(root / "fresh-copied-repository-cache"),
             "--no-check-for-updates"],
            env=recovery_env, timeout=120,
        )
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            second_port = probe.getsockname()[1]
        recovery_env["GOREECLOUD_BACKUP_ADDR"] = f"127.0.0.1:{second_port}"
        recovery_endpoint = f"http://127.0.0.1:{second_port}/api/v1/"
        second_service = subprocess.Popen(
            [backup_service], env=recovery_env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(90):
                if second_service.poll() is not None:
                    raise RuntimeError("Copied repository recovery API unexpectedly exited.")
                try:
                    status, health = api_request(
                        recovery_endpoint, recovery_env["GOREECLOUD_BACKUP_TOKEN"],
                        "GET", "health",
                    )
                    if status == 200:
                        break
                except (urllib.error.URLError, ConnectionError, TimeoutError):
                    time.sleep(.15)
            else:
                raise RuntimeError("Copied repository recovery API did not start.")
            if not health.get("engines", {}).get("kopia"):
                raise RuntimeError("Recovery Backup API cannot find Kopia.")
            new_token = recovery_env["GOREECLOUD_BACKUP_TOKEN"]
            expect_http_status(401, recovery_endpoint, token, "GET", "health")
            expect_http_status(401, recovery_endpoint, new_token,
                               "GET", "health", authenticated=False)
            wait_for_job(recovery_endpoint, new_token, "verify-structure")
            wait_for_job(recovery_endpoint, new_token, "verify-full",
                         confirm="VERIFY ALL BACKUPS")
            copy_snapshots = wait_for_job(recovery_endpoint, new_token, "snapshots")
            copied_items = json.loads(copy_snapshots.get("output", ""))
            if not copied_items or copied_items[0]["rootEntry"]["obj"] != root_object_id:
                raise RuntimeError("Snapshot ID differs in copied encrypted repository.")
            second_restore = root / "restored-from-independent-copy"
            wait_for_job(recovery_endpoint, new_token, "restore",
                         snapshot_id=root_object_id,
                         destination=str(second_restore), confirm="RESTORE")
            copied_store = Store(second_restore)
            copied_store.ready()
            copied_bare = copied_store.existing("example")
            copied_store.verify("example")
            if git("--git-dir", str(copied_bare),
                   "rev-parse", "refs/heads/main") != original_ref:
                raise RuntimeError("Git branch ref differs after copied repository restore.")
            for key, expected in original_config.items():
                if git("--git-dir", str(copied_bare), "config", "--get", key) != expected:
                    raise RuntimeError("Git protection differs after copied restore.")
            if copied_store.read_token() != original_token:
                raise RuntimeError("Copied repository restore lost original web token.")
            if copied_store.rotate_token() == original_token:
                raise RuntimeError("Copied repository restored token was not rotated.")
            copied_clone = root / "copied-repository-clone"
            run(["git", "clone", str(copied_bare), str(copied_clone)])
            if (copied_clone / "fixture.txt").read_text() != marker + "\n":
                raise RuntimeError("Copied repository Git clone contents differ.")
        finally:
            second_service.terminate()
            try:
                second_service.wait(timeout=5)
            except subprocess.TimeoutExpired:
                second_service.kill()
                second_service.wait(timeout=5)

        print("PASS: authenticated Backup API encrypted Git snapshot/full verification; "
              "isolated original restore; encrypted repository copy with matching "
              "digests; hidden original paths, wrong-password/old-token denial; "
              "fresh-connection/fresh-cache API verification and Git restore, "
              "refs/config/fsck/clone and restored-token rotation.")
        print("Not verified: physical off-host storage, key escrow, durable backup "
              "scheduling, host RPO/RTO or real private Git data.")


def main() -> int:
    if len(sys.argv) != 1:
        raise ValueError("No arguments supported; set reviewed binary paths using environment.")
    kopia = required_executable("KOPIA_BIN")
    backup = required_executable("GOREECLOUD_BACKUP_BIN")
    if not kopia or not backup:
        print("SKIP: reviewed KOPIA_BIN and GOREECLOUD_BACKUP_BIN required.",
              file=sys.stderr)
        return 77
    exercise(kopia, backup)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError,
            urllib.error.URLError, json.JSONDecodeError) as exc:
        print("FAIL: disposable Git/Backup API recovery acceptance: "
              + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        raise SystemExit(1)
