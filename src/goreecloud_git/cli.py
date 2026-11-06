"""CLI-first administration for private bare Git repositories."""
import argparse
import ipaddress
import os
import sys

from .core import GitError, Store, git


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gcgit", description="GoreeCloud Git (owner-operated, private SSH Git hosting)")
    p.add_argument("--root", help="Private storage directory; defaults to ~/.local/share/goreecloud-git")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Initialize owner-private storage (0700)")
    create = sub.add_parser("create", help="Create a private bare Git repository")
    create.add_argument("name")
    sub.add_parser("list", help="List private repository names")
    info = sub.add_parser("info", help="Print repository details")
    info.add_argument("name")
    remote = sub.add_parser("remote", help="Print the native SSH Git remote URL")
    remote.add_argument("name")
    remote.add_argument("--host", required=True, help="Your self-hosted SSH hostname")
    remote.add_argument("--user", default="gcgit", help="Dedicated host Unix user")
    remote.add_argument("--port", type=int, default=22)
    sub.add_parser("web-token", help="Rotate the owner-only optional web login token")
    serve = sub.add_parser("serve-web", help="Serve read-only web interface on loopback")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    ssh = sub.add_parser("serve-ssh", help="Restricted forced-command Git transport (OpenSSH only)")
    ssh.add_argument("--repo", required=True, help="Only the named private repository may be accessed")
    ssh.add_argument("--allow-push", action="store_true", help="Explicitly permit Git push as well as clone/fetch")
    ssh.add_argument("--wall-seconds", type=int, default=600, help="Git connection wall-time limit, 1-7200 seconds (default 600)")
    ssh.add_argument("--cpu-seconds", type=int, default=300, help="Git process CPU-time limit, 1-3600 seconds (default 300)")
    ssh.add_argument("--memory-mib", type=int, default=2048, help="Git process virtual-memory limit, 128-16384 MiB (default 2048)")
    verify = sub.add_parser("verify", help="Check object integrity without changing repository contents")
    verify.add_argument("name")
    sub.add_parser("verify-all", help="Check all complete private repositories, reporting every failure")
    sub.add_parser("doctor", help="Check storage and Git prerequisites")
    return p


def run(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    args = parser().parse_args(argv)
    store = Store(args.root)
    try:
        if args.command == "init":
            print(f"Private storage initialized: {store.init()}")
        elif args.command == "create":
            print(f"Private repository created: {store.create(args.name)}")
        elif args.command == "list":
            for name in store.names():
                print(name)
        elif args.command == "info":
            info = store.info(args.name)
            print(f"Name: {info['name']}\nPath: {info['path']}\nCommits: {info['commits']}")
            print("Branches: " + (", ".join(info["branches"]) or "(none)"))
        elif args.command == "remote":
            print(store.ssh_url(args.name, args.host, args.user, args.port))
        elif args.command == "web-token":
            print("New web token (copy now; do not share):", store.rotate_token())
        elif args.command == "serve-web":
            if not ipaddress.ip_address(args.host).is_loopback:
                raise ValueError("Web service must bind to a loopback IP; use an authenticated TLS reverse proxy or SSH tunnel.")
            if not 1 <= args.port <= 65535:
                raise ValueError("Invalid TCP port.")
            from .web import serve
            serve(store, args.host, args.port)
        elif args.command == "serve-ssh":
            from .ssh import serve_ssh
            return serve_ssh(
                store, args.repo, allow_push=args.allow_push,
                wall_seconds=args.wall_seconds, cpu_seconds=args.cpu_seconds,
                memory_mib=args.memory_mib,
            )
        elif args.command == "verify":
            store.verify(args.name)
            print(f"Integrity check passed: {args.name}")
        elif args.command == "verify-all":
            names = store.names()
            failed = 0
            for name in names:
                try:
                    store.verify(name)
                except (GitError, OSError):
                    failed += 1
                    print(f"FAIL: {name}", file=sys.stderr)
                else:
                    print(f"PASS: {name}")
            if not names:
                print("No complete private repositories to verify.")
            print(f"Integrity sweep: {len(names) - failed}/{len(names)} passed.")
            return 1 if failed else 0
        elif args.command == "doctor":
            print("Git:", git("--version"))
            store.ready()
            print(f"Private storage: OK ({store.root})")
            if not store.token_path().exists() and not store.token_path().is_symlink():
                print("Web token: not configured (optional)")
            else:
                store.read_token()  # fail closed on weak permissions or symlinks
                print("Web token: configured (permissions verified)")
        return 0
    except (OSError, ValueError, GitError) as exc:
        print(f"gcgit: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
