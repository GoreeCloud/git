#!/usr/bin/env python3
"""Opt-in real OpenSSH acceptance in disposable, unprivileged Linux namespaces.

This is a local synthetic integration test, NOT production SSH deployment.
Requires caller-owned subuid/subgid mapping, user/mount/network namespaces, Git,
OpenSSH client/server, and generated test-only keys. No host socket or key change.
Run explicitly: python3 scripts/smoke-sshd-live.py
Exit 77 denotes unavailable namespace prerequisites.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))


def execute(argv, *, env=None, timeout=20, expected=0):
    result = subprocess.run(argv, env=env, text=True, capture_output=True, timeout=timeout)
    if expected is not None and result.returncode != expected:
        raise RuntimeError(
            f"Fixture command failed (exit {result.returncode}): {argv[0]} "
            f"{argv[1] if len(argv) > 1 else ''}; output tail: {result.stderr[-350:]}"
        )
    return result


def mapping_range(filename: str) -> tuple[int, int] | None:
    """Only use subordinate ID ranges explicitly allocated to the current user."""
    import pwd
    username = pwd.getpwuid(os.getuid()).pw_name
    try:
        lines = Path(filename).read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        pieces = line.strip().split(":")
        if len(pieces) != 3 or pieces[0] not in (username, str(os.getuid())):
            continue
        try:
            start, count = int(pieces[1]), int(pieces[2])
        except ValueError:
            continue
        if count >= 1001 and start > 0:
            return start, min(count, 65536)
    return None


def test_inside() -> None:
    # Fail closed *before mounting*: root on the actual host must never be
    # able to run the inner entrypoint outside separate user/mount/net spaces.
    uid_lines = Path("/proc/self/uid_map").read_text().splitlines()
    mapped = []
    for line in uid_lines:
        pieces = line.split()
        if len(pieces) == 3:
            mapped.append(tuple(int(x) for x in pieces))
    if os.geteuid() != 0 or not any(
        inner == 0 and outer > 0 and count >= 1001
        for inner, outer, count in mapped
    ):
        raise RuntimeError("Test requires synthetic namespace UID 0, never host root.")
    for ns in ("mnt", "net"):
        # Reading /proc/1 namespace links is often forbidden under subordinate
        # UID maps. Compare to the caller's namespace identities instead.
        origin = os.environ.get("GCGIT_PARENT_" + ns.upper() + "NS")
        current = os.readlink("/proc/self/ns/" + ns)
        if not origin or current == origin:
            raise RuntimeError("Refusing to run without separate mount and network namespaces.")
    execute(["mount", "-t", "tmpfs", "-o", "mode=755", "tmpfs", "/run"])
    # sshd StrictModes rejects the host-owned sticky /tmp from a subordinate
    # UID namespace. Use a tmpfs owned by namespace root, while bind-mounting
    # the inspected checkout read-only into a separate private namespace path.
    checkout = Path("/run/gcgit-source")
    checkout.mkdir(mode=0o755)
    execute(["mount", "--bind", str(PROJECT), str(checkout)])
    execute(["mount", "-o", "remount,bind,ro", str(checkout)])
    execute(["mount", "-t", "tmpfs", "-o", "mode=1777", "tmpfs", "/tmp"])
    sys.path.insert(0, str(checkout / "src"))
    Path("/run/sshd").mkdir(mode=0o755)
    execute(["ip", "link", "set", "lo", "up"])
    from goreecloud_git.core import Store, git

    with tempfile.TemporaryDirectory(prefix="goreecloud-git-ssh-acceptance-") as path:
        root = Path(path)
        store = Store(root / "storage")
        store.init()
        first = store.create("first")
        store.create("other")
        work = root / "work"
        execute(["git", "init", "-b", "main", str(work)])
        (work / "test.txt").write_text("synthetic-only\n", encoding="utf-8")
        execute(["git", "-C", str(work), "add", "test.txt"])
        execute(["git", "-C", str(work), "-c", "user.name=Fixture",
                 "-c", "user.email=fixture@example.invalid", "commit", "-m", "first"])
        execute(["git", "-C", str(work), "push", str(first), "main"])
        expected_ref = git("--git-dir", str(first), "rev-parse", "refs/heads/main")
        for name in ("host", "read", "write", "unknown"):
            execute(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(root / name)])
        known = root / "known_hosts"
        pub = (root / "host.pub").read_text().split()
        port = 22923
        known.write_text(f"[127.0.0.1]:{port} {pub[0]} {pub[1]}\n", encoding="ascii")
        # Python sources are read-only fixtures here and the forced command is
        # fixed by the test harness, not supplied by the SSH client.
        source_path = Path("/run/gcgit-source/src")
        command_base = (
            f"PYTHONPATH={source_path} /usr/bin/python3 -m goreecloud_git.cli"
            f" --root {store.root} serve-ssh --repo first"
        )
        auth_dir = Path("/run/gcgit-auth")
        auth_dir.mkdir(mode=0o700)
        authorized = auth_dir / "authorized_keys"
        lines = []
        for identity, allow_push in (("read", False), ("write", True)):
            pubkey = (root / (identity + ".pub")).read_text().strip()
            command = command_base + (" --allow-push" if allow_push else "")
            lines.append('restrict,command="' + command + '" ' + pubkey)
        authorized.write_text("\n".join(lines) + "\n", encoding="ascii")
        authorized.chmod(0o600)
        # Enforce explicit fixture permissions even though sshd's StrictModes
        # cannot validate the outer host / ownership through this UID mapping.
        for file_path, mode in ((auth_dir, 0o700), (authorized, 0o600),
                                (store.root, 0o700), (store.repos, 0o700),
                                (first, 0o700)):
            if stat.S_IMODE(file_path.stat().st_mode) != mode:
                raise RuntimeError("Unexpected fixture permission boundary.")
        config = root / "sshd_config"
        config.write_text(
            f"Port {port}\nListenAddress 127.0.0.1\nAddressFamily inet\n"
            f"HostKey {root / 'host'}\nAuthorizedKeysFile {authorized}\n"
            f"PidFile {root / 'sshd.pid'}\n"
            "PasswordAuthentication no\nKbdInteractiveAuthentication no\n"
            "UsePAM no\nPubkeyAuthentication yes\n"
            "PermitRootLogin forced-commands-only\n"
            "AllowTcpForwarding no\nAllowAgentForwarding no\n"
            "PermitTTY no\nX11Forwarding no\nPermitTunnel no\n"
            # This synthetic namespace maps host root-owned / to nobody.
            # StrictModes is disabled ONLY for the isolated disposable test;
            # staging/production MUST enable it and test actual file ownership.
            "PermitUserEnvironment no\nStrictModes no\n"
            "MaxSessions 2\nLoginGraceTime 15\nLogLevel VERBOSE\n",
            encoding="ascii",
        )
        execute(["/usr/sbin/sshd", "-t", "-f", str(config)])
        server_log = root / "sshd.log"
        log_sink = server_log.open("w")
        server = subprocess.Popen(
            ["/usr/sbin/sshd", "-D", "-e", "-f", str(config)],
            stdout=subprocess.DEVNULL, stderr=log_sink, text=True,
        )
        try:
            for _ in range(60):
                if server.poll() is not None:
                    raise RuntimeError("Isolated sshd exited before accepting a connection.")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Isolated sshd did not accept loopback connections.")

            def ssh_args(key, known_hosts=None):
                return [
                    "ssh", "-F", "/dev/null", "-o", "BatchMode=yes",
                    "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
                    "-o", f"UserKnownHostsFile={known_hosts or known}",
                    "-o", "ConnectTimeout=4", "-p", str(port),
                    "-i", str(root / key), "root@127.0.0.1",
                ]

            # Verify actual host-key-pinned public-key authentication, not just
            # Git transport emulation. The read key never receives write scope.
            # Native Git ls-remote/clone below drive the real upload-pack wire
            # protocol. Calling upload-pack by hand without protocol input
            # would legitimately block on its stdin.
            unauthorized = execute(ssh_args("unknown") + ["id"], expected=None)
            if unauthorized.returncode == 0:
                raise RuntimeError("Unknown SSH key unexpectedly authenticated.")
            wrong_hosts = root / "wrong_hosts"
            bogus = (root / "unknown.pub").read_text().split()
            wrong_hosts.write_text(
                f"[127.0.0.1]:{port} {bogus[0]} {bogus[1]}\n", encoding="ascii"
            )
            wrong_host = execute(ssh_args("read", wrong_hosts) + ["id"], expected=None)
            if (wrong_host.returncode == 0 or not any(
                phrase in wrong_host.stderr.lower() for phrase in
                ("host key verification failed", "remote host identification has changed")
            )):
                raise RuntimeError("Wrong SSH host key was not conclusively rejected.")
            shell = execute(ssh_args("read") + ["id"], expected=None)
            if shell.returncode == 0:
                raise RuntimeError("SSH key unexpectedly launched arbitrary shell.")
            cross = execute(ssh_args("read") + ["git-upload-pack other.git"], expected=None)
            if cross.returncode == 0:
                raise RuntimeError("Read key accessed a second repository.")
            remote = f"ssh://root@127.0.0.1:{port}{first}"
            env = dict(os.environ)
            env["GIT_SSH_COMMAND"] = " ".join(ssh_args("read")[:-1])
            clone = root / "cloned"
            cloned = execute(["git", "clone", remote, str(clone)], env=env, expected=None)
            if cloned.returncode != 0:
                raise RuntimeError("Native SSH Git clone failed: " + cloned.stderr[-300:])
            if (clone / "test.txt").read_text() != "synthetic-only\n":
                raise RuntimeError("Cloned fixture bytes differ.")
            (work / "test.txt").write_text("second fixture\n")
            execute(["git", "-C", str(work), "add", "test.txt"])
            execute(["git", "-C", str(work), "-c", "user.name=Fixture",
                     "-c", "user.email=fixture@example.invalid", "commit", "-m", "second"])
            proposed_ref = execute(["git", "-C", str(work), "rev-parse", "main"]).stdout.strip()
            push = execute(["git", "-C", str(work), "push", remote, "main"],
                           env=env, expected=None)
            if push.returncode == 0:
                raise RuntimeError("Read-only SSH key unexpectedly allowed push.")
            if git("--git-dir", str(first), "rev-parse", "refs/heads/main") != expected_ref:
                raise RuntimeError("Rejected push changed the ref.")
            write_env = dict(env)
            write_env["GIT_SSH_COMMAND"] = " ".join(ssh_args("write")[:-1])
            written = execute(["git", "-C", str(work), "push", remote, "main"],
                              env=write_env, expected=None)
            if written.returncode != 0:
                raise RuntimeError("Explicit write-key Git push failed: " + written.stderr[-300:])
            if git("--git-dir", str(first), "rev-parse", "refs/heads/main") != proposed_ref:
                raise RuntimeError("Write-key push did not update the expected Git ref.")
            store.verify("first")
            print("PASS: namespace-isolated live sshd with pinned host key, native clone, "
                  "unknown-key/wrong-host/shell/cross-repo/read-only denial, "
                  "and explicitly authorized write-key push.")
        finally:
            server.terminate()
            try:
                server.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill()
                server.communicate()
            log_sink.close()


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--inner":
        test_inside()
        return 0
    if sys.platform != "linux":
        print("SKIP: Linux namespace support required.")
        return 77
    required = ("unshare", "newuidmap", "newgidmap", "mount", "ip",
                "sshd", "ssh", "ssh-keygen", "git", "python3")
    if any(shutil.which(x) is None for x in required):
        print("SKIP: required installed OpenSSH or namespace tool unavailable.")
        return 77
    users, groups = mapping_range("/etc/subuid"), mapping_range("/etc/subgid")
    if users is None or groups is None:
        print("SKIP: no authorized subordinate UID/GID ranges for unprivileged test.")
        return 77
    command = [
        "unshare", "--map-users=0:%d:%d" % users,
        "--map-groups=0:%d:%d" % groups,
        "--setuid", "0", "--setgid", "0", "--mount", "--net",
        "python3", str(Path(__file__).resolve()), "--inner",
    ]
    namespace_env = dict(os.environ)
    for ns in ("mnt", "net"):
        namespace_env["GCGIT_PARENT_" + ns.upper() + "NS"] = os.readlink(
            "/proc/self/ns/" + ns
        )
    result = subprocess.run(command, env=namespace_env, text=True,
                            capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError(
            "Isolated live-SSH acceptance unavailable or failed (exit "
            f"{result.returncode}): {result.stderr[-650:]}"
        )
    print(result.stdout.strip())
    print("No host listener, production SSH account, root config, or keys modified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print("FAIL:", str(exc), file=sys.stderr)
        raise SystemExit(1)
