# GoreeCloud Git

**Private Git repositories. Native Git and SSH. CLI first. Optional read-only web.**

GoreeCloud Git is a small, original Python 3.11+ self-hosted service for operating **your own private bare Git repositories**. This **public GitHub repository contains only source code**. Repositories, credentials, backups, and private history live on your chosen private machine or VPS, not on GitHub.

**Status: v0.1.0 development foundation.** Implemented and locally tested features are described below. This is not a production-ready, multi-user alternative to GitHub, GitLab, or Forgejo. It does not yet implement hosted CI/CD, pull requests, issues, Git LFS, a multi-user ACL, or an HTTP Git protocol.

## Requirements

- Linux/macOS or an equivalent Unix host with Python 3.11+ and Git.
- OpenSSH server and an SSH key for remote clone/push (operated separately).
- Owner-controlled, non-root Unix account with a private home/data directory.
- The optional browser requires no Node.js, frontend build, or third-party Python packages.

## Local quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .

gcgit init
gcgit create my-private-repo
gcgit list
gcgit info my-private-repo
gcgit doctor
gcgit verify my-private-repo   # read-only Git object and reference integrity check
```

Storage defaults to `~/.local/share/goreecloud-git/repos/my-private-repo.git` under the user running `gcgit`. Change it using `gcgit --root /path/to/private/storage ...` or `GC_GIT_ROOT`. Owner-only mode `0700` is required for the storage root and `repos/` directory. This tool will **not** silently chmod pre-existing directories.

The repository is a standard bare Git repository. On the **same machine and account**, test a push and clone using Git:

```bash
mkdir my-private-repo-work && cd my-private-repo-work
git init -b main
echo hello > README.md
git add README.md
git -c user.name=LocalTester -c user.email=local@example.invalid commit -m 'Initial commit'
git remote add origin "$HOME/.local/share/goreecloud-git/repos/my-private-repo.git"
git push -u origin main
cd ..
git clone "$HOME/.local/share/goreecloud-git/repos/my-private-repo.git" check-clone
```

This example creates a disposable demonstration commit. Run it only in a suitable development environment; do not push secrets.

## Native SSH Git access

GoreeCloud Git delegates remote Git authentication and Git transport to **OpenSSH and Git**. Do not expose raw repository files over HTTP. A deployment should use a dedicated non-root Unix service account (for example `gcgit`), SSH key authentication, and a restricted `git-shell` login shell. Install the CLI and initialize/create repositories **as that same account**; grant no world/group access to the data root.

After SSH user, keys, firewall, and host-key trust are separately configured, get a remote URL:

```bash
gcgit remote my-private-repo --host git.example.net --user gcgit
# ssh://gcgit@git.example.net:22/home/gcgit/.local/share/goreecloud-git/repos/my-private-repo.git

git clone ssh://gcgit@git.example.net:22/home/gcgit/.local/share/goreecloud-git/repos/my-private-repo.git
# git remote add origin ... ; git push origin main
```

The displayed URL is an example based on a typical service-account home path. **No SSH server, account, DNS, firewall, certificate, or internet-facing endpoint is provisioned by this program.** The `git-shell` restricts shell commands but should be reviewed against your host's SSH forwarding and account policies. Prefer a private network or VPN for administrative access.

## Per-key restricted SSH transport (development preview)

GoreeCloud Git also has an optional `gcgit serve-ssh` forced-command handler. This allows **one explicitly named repository per SSH key**. Its default is **clone/fetch only**; `--allow-push` is required to enable Git receive-pack. It validates Git's `SSH_ORIGINAL_COMMAND` and directly invokes the required Git subcommand without a shell. It does **not** install or configure an SSH daemon, create keys, authenticate users, or implement a multi-user ACL.

On a security-reviewed Linux host, use a dedicated non-root service account and an OpenSSH `authorized_keys` entry of this form (replace every example path and key with verified values):

```text
restrict,command="/opt/goreecloud-git/.venv/bin/gcgit --root /var/lib/goreecloud-git serve-ssh --repo my-private-repo" ssh-ed25519 <KEY_MATERIAL> owner-read-only
```

For a key explicitly authorized to **push to the same single repository**, add `--allow-push` to the forced command. Keep other keys restricted or revoked. Do not place a privileged/unrestricted SSH key alongside restricted keys for the service account. The Unix account must own the private storage and must be unable to read unrelated files.

**Choose one SSH confinement architecture:** the previous `git-shell` approach directly permits Git's standard upload/receive-pack verbs and is administered outside this program. The `gcgit serve-ssh` approach requires an SSH account login shell capable of starting the Python entrypoint (not `git-shell`); compensate with an audited `authorized_keys` forced command plus OpenSSH key restrictions, disabled password logins, and a restrictive `Match User` policy. Never claim that `git-shell` can execute this custom forced command. `restrict` blocks interactive PTY and common forwarding features for that key; validate host-wide SSH policy too.

A native Git remote URL from `gcgit remote ...` is compatible with this mode when its path matches the private bare repository exactly. In testing, a local SSH-command shim exercised clone/fetch and push permissions without starting a network SSH daemon. **Real host key verification, unauthenticated-key rejection, service account isolation, rate/resource controls, and host deployment remain pending.** See [SECURITY.md](SECURITY.md) and [docs/architecture.md](docs/architecture.md).

## Optional browser (read-only)

```bash
gcgit web-token             # outputs a new owner password once; keep it private
gcgit serve-web             # listens only on 127.0.0.1:8787
# Open http://127.0.0.1:8787 from that host.
# Username: owner   Password: the generated web token
```

The browser lists repositories, branch counts, commit totals, and recent history; it has no upload, push, create, delete, or admin API. It uses HTTP Basic authentication and no JavaScript. **Never expose its HTTP port directly on a public interface.** For remote private access, use an SSH tunnel or a properly protected TLS reverse proxy. Example from a trusted client using an authorized SSH administration account:

```bash
ssh -N -L 8787:127.0.0.1:8787 admin@git.example.net
# Then open http://127.0.0.1:8787 locally.
```

Rotating the web token requires restarting the browser service. The web interface is a **development UI**, not yet certified against the canonical GoreeCloud UI token/component and full accessibility acceptance standards.

## Licensing

The original GoreeCloud Git source and documentation in this repository are licensed under the [MIT License](LICENSE) (SPDX: `MIT`). The implementation uses Python standard-library modules and invokes an externally installed Git executable; neither Git itself nor OpenSSH are copied into this repository or relicensed. This permissive license covers the application code, **not** the private repositories or their contents that you host with it.

## Private backup and recovery integration

GoreeCloud Git plans to integrate with the existing [GoreeCloud Backup](https://github.com/GoreeCloud/backup) alpha and its externally installed encrypted Kopia snapshot repository rather than developing another backup engine. Read the [disposable encrypted backup/restore acceptance procedure](docs/backup-recovery.md), including the important requirements to quiesce writes, protect token-bearing snapshots, restore into a new root and test Git refs/clone. **No live encrypted Git backup or restore has been verified.**

## Private backup and recovery integration

GoreeCloud Git plans to integrate with the existing [GoreeCloud Backup](https://github.com/GoreeCloud/backup) alpha and its externally installed encrypted Kopia snapshot repository rather than developing another backup engine. Read the [disposable encrypted backup/restore acceptance procedure](docs/backup-recovery.md), including the important requirements to quiesce writes, protect token-bearing snapshots, restore into a new root and test Git refs/clone. **No live encrypted Git backup or restore has been verified.**

## Test

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
```

Tests use real Git in throwaway temporary folders, do not access private account data, and do not require network access. GitHub Actions runs the same suite on supported Python versions.

## Security and boundaries

Read [SECURITY.md](SECURITY.md) and [docs/architecture.md](docs/architecture.md). Protect SSH private keys, web tokens and private repository backups. Filesystem permissions are a single-owner boundary; this is **not** a multi-tenant authorization system. Only the public application code should be hosted in `GoreeCloud/git`.

## Next milestones

1. Independent security and restore testing; test a real SSH key-based push/clone on an authorized host.
2. A restricted service-account installer, encrypted backups and restore drills, safe per-user permissions, audit logs and rate limiting.
3. Canonical GC UI token/component integration, accessible browser QA and an optional remote administration API with authentication, CSRF protections, scopes, and replay protection.
4. Repository quotas and management, signed releases, contributor workflows, Git LFS and an optional issues/PR layer.

Built as an original source foundation, without third-party application source or fabricated deployment claims. Source and documentation are released under the MIT License; see [LICENSE](LICENSE). This choice applies only to original repository content and does not relicense third-party material.