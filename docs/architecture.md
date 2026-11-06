# GoreeCloud Git — technical architecture (v0.1.0)

## Trust boundaries

- **Public source boundary:** The `GoreeCloud/git` GitHub project stores application source, tests, and documentation only.
- **Private data boundary:** Bare Git repositories are stored outside the source checkout under a strict 0700 owner-controlled data root. Their `.git` object trees are never synchronized to GitHub by this application.
- **CLI admin boundary:** `gcgit` executes directly as the repository filesystem owner. Creation/listing/configuration are local-only. There is no remote admin API.
- **SSH Git boundary:** Git push and clone run through standard OpenSSH/Git. The operating system authenticates SSH keys; `git-shell` restricts the service account where deployed. The application itself does not authenticate Git transport clients or isolate multiple users.
- **Web boundary:** Optional owner-only HTTP Basic login; token in a local 0600 file; requests limited to read-only repository metadata and commit history. Server refuses non-loopback binds, and returns CSP, no-cache, no-sniff, no-frame, and no-referrer headers.

## Threats and mitigations

| Threat | Current mitigation | Remaining risk |
| --- | --- | --- |
| Path traversal via repo name | Strict name regex, no slash, no shell interpolation | Same-host owner process is trusted |
| Symlink escape | Reject symlink repository directories and token symlink | Local owner-level races and compromised host are out of scope |
| Accidental exposure | Default 0700 root, private token 0600, loopback-only web | SSH, network, account and backup configuration are operator-managed |
| Force-push or branch deletion | `receive.denyNonFastForwards` and `receive.denyDeletes` set on creation | Admin can alter Git config; branch ACL not implemented |
| Browser XSS | HTML escaping, no user-supplied JS, restrictive CSP | Full browser/security review outstanding |
| Credential capture | Basic auth only over localhost/SSH tunnel or separately configured TLS | Browser credential caching; no account lockout or server-side session expiry |
| Git command injection | argv subprocess invocation; stripped Git environment; strict repository names | Per-repo Git configuration and untrusted Git object parsing require continued review |
| Data loss | Standard Git bare repository format, recoverable via filesystem backups | No built-in backup, quota, scrub or restore automation |

## Non-goals for first milestone

Not a GitHub clone, publicly deployed service, shared tenancy, OAuth provider, branch-protection policy engine, CI runner, or managed web Git transport. No external service is provisioned automatically. The optional web interface is not a write path.

## Operational acceptance gate

Before hosting actual private assets: review SSH and filesystem account permissions; verify SSH host keys; test clone/push over SSH; verify access denied with unknown SSH keys and wrong web token; perform offline encrypted backup + restore; evaluate resource limits, monitoring, patch levels and incident recovery. Record the results in canonical GoreeCloud documentation only after verification.

## Integrity verification

`gcgit verify REPOSITORY` runs `git fsck --full --no-reflogs` against the owner-selected private bare repository. It does not repair objects, modify refs, or replace encrypted backups. A clean return is a useful local structural check, not a guarantee of disaster recovery; separately validate backups through an isolated restore drill.

## Source licensing boundary

The application source uses the MIT License. Git and OpenSSH are separately installed system tools, rather than bundled upstream source. No license applies by implication to private repository content uploaded by the owner.

## Restricted per-key Git SSH adapter (development preview)

`gcgit serve-ssh --repo NAME` is a small permission-checking Git transport adapter intended for OpenSSH `authorized_keys` forced commands. It reads `SSH_ORIGINAL_COMMAND`, parses the untrusted Git verb and repository argument without shell expansion, and accepts exactly `git-upload-pack` (read) or, only with explicit `--allow-push`, `git-receive-pack` (write). Each key should be restricted to one named repository. It denies path traversal, alternate paths, additional arguments, arbitrary shell commands, and missing original commands. It invokes Git with argv only and sanitizes Git environment overrides.

This adapter authenticates **nothing** itself: SSH host key validation, client public-key authentication, `authorized_keys` restrictions, password-login denial, network controls, user account confinement, and key revocation belong to a reviewed OpenSSH configuration. The adapter does not use a Unix login shell of `git-shell`, since such a shell cannot launch custom Python forced commands. A `git-shell` deployment is an alternative path rather than something to combine with this adapter.

The local integration suite uses a test SSH-command shim to exercise a real Git remote clone/fetch, rejection of receive-pack under read-only scope, and positive push only under explicit write scope. Network OpenSSH end-to-end validation, host compromise protection, resource limits and logged access reviews are outstanding and should not be inferred from the shim.
