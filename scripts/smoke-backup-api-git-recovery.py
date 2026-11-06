#!/usr/bin/env python3
"""Opt-in encrypted Git backup/restore through the real GoreeCloud Backup API.

Operates only on disposable repositories and an independently built local
GoreeCloud Backup server binary and independently reviewed Kopia binary.
The caller MUST provide network isolation; no off-host or production API use.
"""
from __future__ import annotations

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
            print("PASS: authenticated GoreeCloud Backup API -> encrypted Kopia Git snapshot "
                  "-> fresh-cache structural and full verification -> isolated restore, "
                  "with unauthorized/confirmation/overwrite denial, refs/config/fsck/clone "
                  "and restored token rotation.")
            print("Not verified: off-host copy, backup credential escrow, durable job "
                  "scheduling, host-level RPO/RTO or production data.")
        finally:
            service.terminate()
            try:
                service.wait(timeout=5)
            except subprocess.TimeoutExpired:
                service.kill()
                service.wait(timeout=5)


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
