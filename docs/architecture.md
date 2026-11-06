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
