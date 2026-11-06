#!/usr/bin/env python3
"""Opt-in synthetic non-root OpenSSH/StrictModes integration in user+mount+net ns.

No host service, port, account or keys are changed. Uses a temp tmpfs chroot,
synthetic service UID 1001 and caller-assigned subordinate UID/GID mappings.
Only run intentionally on an authorized Linux development machine.
"""
from __future__ import annotations

import os
from pathlib import Path
import pwd
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]
SERVICE_UID = 1001
SERVICE_GID = 1001
PORT = 22924


def run(*args: str, timeout: float = 20, env=None, check=True):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, env=env)
    if check and result.returncode != 0:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {result.stderr[-400:]}")
    return result


def assigned_range(file: str) -> tuple[int, int] | None:
    try:
        user = pwd.getpwuid(os.getuid()).pw_name
        content = Path(file).read_text()
    except (KeyError, OSError):
        return None
    for line in content.splitlines():
        parts = line.split(":")
        if len(parts) != 3 or parts[0] not in (user, str(os.getuid())):
            continue
        try:
            begin, count = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        if begin > 0 and count >= 65535:
            return begin, min(count, 65536)
    return None


def verify_namespace() -> None:
    mapping = [
        tuple(map(int, parts))
        for line in Path("/proc/self/uid_map").read_text().splitlines()
        if len(parts := line.split()) == 3
    ]
    if os.geteuid() != 0 or not any(
        inner == 0 and outer > 0 and count >= 65535
        for inner, outer, count in mapping
    ):
        raise RuntimeError("Refusing to run outside synthetic subordinate-ID root.")
    for kind in ("mnt", "net"):
        origin = os.environ.get("GCGIT_PARENT_" + kind.upper() + "NS")
        if not origin or origin == os.readlink("/proc/self/ns/" + kind):
            raise RuntimeError("Refusing to run without separate mount/network namespace.")


def build_chroot(root: Path) -> None:
    # IMPORTANT: the caller has already proved it is in an isolated mount ns.
    root.mkdir(mode=0o755)
    run("mount", "-t", "tmpfs", "-o", "mode=755", "tmpfs", str(root))
    for folder in ("usr", "etc", "proc", "dev", "tmp", "run", "home",
                   "opt", "opt/gcgit-src"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "home").chmod(0o755)
    (root / "opt").chmod(0o755)
    run("mount", "--bind", "/usr", str(root / "usr"))
    run("mount", "-o", "remount,bind,ro", str(root / "usr"))
    for link, dest in (("bin", "usr/bin"), ("lib", "usr/lib"),
                       ("lib64", "usr/lib64"), ("sbin", "usr/sbin")):
        (root / link).symlink_to(dest)
    run("mount", "--bind", str(PROJECT), str(root / "opt/gcgit-src"))
    run("mount", "-o", "remount,bind,ro", str(root / "opt/gcgit-src"))
    run("mount", "-t", "proc", "proc", str(root / "proc"))
    # A subordinate UID namespace cannot mknod or bind the whole host /dev.
    # Bind only the five standard character devices needed by Git/OpenSSH
    # into the test-only mount tree, not host-controlled disks or sockets.
    for device in ("null", "zero", "random", "urandom", "tty"):
        destination = root / "dev" / device
        destination.touch(mode=0o600)
        run("mount", "--bind", "/dev/" + device, str(destination))
    (root / "tmp").chmod(0o1777)
    (root / "run/sshd").mkdir(mode=0o755)
    (root / "etc/passwd").write_text(
        "root:x:0:0:root:/root:/bin/sh\n"
        "sshd:x:130:65534:sshd:/run/sshd:/usr/sbin/nologin\n"
        "gcgit:x:1001:1001:Git test service:/home/gcgit:/bin/sh\n",
        encoding="ascii")
    (root / "etc/group").write_text(
        "root:x:0:\nnogroup:x:65534:\ngcgit:x:1001:\n", encoding="ascii")
    (root / "etc/nsswitch.conf").write_text(
        "passwd: files\ngroup: files\nhosts: files dns\n", encoding="ascii")
    (root / "etc/hosts").write_text("127.0.0.1 localhost\n", encoding="ascii")
    home = root / "home/gcgit"
    home.mkdir(mode=0o700)
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(mode=0o700)
    for p in (home, ssh_dir):
        os.chown(p, SERVICE_UID, SERVICE_GID)


def fixture() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("Synthetic namespace root is required for sshd fixture.")
    from goreecloud_git.core import Store, git

    home = Path("/home/gcgit")
    store = Store(home / "storage")
    store.init()
    alpha = store.create("alpha")
    store.create("other")
    work = Path("/tmp/work")
    run("git", "init", "-b", "main", str(work))
    (work / "hello.txt").write_text("synthetic Git data\n")
    run("git", "-C", str(work), "add", "hello.txt")
    run("git", "-C", str(work), "-c", "user.name=Fixture",
        "-c", "user.email=fixture@example.invalid", "commit", "-m", "initial")
    run("git", "-C", str(work), "push", str(alpha), "main")

    # Account data is owned exclusively by synthetic UID1001 in tmpfs.
    for base, dirs, files in os.walk(store.root):
        os.chown(base, SERVICE_UID, SERVICE_GID)
        for filename in files:
            os.chown(Path(base) / filename, SERVICE_UID, SERVICE_GID)
    for repo in (alpha, store.path("other")):
        if stat.S_IMODE(repo.stat().st_mode) != 0o700:
            raise RuntimeError("Bare repository mode is not private.")
    for name in ("host", "read", "write", "unknown"):
        run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", f"/tmp/{name}")
    pubhost = Path("/tmp/host.pub").read_text().split()
    known = Path("/tmp/known_hosts")
    known.write_text(f"[127.0.0.1]:{PORT} {pubhost[0]} {pubhost[1]}\n")
    forced = (
        "PYTHONPATH=/opt/gcgit-src/src /usr/bin/python3 -m goreecloud_git.cli"
        " --root /home/gcgit/storage serve-ssh --repo alpha"
    )
    auth = home / ".ssh/authorized_keys"
    auth.write_text(
        'restrict,command="' + forced + '" ' + Path("/tmp/read.pub").read_text().strip() + "\n"
        + 'restrict,command="' + forced + ' --allow-push" '
        + Path("/tmp/write.pub").read_text().strip() + "\n")
    auth.chmod(0o600)
    os.chown(auth, SERVICE_UID, SERVICE_GID)

    for candidate, mode, uid in (
        (Path("/"), 0o755, 0),
        (Path("/home"), 0o755, 0),
        (home, 0o700, SERVICE_UID),
        (home / ".ssh", 0o700, SERVICE_UID),
        (auth, 0o600, SERVICE_UID),
        (store.root, 0o700, SERVICE_UID),
    ):
        if stat.S_IMODE(candidate.stat().st_mode) != mode or candidate.stat().st_uid != uid:
            raise RuntimeError(f"Unexpected synthetic account ownership for {candidate}")

    cfg = Path("/tmp/sshd_config")
    cfg.write_text(
        f"Port {PORT}\nListenAddress 127.0.0.1\nAddressFamily inet\n"
        "HostKey /tmp/host\nPidFile /run/gcgit-sshd.pid\n"
        "AuthorizedKeysFile .ssh/authorized_keys\n"
        "UsePAM no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n"
        "PubkeyAuthentication yes\nPermitRootLogin no\nAllowUsers gcgit\n"
        "StrictModes yes\nPermitUserEnvironment no\n"
        "AllowTcpForwarding no\nAllowAgentForwarding no\n"
        "PermitTTY no\nX11Forwarding no\nPermitTunnel no\n"
        "MaxSessions 2\nLoginGraceTime 15\nUseDNS no\nLogLevel VERBOSE\n"
    )
    run("/usr/sbin/sshd", "-t", "-f", str(cfg))
    effective = run(
        "/usr/sbin/sshd", "-T", "-f", str(cfg),
        "-C", f"user=gcgit,host=localhost,addr=127.0.0.1,laddr=127.0.0.1,lport={PORT}"
    ).stdout.lower().splitlines()
    for setting in ("strictmodes yes", "permitrootlogin no",
                    "passwordauthentication no", "kbdinteractiveauthentication no",
                    "allowtcpforwarding no", "allowagentforwarding no"):
        if setting not in effective:
            raise RuntimeError("Unexpected effective OpenSSH security setting: " + setting)
    log_path = Path("/tmp/sshd.log")
    with log_path.open("w") as log:
        server = subprocess.Popen(
            ["/usr/sbin/sshd", "-D", "-e", "-f", str(cfg)],
            stdout=subprocess.DEVNULL, stderr=log)
        try:
            for _ in range(70):
                if server.poll() is not None:
                    raise RuntimeError("Synthetic sshd exited: " + log_path.read_text()[-700:])
                try:
                    with socket.create_connection(("127.0.0.1", PORT), timeout=.1):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("Namespace sshd did not start on loopback.")
            def ssh_args(key, hostfile=known):
                return ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes",
                        "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
                        "-o", f"UserKnownHostsFile={hostfile}",
                        "-o", "ConnectTimeout=4", "-p", str(PORT),
                        "-i", f"/tmp/{key}", "gcgit@127.0.0.1"]
            bad = run(*ssh_args("unknown"), "id", check=False)
            if bad.returncode == 0:
                raise RuntimeError("Unknown key unexpectedly authenticated.")
            wrong_host = Path("/tmp/wrong_hosts")
            wrong = Path("/tmp/unknown.pub").read_text().split()
            wrong_host.write_text(f"[127.0.0.1]:{PORT} {wrong[0]} {wrong[1]}\n")
            bad = run(*ssh_args("read", wrong_host), "id", check=False)
            if bad.returncode == 0 or "host key verification failed" not in bad.stderr.lower():
                raise RuntimeError("Incorrect host key was not rejected.")
            bad = run(*ssh_args("read"), "id", check=False)
            if bad.returncode == 0:
                raise RuntimeError("Restricted key launched a shell.")
            bad = run(*ssh_args("read"), "git-upload-pack other.git", check=False)
            if bad.returncode == 0:
                raise RuntimeError("Restricted key accessed another repository.")

            url = f"ssh://gcgit@127.0.0.1:{PORT}{alpha}"
            env = dict(os.environ)
            env["GIT_SSH_COMMAND"] = " ".join(ssh_args("read")[:-1])
            clone = run("git", "clone", url, "/tmp/clone", env=env, check=False, timeout=30)
            if clone.returncode:
                raise RuntimeError(
                    "Synthetic non-root StrictModes SSH clone failed: "
                    + clone.stderr[-250:] + " server: " + log_path.read_text()[-900:]
                )
            if Path("/tmp/clone/hello.txt").read_text() != "synthetic Git data\n":
                raise RuntimeError("Cloned content mismatch.")
            # A writable authorized-keys directory must be rejected by
            # OpenSSH's actual StrictModes enforcement (not just sshd -T).
            ssh_dir = home / ".ssh"
            ssh_dir.chmod(0o777)
            try:
                denied = run("git", "ls-remote", url, env=env,
                             check=False, timeout=25)
                if denied.returncode == 0 or "permission denied" not in denied.stderr.lower():
                    raise RuntimeError("StrictModes failed to reject writable .ssh.")
            finally:
                ssh_dir.chmod(0o700)

            # Revoke the disposable read key in the synthetic key list and
            # verify it can no longer authenticate; then restore the fixture.
            authorized_before = auth.read_text()
            write_line = Path("/tmp/write.pub").read_text().strip()
            auth.write_text(
                "\n".join(line for line in authorized_before.splitlines()
                          if write_line in line) + "\n"
            )
            try:
                revoked = run("git", "ls-remote", url, env=env,
                              check=False, timeout=25)
                if revoked.returncode == 0 or "permission denied" not in revoked.stderr.lower():
                    raise RuntimeError("Revoked SSH key still authenticated.")
            finally:
                auth.write_text(authorized_before)
            restored = run("git", "ls-remote", url, env=env,
                           check=False, timeout=25)
            if restored.returncode != 0:
                raise RuntimeError("Restored read-only SSH key was not accepted.")

            original = git("--git-dir", str(alpha), "rev-parse", "refs/heads/main")
            (work / "hello.txt").write_text("second fixture\n")
            run("git", "-C", str(work), "add", "hello.txt")
            run("git", "-C", str(work), "-c", "user.name=Fixture",
                "-c", "user.email=fixture@example.invalid", "commit", "-m", "second")
            proposed = run("git", "-C", str(work), "rev-parse", "main").stdout.strip()
            bad_push = run("git", "-C", str(work), "push", url, "main",
                           env=env, check=False, timeout=30)
            if bad_push.returncode == 0:
                raise RuntimeError("Read-only key accepted a write.")
            if git("--git-dir", str(alpha), "rev-parse", "refs/heads/main") != original:
                raise RuntimeError("Rejected write modified bare Git ref.")
            env["GIT_SSH_COMMAND"] = " ".join(ssh_args("write")[:-1])
            good = run("git", "-C", str(work), "push", url, "main",
                       env=env, check=False, timeout=30)
            if good.returncode:
                raise RuntimeError("Authorized write key was denied: "
                                   + good.stderr[-300:] + " sshd:" + log_path.read_text()[-750:])
            if git("--git-dir", str(alpha), "rev-parse", "refs/heads/main") != proposed:
                raise RuntimeError("Authorized write did not update ref.")
            store.verify("alpha")
            print("PASS: synthetic non-root SSH account with effective StrictModes yes; "
                  "pinned-host clone, wrong/unknown key denial, active unsafe-mode "
                  "rejection, revoked-key denial, shell/cross-repo/read-only denial, "
                  "authorized write and Git fsck.")
        finally:
            server.terminate()
            try:
                server.wait(timeout=4)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


def outer() -> int:
    verify_namespace()
    run("ip", "link", "set", "lo", "up")
    # Only under an already private mount namespace: no host mounts are changed.
    with tempfile.TemporaryDirectory(prefix="gcgit-strict-ns-") as tmp:
        root = Path(tmp) / "rootfs"
        try:
            build_chroot(root)
            env = dict(os.environ)
            env["PYTHONPATH"] = "/opt/gcgit-src/src"
            result = subprocess.run(
                ["chroot", str(root), "/usr/bin/python3",
                 "/opt/gcgit-src/scripts/smoke-sshd-strict.py", "--inner"],
                text=True, capture_output=True, env=env, timeout=110)
            if result.returncode:
                raise RuntimeError(
                    "StrictModes live SSH test failed: "
                    + result.stderr[-3500:] + result.stdout[-250:]
                )
            print(result.stdout.strip())
        finally:
            # Remove only our own explicitly created mounts, and only from the
            # separate mount namespace. Never attempt to recursively unlink a
            # bind-mounted source checkout or a host path.
            for fragment in ("opt/gcgit-src", "dev/tty", "dev/urandom",
                             "dev/random", "dev/zero", "dev/null",
                             "proc", "usr", ""):
                mountpoint = root / fragment
                subprocess.run(["umount", str(mountpoint)],
                               capture_output=True, timeout=6)
    return 0


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--inner":
        verify_namespace()  # Never allow direct inner invocation on the host.
        fixture()
        return 0
    if len(sys.argv) == 2 and sys.argv[1] == "--outer":
        return outer()
    if len(sys.argv) > 1:
        raise ValueError("Unknown test argument.")
    if sys.platform != "linux" or os.geteuid() == 0:
        print("SKIP: requires non-root authorized Linux developer.")
        return 77
    required = ("unshare", "newuidmap", "newgidmap", "mount", "chroot",
                "ip", "sshd", "ssh", "ssh-keygen", "git", "python3")
    if any(shutil.which(name) is None for name in required):
        print("SKIP: missing OpenSSH or unprivileged namespace tool.")
        return 77
    uidmap, gidmap = assigned_range("/etc/subuid"), assigned_range("/etc/subgid")
    if not uidmap or not gidmap:
        print("SKIP: no assigned subordinate UID and GID ranges.")
        return 77
    env = dict(os.environ)
    for namespace in ("mnt", "net"):
        env["GCGIT_PARENT_" + namespace.upper() + "NS"] = os.readlink(
            "/proc/self/ns/" + namespace
        )
    command = [
        "unshare", f"--map-users=0:{uidmap[0]}:{uidmap[1]}",
        f"--map-groups=0:{gidmap[0]}:{gidmap[1]}",
        "--setuid", "0", "--setgid", "0", "--mount", "--net",
        "--pid", "--fork", "--kill-child", "--mount-proc",
        "python3", str(Path(__file__).resolve()), "--outer",
    ]
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=150)
    if result.returncode:
        raise RuntimeError(
            f"Isolated StrictModes acceptance failed (exit {result.returncode}): "
            + result.stderr[-1100:]
        )
    print(result.stdout.strip())
    print("No host SSH account, sshd config, keys, network listener, firewall, "
          "or production private Git data changed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        import traceback
        traceback.print_exc()
        print("FAIL:", exc, file=sys.stderr)
        raise SystemExit(1)
