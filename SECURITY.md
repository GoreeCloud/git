# Security policy and operating boundaries

This is an early-development, single-owner self-hosted service. **Do not deploy it as a public, multi-user Git forge** without an independent threat review.

- Source repository `GoreeCloud/git` is public. Never commit private Git objects, token files, SSH keys, backups, user data, `.env` files, or server configurations with secrets.
- Private repositories live only in a separate filesystem data root with owner-only `0700` directory permissions. The public source tree is never the repository storage root.
- Git transport is standard Git-over-SSH. Use SSH public-key authentication and a dedicated non-root operating-system account. Select either a reviewed `git-shell` installation **or** a `gcgit serve-ssh` per-key forced-command installation; these approaches have different login-shell requirements. Manage key revocation through `authorized_keys`/your SSH infrastructure.
- This application does not implement a remote identity service, an ACL/organization model, Git LFS, branch policies per user, CI runners, hooks isolation, or an HTTP Git transport. Do not infer those features.
- The optional browser is read-only and requires owner Basic authentication using a locally stored high-entropy token. It only binds to loopback; use an SSH tunnel or a separately configured TLS reverse proxy with proper access controls for remote viewing. Browser Basic auth may cache credentials.
- The web token is readable by the server operating-system account and must be protected from backups, accidental copying, and logging. Rotating it requires restarting the web service. Use short-lived SSH forwarding rather than exposing an HTTP port to the Internet.
- Git hooks and pushed content should be treated as untrusted. Never automatically execute hooks from untrusted repositories in privileged contexts. Use a non-root service account.
- Maintain off-site encrypted backups of the private repository storage and periodically test restores. No backup automation is provided in this version.
- Do not expose port 8787 publicly, weaken filesystem modes, or share a dedicated SSH account among untrusted users.

Report vulnerabilities privately to the repository owner. Do not publish exploitation details or credentials in a public issue.
## Optional forced-command SSH restrictions (development)

- `gcgit --root PRIVATE_DIR serve-ssh --repo NAME` accepts only Git upload-pack for that named repository by default. `--allow-push` additionally enables receive-pack for that **one** repository. Unsupported verbs, extra arguments, malformed paths, cross-repo accesses, and missing `SSH_ORIGINAL_COMMAND` fail closed.
- Invoke it **only** as a trusted OpenSSH `authorized_keys` forced command with `restrict` on the corresponding key. It is not an authentication server; local processes with the service account's privileges can still access its repositories.
- OpenSSH runs a forced command via the user's configured login shell. A login shell of `git-shell` will **not** launch a custom Python forced command; use a separately reviewed shell + SSH configuration if selecting this mode. Do not allow unrestricted keys, password-based logins, PTY, port forwarding, X11 forwarding, or arbitrary shell sessions for this service account.
- Enforce per-key authorization and key rotation outside this application. A write-enabled key can push any allowed fast-forward ref to the named repository; this is not a branch-level ACL, and pushed objects must remain untrusted data.
- Tests use a local simulated SSH transport; they do not establish server-level protection, identity verification, DOS resistance, host firewall rules, or production readiness.
