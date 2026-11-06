# GoreeCloud Git — technical architecture (v0.1.0)

## Trust boundaries

- **Public source boundary:** The `GoreeCloud/git` GitHub project stores application source, tests, and documentation only.
- **Private data boundary:** Bare Git repositories are stored outside the source checkout under a strict 0700 owner-controlled data root. Their `.git` object trees are never synchronized to GitHub by this application.
- **CLI admin boundary:** `gcgit` executes directly as the repository filesystem owner. Creation/listing/configuration are local-only. There is no remote admin API.
- **SSH Git boundary:** Git push and clone run through standard OpenSSH/Git. The operating system authenticates SSH keys; `git-shell` restricts the service account where deployed. The application itself does not authenticate Git transport clients or isolate multiple users.
- **Web boundary:** Optional owner-only HTTP Basic login; token in a local 0600 file; requests limited to read-only repository metadata and commit history and a non-secret appearance cookie. GC UI v1 semantic role CSS and a Light-first Appearance setting (Light/Dark/explicit Auto) do not introduce a Git mutation API. Server refuses non-loopback binds, bounds in-flight request threads to eight, applies 10-second socket I/O timeouts, rejects overload with anonymous 503, and returns CSP, no-cache, no-sniff, no-frame, and no-referrer headers. These are single-process limits, not admission rate limiting or Git CPU quotas.

## Threats and mitigations

| Threat | Current mitigation | Remaining risk |
| --- | --- | --- |
| Path traversal / concurrent repo creation | Strict name regex, no shell interpolation; exclusive 0700 directory reservation prevents name-collision overwrites | Same-host owner process is trusted; interrupted creates may leave private reserved directories requiring investigation |
| Symlink escape | Reject symlink repository directories and token symlink | Local owner-level races and compromised host are out of scope |
| Accidental exposure | Default 0700 root, private token 0600, loopback-only web | SSH, network, account and backup configuration are operator-managed |
| Force-push or branch deletion | `receive.denyNonFastForwards` and `receive.denyDeletes` set on creation | Admin can alter Git config; branch ACL not implemented |
| Browser XSS | HTML escaping, no user-supplied JS, restrictive CSP | Full browser/security review outstanding |
| Credential capture | Basic auth only over localhost/SSH tunnel or separately configured TLS | Browser credential caching; no account lockout or server-side session expiry |
| Git command injection / oversized metadata | argv subprocess invocation, stripped Git environment, strict repository names, 1 MiB bounded metadata stdout, timeouts and Git process-group cleanup on failure | Per-repo Git config, untrusted object parsing, filesystem quotas, and aggregate compute budgets require review |
| Data loss | Standard Git bare repository format, recoverable via filesystem backups | No built-in backup, quota, scrub or restore automation |

## Staging OpenSSH verification gate

The [OpenSSH acceptance plan](ssh-host-acceptance.md) specifies a dedicated non-root service-account model, exact `authorized_keys` per-key forced-command scope, host-key verification, wrong/revoked-key and unauthorized cross-repo denial, forwarding restrictions, and staged rollback. The optional synthetic `sshd -T` dry-run uses an isolated Linux namespace and does not start an SSH server. A successful configuration parse is not equivalent to real host-level identity, network, or recovery acceptance.

## Non-goals for first milestone

Not a GitHub clone, publicly deployed service, shared tenancy, OAuth provider, branch-protection policy engine, CI runner, or managed web Git transport. No external service is provisioned automatically. The optional web interface is not a write path.

## Operational acceptance gate

Before hosting actual private assets: review SSH and filesystem account permissions; verify SSH host keys; test clone/push over SSH; verify access denied with unknown SSH keys and wrong web token; perform offline encrypted backup + restore; evaluate resource limits, monitoring, patch levels and incident recovery. Record the results in canonical GoreeCloud documentation only after verification.

## Integrity verification

`gcgit verify REPOSITORY` runs `git fsck --full --no-reflogs` against the owner-selected private bare repository. `gcgit verify-all` runs the same bounded, sequential checks for all discovered complete private repositories, reports both success and failure by repository name, continues after corruption, and returns a nonzero exit code when any repository fails. Empty storage is clearly reported. The sweep does not scan incomplete reserved create directories or prove backup completeness. Neither command repairs objects, modifies refs, schedules background checks, or replaces encrypted backups. A clean return is a local structural check, not a guarantee of disaster recovery; validate through an isolated encrypted restore drill.

## Cross-product encrypted recovery plan

GoreeCloud Backup already has a Kopia-based encrypted snapshot foundation, so GoreeCloud Git will not duplicate its encryption, scheduling or restore engine. See [backup and isolated recovery acceptance](backup-recovery.md) for a disposable-data runbook, quiesced Git write requirement, owner-private source and off-host destination boundaries, and verification of restored Git objects and refs. **No encrypted Git snapshot has been restored or deployed as part of this source development.**

## Source licensing boundary

The application source uses the MIT License. Git and OpenSSH are separately installed system tools, rather than bundled upstream source. No license applies by implication to private repository content uploaded by the owner.

## Restricted per-key Git SSH adapter (development preview)

`gcgit serve-ssh --repo NAME` is a small permission-checking Git transport adapter intended for OpenSSH `authorized_keys` forced commands. It reads `SSH_ORIGINAL_COMMAND`, parses the untrusted Git verb and repository argument without shell expansion, and accepts exactly `git-upload-pack` (read) or, only with explicit `--allow-push`, `git-receive-pack` (write). Each key should be restricted to one named repository. It denies path traversal, alternate paths, additional arguments, arbitrary shell commands, and missing original commands. It invokes Git with argv only, a fixed system-path executable lookup and a minimal child environment (no inherited loader, Python, shell startup, PATH or arbitrary Git settings). The only optionally forwarded client hint is exact `GIT_PROTOCOL=version=2`; before Python starts, the host's sshd must independently block untrusted environment overrides.

This adapter authenticates **nothing** itself: SSH host key validation, client public-key authentication, `authorized_keys` restrictions, password-login denial, network controls, user account confinement, and key revocation belong to a reviewed OpenSSH configuration. The adapter does not use a Unix login shell of `git-shell`, since such a shell cannot launch custom Python forced commands. A `git-shell` deployment is an alternative path rather than something to combine with this adapter.

Git upload/receive-pack is additionally bounded by default per-key forced-command session budgets: 600 seconds elapsed, 300 seconds CPU in the Git process, and 2048 MiB virtual memory per child process. The subprocess is started in a new POSIX process group and killed on timeout, while standard input/output remain streaming for the native Git wire protocol. CPU/memory limits apply individually to descendants rather than providing an aggregate quota; they do not restrict disk usage, concurrent connections, exhausted file descriptors, or privileged same-UID interference. Host cgroups, filesystem quotas, SSH connection limits, packet filtering and operational monitoring remain pending.

The local integration suite uses a test SSH-command shim to exercise a real Git remote clone/fetch, rejection of receive-pack under read-only scope, and positive push only under explicit write scope. Network OpenSSH end-to-end validation, host compromise protection, resource limits and logged access reviews are outstanding and should not be inferred from the shim.
