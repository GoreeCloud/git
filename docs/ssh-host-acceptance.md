# GoreeCloud Git — OpenSSH acceptance and reversible staging plan

**Status:** Development/staging guidance only. **No service-account, sshd, key, firewall, DNS, or private-data deployment is authorized or performed by this document.** The parser-only smoke is not live SSH acceptance; two separate opt-in namespace-isolated live drills cover selected protocol controls without touching a real host account.

## A. Preflight

1. Choose a **non-root** dedicated Unix account for the private repository root. Record its UID, permissions, shell, home, and the actual private `gcgit --root` path. Confirm storage-root and `repos/` modes `0700`, web token mode `0600`, no external symlink aliases, and no unrelated account sharing its UID.
2. Choose exactly **one** Git SSH transport: standard `git-shell` **or** `gcgit serve-ssh` in an audited `authorized_keys` forced command. The latter **cannot** use `git-shell` as the account login shell, since `git-shell` cannot execute the Python forced command. Give it a normal shell capable of executing the fixed command, while denying unrestricted login by account and key policy.
3. Confirm SSH host-key identity via an independently trusted channel and store a pinned `known_hosts` entry on the testing client. Do **not** disable `StrictHostKeyChecking` or bypass host-key warnings.
4. Review sshd default and `Match User` effective settings for public-key-only access, no password/keyboard-interactive login, no PTY, no agent/X11/TCP forwarding, **no user-controlled interpreter/dynamic linker environment** (including `PYTHONPATH`, `LD_PRELOAD`, `BASH_ENV`), and bounded unauthenticated/established sessions. The app now sanitizes its child Git processes and resolves Git via a fixed system search path, but **cannot protect its own Python interpreter startup from malicious SSH environment propagation**. Confirm `PermitUserEnvironment no`, review all effective `AcceptEnv` directives, and use an audited, pinned forced-command launcher and trusted installation path. Validate with `sshd -t` and `sshd -T -C user=gcgit,host=git.example.invalid,addr=127.0.0.1` on the **reviewed staging host**. Review possible interaction with existing system policies before touching sshd. Do not expose a public administration HTTP endpoint.
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

## D.2. Optional isolated **live** OpenSSH transport drill

Run only on an authorized Linux development laptop with **unprivileged** user/mount/network namespaces, sufficient `/etc/subuid` and `/etc/subgid` ranges, and installed OpenSSH client/server, Git, Python and namespace tools:

```bash
python3 scripts/smoke-sshd-live.py
```

This is explicitly opt-in: ordinary Python CI compiles its source and tests its pure safety preflight, but does **not** run an SSH daemon. The script uses a subordinate-UID/GID namespace and separate network/mount namespaces, verifies that it did not enter the host mount/network namespaces, mounts temporary filesystems over `/run` and `/tmp` **inside the namespace only**, binds this checkout read-only, and starts `sshd` on namespace loopback. It uses only synthetic disposable bare Git repos, commits, generated host/client keys, and a fixed, temporary `authorized_keys` policy. It tears down the server and temporary fixtures after the test; the host's keys, users, sshd settings, listeners, private repositories, and firewall stay unchanged.

The live protocol checks include pinned host-key validation, native clone, unknown-client-key denial, wrong-host-key denial, arbitrary-shell denial, cross-repository denial, rejection of a write attempt using a read-only key without changing the ref, and successful fast-forward push with a separately authorized write key. It verifies a real `git fsck` after the permitted write. Failures must **not** be reported as passing. Exit code `77` indicates missing namespace/tool prerequisites; errors in an otherwise runnable test produce nonzero failure.

**Important limitations:** The disposable test maps namespace UID 0 to a caller-authorized subordinate host UID. It does **not** run with a dedicated non-root host service account. The synthetic `sshd` fixture sets `StrictModes no` **only** because the host's filesystem ancestor `/` appears owned by an unmapped identity inside that namespace; it separately asserts mode `0700` for test storage/key directories and `0600` for the authorized-keys file. This exception is **not acceptable for production**: staging/production must enforce `StrictModes yes`, proper actual account ownership, `PermitRootLogin no`, effective sshd restrictions, key revocation, forwarding denial, monitored quotas, and approved network boundaries. The test does not prove these gates or encrypted backup recovery.

**Verified isolated development evidence (November 6, 2026):** On the authorized Linux laptop, OpenSSH 9.6p1, Python 3.12.3 and Git 2.43.0, this optional network-isolated live transport drill passed its listed positive/negative checks without a host-visible listener or host SSH changes. Do not present this as public service deployment or production SSH acceptance.

## D.3. Optional synthetic **non-root + StrictModes yes** OpenSSH acceptance

For a stronger *disposable* client/server drill, run only on an authorized non-root Linux development machine with assigned subordinate UID/GID ranges (at least 65,535 IDs), user/mount/network/PID namespaces, Git, OpenSSH, Python and standard namespace tools:

```bash
python3 scripts/smoke-sshd-strict.py
```

The script fails closed unless the caller has left the host's mount and network namespaces with authorized subordinate IDs. It mounts an isolated temporary root filesystem, mounts installed system tools **read-only** within that namespace, creates a minimal synthetic user database and ephemeral device bindings, and `chroot`s into that test root. It defines synthetic account `gcgit` (UID/GID 1001 inside the namespace, mapped to an unprivileged subordinate host identity). The synthetic OpenSSH server enforces **`StrictModes yes`, `PermitRootLogin no`, public-key-only login, restricted forwarding, and fixed forced Git commands**. Unlike D.2's simpler namespace fixture, it does **not** weaken `StrictModes`; it checks effective `sshd -T` output and independently validates private home/key/repo ownership.

The opt-in live test covers host-key-pinned Git clone; denial of unknown keys, incorrect host keys, arbitrary shell commands, cross-repository access and pushes from a read-only key; successful explicit write-key push and Git fsck. It additionally confirms that an intentionally group/world-writable synthetic `.ssh` directory causes authentication denial, and removing an authorized test key revokes authentication. The fixture restores its test-only permission/key changes before proceeding. All keys, bare repos, user records, private account home, temporary root, mounts and loopback listener are disposable. The test is **not** started by normal CI; CI only compiles the script and runs pure safety tests.

**Verified local result (November 6, 2026):** The authorized Linux laptop passed the actual synthetic non-root `StrictModes yes` OpenSSH drill with Python 3.12.3, Git 2.43.0 and OpenSSH 9.6p1. No host account was created; the real host's SSH daemon, ports, firewall, users, keys, mounts and private Git storage were not changed.

**Acceptance boundary:** This does **not** prove that a real persistent host non-root user has been provisioned and audited, nor does it establish host firewall/VPN policy, production SSH key lifecycle, disk/cgroup quotas, monitoring, encrypted offsite recovery, or deployment approval. Those gates remain open and must be accepted independently under the reviewed host-specific plan.

## E. Rollback and evidence retention

Before any future approved host changes, preserve reviewed sshd configuration and `authorized_keys` state in a private backup and maintain an independent administration channel. Revert the exact change on failure, revoke test keys, verify sshd syntax and active sessions, confirm firewall/listener state, and keep private repositories untouched. Avoid automated deletions or replacement of repository roots. Record host/version, client version, keys by **public fingerprints only**, test timestamps, exit statuses, objective evidence, and outstanding blockers. Private token/secret contents must never be committed or pasted into public issues.

**Current status:** Local Git-over-SSH simulation, isolated sshd configuration parsing, the original namespace live transport drill (synthetic namespace root with `StrictModes no`), and the stronger **synthetic non-root `StrictModes yes` live drill** have passed on the authorized development laptop. The stronger drill covers real synthetic SSH key revocation and unsafe-mode denial. **Actual host** non-root account provisioning, enforced host ownership and sshd policies, service monitoring, network controls, disk quotas, and encrypted off-host recovery remain open in [v0.2 issue #1](https://github.com/GoreeCloud/git/issues/1).
