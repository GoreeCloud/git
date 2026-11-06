#!/usr/bin/env python3
"""Optional Linux-only, isolated OpenSSH config test; never starts sshd.

Requires unprivileged user/mount/network namespaces and an installed OpenSSH
server. Does not edit sshd_config, add accounts, change firewall, or listen.
"""
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

REQUIRED = {
    "passwordauthentication": "no",
    "kbdinteractiveauthentication": "no",
    "pubkeyauthentication": "yes",
    "x11forwarding": "no",
    "permittty": "no",
    "allowtcpforwarding": "no",
    "allowagentforwarding": "no",
    "permittunnel": "no",
    "permituserenvironment": "no",
    "loglevel": "VERBOSE",
}


def validate_output(stdout: str) -> None:
    """Verify key controls actually parsed, instead of trusting source text."""
    lines = {}
    for line in stdout.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            lines[parts[0].lower()] = parts[1].strip()
    for key, expected in REQUIRED.items():
        if lines.get(key) != expected:
            raise RuntimeError(f"OpenSSH rejected expected setting: {key}")


def run() -> None:
    if sys.platform != "linux":
        raise RuntimeError("This smoke test requires Linux user namespaces.")
    for program in ("unshare", "ssh-keygen", "sshd"):
        if shutil.which(program) is None:
            raise RuntimeError(f"Required installed program missing: {program}")
    with tempfile.TemporaryDirectory(prefix="gcgit-sshd-config-") as td:
        root = Path(td)
        host_key = root / "ephemeral_ed25519"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host_key)],
            check=True, capture_output=True, timeout=20,
        )
        config = root / "sshd_config"
        config.write_text(
            "Port 22222\nListenAddress 127.0.0.1\nAddressFamily inet\n"
            f"HostKey {host_key}\n"
            f"PidFile {root / 'sshd.pid'}\n"
            f"AuthorizedKeysFile {root / 'authorized_keys'}\n"
            "PasswordAuthentication no\nKbdInteractiveAuthentication no\n"
            "PubkeyAuthentication yes\nUsePAM no\n"
            # A root-namespace test fixture ONLY; a real service account must
            # be non-root, with PermitRootLogin no in reviewed host settings.
            "PermitRootLogin prohibit-password\n"
            "PermitTTY no\nAllowTcpForwarding no\nAllowAgentForwarding no\n"
            "X11Forwarding no\nPermitTunnel no\nPermitUserEnvironment no\n"
            "LogLevel VERBOSE\nMaxSessions 2\nLoginGraceTime 20\n",
            encoding="utf-8",
        )
        # Mount /run only in the ephemeral mount namespace; no host changes.
        # The new network namespace has no external listeners or network access.
        validate_command = (
            "mount -t tmpfs tmpfs /run && mkdir -p /run/sshd && "
            "chmod 755 /run/sshd && exec /usr/sbin/sshd -T -f "
            + shlex.quote(str(config))
        )
        result = subprocess.run(
            ["unshare", "-Ur", "-m", "-n", "sh", "-c", validate_command],
            capture_output=True, text=True, timeout=20, check=False,
        )
        if result.returncode:
            raise RuntimeError(
                f"Isolated sshd -T failed (exit {result.returncode}). "
                "Namespace permission or OpenSSH setup may be unavailable."
            )
        validate_output(result.stdout)
    print("PASS: isolated OpenSSH config parsed with expected key-only restrictions.")
    print("No daemon started, no TCP port opened, no host SSH settings changed.")


if __name__ == "__main__":
    try:
        run()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
