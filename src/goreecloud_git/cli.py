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
        elif args.command == "doctor":
            print("Git:", git("--version"))
            store.ready()
            print(f"Private storage: OK ({store.root})")
            print("Web token:", "configured" if store.token_path().exists() else "not configured (optional)")
        return 0
    except (OSError, ValueError, GitError) as exc:
        print(f"gcgit: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
