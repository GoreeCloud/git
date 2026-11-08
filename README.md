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
gcgit create big-data --max-push-mib 4096  # optional per-push pack limit override
gcgit list
gcgit info my-private-repo
gcgit doctor
gcgit verify my-private-repo   # read-only Git object and reference integrity check
gcgit verify-all              # check every complete repository, report each failure
```

Storage defaults to `~/.local/share/goreecloud-git/repos/my-private-repo.git` under the user running `gcgit`. Change it using `gcgit --root /path/to/private/storage ...` or `GC_GIT_ROOT`. Owner-only mode `0700` **and ownership by the current service account** are required for the storage root, `repos/` directory, and every bare repository directory. The existing owner web token must be a regular file, owned by that account, with private `0600` permissions; rotation refuses to replace a foreign-owned or unsafe token path. The CLI does not auto-`chown` or auto-repair unknown existing data. Repository access refuses overexposed directory modes and symlinked Git `HEAD`/`config` control files without attempting to repair existing data. Git subprocesses are resolved only from the platform's fixed trusted system executable path (typically `/bin` and `/usr/bin` on Linux) and run with a minimal environment; a Git binary installed only in a custom or user-writable PATH directory will be rejected. Review the Git installation before changing host provisioning. This tool will **not** silently chmod pre-existing directories. New repository names are reserved with an exclusive, owner-private directory creation to prevent concurrent creators from overwriting a name. If Git initialization fails, the reserved directory is intentionally left private for manual investigation, not auto-deleted or reused.

**Incoming push control:** New repositories set Git's `receive.maxInputSize` to **1024 MiB (1 GiB)** by default instead of Git's unlimited default. This limits the size of **each incoming pack stream**, not cumulative repository storage or filesystem usage. An owner can choose `--max-push-mib` from 1–16384 at creation. An invalid value is rejected before reserving the repository name. Existing repositories are **not migrated or changed automatically**; review their effective Git settings separately. Host disk quotas, filesystem monitoring, SSH connection limits and an off-host encrypted recovery drill are still required before hosting real private assets.

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

**Preflight inspection:** `gcgit doctor` now additionally checks every managed `.git` entry for owner-private directory modes, valid Git control files, symlinks, and interrupted repository creation reservations. It reports failures with a nonzero exit code and **never** deletes, changes modes, or repairs them. This basic access audit does not run Git fsck.

**Maintenance integrity sweep:** `gcgit verify-all` sequentially runs the same read-only Git fsck check on each discovered complete private bare repository. It continues after corrupt repositories and exits nonzero if any check fails. An empty store is reported explicitly. Incomplete reserved creation directories are deliberately not included, and an integrity sweep does not prove that off-site encrypted backups are restorable. Run manually during a reviewed maintenance window for large repositories; no scheduler or network service is installed.

**Optional encrypted recovery verification:** With an externally reviewed Kopia installation and a disposable network-isolated test environment, run `KOPIA_BIN=/path/to/kopia python3 scripts/smoke-kopia-git-recovery.py` to exercise an original Git fixture through encrypted **local** Kopia snapshot, fresh-cache full verification and restore to a new directory. This does not configure backups for real private data or prove off-host recovery. The additional opt-in `scripts/smoke-backup-api-git-recovery.py` tests the authenticated GoreeCloud Backup API with encrypted Kopia and a disposable Git restore. It requires reviewed `KOPIA_BIN` and `GOREECLOUD_BACKUP_BIN` executables inside an operator-provided offline sandbox. See [backup and recovery acceptance](docs/backup-recovery.md).

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

## Optional isolated OpenSSH acceptance drill

On an authorized Linux development machine with unprivileged user, mount and network namespaces, installed OpenSSH client/server and configured subordinate UID/GID ranges, you can exercise **real** host-key-pinned Git-over-SSH authentication against a **disposable SSH daemon**:

```bash
python3 scripts/smoke-sshd-live.py
```

The original `scripts/smoke-sshd-live.py` uses disposable client/server SSH keys and repositories, namespace-only loopback networking, and tests positive Git read/write and negative key/shell authorization. **Only that original synthetic-root fixture** uses `StrictModes no` inside its private namespace because its temporary root ownership is not a normal host account. The **separate stronger opt-in drill**, `python3 scripts/smoke-sshd-strict.py`, runs an actual synthetic **non-root** `gcgit` service account with effective `StrictModes yes`, testing unsafe-key-directory and revoked-key denial plus native Git operations. Both are opt-in, do not install or expose host services, and are **not run by normal CI**. Neither proves production host-account acceptance. See [OpenSSH acceptance limits](docs/ssh-host-acceptance.md).

## Per-key restricted SSH transport (development preview)

GoreeCloud Git also has an optional `gcgit serve-ssh` forced-command handler. This allows **one explicitly named repository per SSH key**. Its default is **clone/fetch only**; `--allow-push` is required to enable Git receive-pack. It validates Git's `SSH_ORIGINAL_COMMAND` and directly invokes the required Git subcommand without a shell. It does **not** install or configure an SSH daemon, create keys, authenticate users, or implement a multi-user ACL.

On a security-reviewed Linux host, use a dedicated non-root service account and an OpenSSH `authorized_keys` entry of this form (replace every example path and key with verified values):

```text
restrict,command="/opt/goreecloud-git/.venv/bin/gcgit --root /var/lib/goreecloud-git serve-ssh --repo my-private-repo" ssh-ed25519 <KEY_MATERIAL> owner-read-only
```

Each forced-command session now has bounded defaults: **600 seconds wall time**, **300 seconds child CPU time**, and **2048 MiB child virtual address space**. Review and optionally set `--wall-seconds`, `--cpu-seconds`, and `--memory-mib` in the operator-controlled forced command. A timeout terminates the Git subprocess group and fails the request; these per-process limits are not disk quotas, concurrency limits, complete descendant containment, or a replacement for host cgroups/ulimits and server-side quotas. Test your expected repository sizes before changing defaults.

For a key explicitly authorized to **push to the same single repository**, add `--allow-push` to the forced command. Keep other keys restricted or revoked. Do not place a privileged/unrestricted SSH key alongside restricted keys for the service account. The Unix account must own the private storage and must be unable to read unrelated files.

**Choose one SSH confinement architecture:** the previous `git-shell` approach directly permits Git's standard upload/receive-pack verbs and is administered outside this program. The `gcgit serve-ssh` approach requires an SSH account login shell capable of starting the Python entrypoint (not `git-shell`); compensate with an audited `authorized_keys` forced command plus OpenSSH key restrictions, disabled password logins, and a restrictive `Match User` policy. Never claim that `git-shell` can execute this custom forced command. `restrict` blocks interactive PTY and common forwarding features for that key; validate host-wide SSH policy too.

A native Git remote URL from `gcgit remote ...` is compatible with this mode when its path matches the private bare repository exactly. In testing, a local SSH-command shim exercised clone/fetch and push permissions without starting a network SSH daemon. **Synthetic isolated tests cover real host-key pinning, unknown/revoked keys and a non-root service identity, but actual persistent host key management, account isolation, rate/resource enforcement and deployment remain pending.** See [SECURITY.md](SECURITY.md) and [docs/architecture.md](docs/architecture.md).

### SSH staging and acceptance

Before configuring a real SSH daemon or hosting private projects, follow the [reversible OpenSSH staging and security acceptance plan](docs/ssh-host-acceptance.md). It includes host-key pinning, restricted keys, denied-access tests, safeguards, and both parser-only and **two opt-in synthetic live OpenSSH** acceptance drills. The drills do **not** establish actual persistent-host SSH authorization or deployment.

## Optional browser (read-only)

```bash
gcgit web-token             # outputs a new owner password once; keep it private
gcgit serve-web             # listens only on 127.0.0.1:8787
# Open http://127.0.0.1:8787 from that host.
# Username: owner   Password: the generated web token
```

The browser lists repositories, branch counts, commit totals, and recent history; it has no upload, push, create, delete, or admin API. The development server now allows at most **8 concurrent HTTP request workers**, rejects additional connections with anonymous HTTP 503 responses, and applies a **10-second per-socket timeout** to reduce slow/incomplete-request resource exhaustion. It is not a complete HTTP rate limiter or CPU/disk quota. It uses HTTP Basic authentication and no JavaScript. **Never expose its HTTP port directly on a public interface.** For remote private access, use an SSH tunnel or a properly protected TLS reverse proxy. Example from a trusted client using an authorized SSH administration account:

```bash
ssh -N -L 8787:127.0.0.1:8787 admin@git.example.net
# Then open http://127.0.0.1:8787 locally.
```

Rotating the web token requires restarting the browser service. The browser now consumes verified **GoreeCloud UI v1 semantic color and layout roles**, defaults to **Light** even on a dark-preferring OS, and offers authenticated **Appearance** settings for persistent Light, Dark, or explicitly selected Follow system. The non-secret choice is saved only as a SameSite=Strict/HttpOnly cookie; it never stores Git data, credentials, or private repo history. The browser remains a **development UI**. An **opt-in real Chromium smoke** now checks authenticated read-only navigation, appearance persistence, keyboard skip link, 375/768/1440px viewport reflow and screenshot evidence in a disposable offline sandbox; the full screen-reader, cross-browser, device and WCAG acceptance gates remain open. See [GC UI consumer alignment and reproducible browser test](docs/gc-ui-consumer.md).

## Licensing

The original GoreeCloud Git source and documentation in this repository are licensed under the [MIT License](LICENSE) (SPDX: `MIT`). The implementation uses Python standard-library modules and invokes an externally installed Git executable; neither Git itself nor OpenSSH are copied into this repository or relicensed. This permissive license covers the application code, **not** the private repositories or their contents that you host with it.

## Private backup and recovery integration

GoreeCloud Git plans to integrate with the existing [GoreeCloud Backup](https://github.com/GoreeCloud/backup) alpha and its externally installed encrypted Kopia snapshot repository rather than developing another backup engine. Read the [disposable encrypted backup/restore acceptance procedure](docs/backup-recovery.md), including the important requirements to quiesce writes, protect token-bearing snapshots, restore into a new root and test Git refs/clone. **Synthetic live encrypted local** Kopia and authenticated GoreeCloud Backup API snapshot/restore drills have passed, including restoration from a **separate same-host copy** of encrypted storage when original test paths are unavailable. **No physical off-host production backup, key escrow or recovery of actual private Git repositories** has been verified.

## Test

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
```

Tests use real Git in throwaway temporary folders, do not access private account data, and do not require network access. Administrative Git metadata commands have a **1 MiB captured-output ceiling** and an elapsed-time deadline (usually 12 seconds; 60 seconds for `gcgit verify`); the affected subprocess group is terminated on timeout or oversized output. The native SSH Git wire protocol streams separately and is not buffered into this limit. GitHub Actions runs the same suite on supported Python versions.

## Security and boundaries

Read [SECURITY.md](SECURITY.md) and [docs/architecture.md](docs/architecture.md). Protect SSH private keys, web tokens and private repository backups. Filesystem permissions are a single-owner boundary; this is **not** a multi-tenant authorization system. Only the public application code should be hosted in `GoreeCloud/git`.

## Next milestones

1. Complete **actual persistent non-root host** SSH authorization/network acceptance and physically off-host encrypted restore with independently recoverable keys; isolated synthetic live SSH and local Backup API recovery drills already pass.
2. A restricted service-account installer, encrypted backups and restore drills, safe per-user permissions, audit logs and rate limiting.
3. Broaden the existing canonical GC UI consumer and verified Chromium browser acceptance to Firefox, screen readers, real devices, zoom/forced colors and an approved private access path before any optional scoped remote administration API.
4. Repository quotas and management, signed releases, contributor workflows, Git LFS and an optional issues/PR layer.

Built as an original source foundation, without third-party application source or fabricated deployment claims. Source and documentation are released under the MIT License; see [LICENSE](LICENSE). This choice applies only to original repository content and does not relicense third-party material.