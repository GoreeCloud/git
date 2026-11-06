# GoreeCloud Git — OpenSSH acceptance and reversible staging plan

**Status:** Development/staging guidance only. **No service-account, sshd, key, firewall, DNS, or private-data deployment is authorized or performed by this document.** The synthetic OpenSSH config dry-run is not a real Git-over-SSH acceptance test.

## A. Preflight

1. Choose a **non-root** dedicated Unix account for the private repository root. Record its UID, permissions, shell, home, and the actual private `gcgit --root` path. Confirm storage-root and `repos/` modes `0700`, web token mode `0600`, no external symlink aliases, and no unrelated account sharing its UID.
2. Choose exactly **one** Git SSH transport: standard `git-shell` **or** `gcgit serve-ssh` in an audited `authorized_keys` forced command. The latter **cannot** use `git-shell` as the account login shell, since `git-shell` cannot execute the Python forced command. Give it a normal shell capable of executing the fixed command, while denying unrestricted login by account and key policy.
3. Confirm SSH host-key identity via an independently trusted channel and store a pinned `known_hosts` entry on the testing client. Do **not** disable `StrictHostKeyChecking` or bypass host-key warnings.
4. Review sshd default and `Match User` effective settings for public-key-only access, no password/keyboard-interactive login, no PTY, no agent/X11/TCP forwarding, no user-controlled environment, and bounded unauthenticated/established sessions. Validate with `sshd -t` and `sshd -T -C user=gcgit,host=git.example.invalid,addr=127.0.0.1` on the **reviewed staging host**. Review possible interaction with existing system policies before touching sshd. Do not expose a public administration HTTP endpoint.
5. Keep network access private by default, preferably over the GoreeCloud VPN or a review-approved allowlisted source. Firewall and listening ports must be verified and explicitly authorized before change. Record patch versions, disk/cgroup limits, logging-retention handling, and contingency access.

## B. Per-key forced-command example — edit before use

The following is an **illustrative** `authorized_keys` entry for a **read-only key scoped to one repository**. The operator must replace account, root, CLI path, repository, and key with verified host-specific values.

```text
restrict,command="/opt/goreecloud-git/.venv/bin/gcgit --root /var/lib/goreecloud-git serve-ssh --repo example" ssh-ed25519 <PUBKEY> example-read-only
```

A **separate authorized write key** may append `--allow-push` to the fixed command, after confirming `receive.denyDeletes=true` and `receive.denyNonFastForwards=true`. No private key belongs in this source repository. Every account key must be forced and restricted; one unrestricted key defeats the service-account boundary. Revocation and key rotation are managed in reviewed OpenSSH authorization, not this application.

The CLI limits each Git session to 600 seconds wall time, 300 seconds per-child CPU time, and 2048 MiB virtual memory unless deliberately adjusted within safe CLI bounds. These are **not** aggregate cgroup limits or per-repository disk quotas. Git hooks, pushed history and repository config remain untrusted until reviewed. Treat SSH logs as operationally sensitive.

## C. Real staging acceptance matrix — not yet executed

Run only on an expressly approved **disposable staging host**, using generated synthetic keys, artificial commits and two isolated private bare test repositories. Use exact host-key pinning, and collect redacted exit codes and object IDs:

| Test | Required evidence |
| --- | --- |
| Valid read-only key cloning its permitted repo | `git ls-remote`, `git clone`, expected test commit SHA and contents match |
| Read-only key attempting push | Rejected; no refs or objects modified |
| Explicit write key pushing a fast-forward commit | Accepted only to its assigned repo, then `gcgit verify` passes |
| Assigned key requesting a second repo or arbitrary shell command | Rejected with no unrelated repo disclosure |
| Unknown/revoked key, password attempt, wrong host key | Rejected with no insecure fallback |
| PTY/port forwarding/X11/agent forwarding requests | Denied by effective sshd/account/key restrictions |
| Hanging or resource-heavy Git client | Session deadline enforced; host remains responsive under reviewed limits |
| Authenticated browser and wrong web token | Browser stays loopback; wrong token rejected and no Git mutation path |
| Encrypted backup and isolated new-root restore | Kopia snapshot verified and actual clone, refs, objects, permissions and content match after restore |

If any negative case unexpectedly succeeds, **stop staging and do not open the service to private assets**. Document observed failures, rollback path, host logs with secrets/redaction controls, and owners who approved remediation. Repo source CI or a simulated SSH shim is not equivalent to this matrix.

## D. Safe parser-only preparation

An optional local command checks a synthetic hardening profile's **parsed sshd settings** using installed OpenSSH and Linux unprivileged user, mount, and network namespaces:

```bash
python3 scripts/smoke-sshd-config.py
```

It generates an ephemeral host key in a temporary directory, mounts a disposable `/run` *inside the mount namespace only*, executes `sshd -T` and asserts public-key-only and no-forwarding controls. It **does not start `sshd`**, accept SSH sessions, connect to production, or edit the host's sshd configuration. A test fixture uses `PermitRootLogin prohibit-password` within the isolated namespace to allow root-namespace parsing; **production sshd must use a non-root service account and reviewed root-login policy**. Namespaces may be unavailable on other systems; failure is not a reason to relax host security settings.

## E. Rollback and evidence retention

Before any future approved host changes, preserve reviewed sshd configuration and `authorized_keys` state in a private backup and maintain an independent administration channel. Revert the exact change on failure, revoke test keys, verify sshd syntax and active sessions, confirm firewall/listener state, and keep private repositories untouched. Avoid automated deletions or replacement of repository roots. Record host/version, client version, keys by **public fingerprints only**, test timestamps, exit statuses, objective evidence, and outstanding blockers. Private token/secret contents must never be committed or pasted into public issues.

**Current status:** Only `gcgit`'s local simulated Git-over-SSH transport and the isolated sshd **configuration parser** have been tested. Real OpenSSH client authentication, host-key/cross-repo negatives and the complete recovery drill remain open in [v0.2 issue #1](https://github.com/GoreeCloud/git/issues/1).
