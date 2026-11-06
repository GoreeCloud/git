# GoreeCloud Git — encrypted backup and isolated recovery acceptance

**Status:** Design and acceptance procedure, **not deployed or validated** for actual private Git repository recovery. This document describes an integration target rather than an implemented background job or hosted backup service.

## Reuse the existing GoreeCloud Backup engine

Use the separately maintained [GoreeCloud Backup](https://github.com/GoreeCloud/backup) service and a verified, externally installed **Kopia** encrypted repository. GoreeCloud Git does not implement a second cryptographic backup format, store backup passwords, or invoke remote cloud services. GoreeCloud Backup's alpha supports authenticated loopback Kopia snapshot creation, listing, restore to a **new destination**, and structural/full integrity verification. It is not production-accepted, and any host setup remains a separate authorized change.

References:
- [Backup README](https://github.com/GoreeCloud/backup/blob/main/README.md)
- [Backup integrity verification](https://github.com/GoreeCloud/backup/blob/main/docs/INTEGRITY_VERIFICATION.md)
- [Backup security boundaries](https://github.com/GoreeCloud/backup/blob/main/docs/SECURITY.md)
- [GoreeCloud Git security](../SECURITY.md)

## Source scope and identity

- Source path is the **actual private root** configured for `gcgit --root` (the directory containing `repos/`), not the public source checkout or `GoreeCloud/git` GitHub repository.
- Repositories are standard bare `.git` directories. Preserve Git objects, refs, HEAD, and server-side settings/hook configuration as data; do not restore into an existing live repository.
- The private root must stay `0700` and repository contents must stay owner-private. Do **not** loosen permissions so a separate backup process can read them. A backup job needs explicitly reviewed identity/permissions to read exactly this root; running the backup alpha under the Git service identity increases that identity's attack surface.
- Stop/deny new pushes **for the affected repositories** while capturing a consistent filesystem snapshot, or use a reviewed filesystem-level atomic snapshot. A directory walk concurrent with ref/object updates is not a proven application-consistent Git backup. Do not stop production writes without authorization.
- The root may contain a `.web-token` file. Treat any snapshot as secret-bearing, protect its Kopia keys, and **rotate the restored web token** before enabling the restored web service. SSH `authorized_keys`, sshd policies, server SSH host keys, DNS/firewall settings, and OS service definitions are **outside** this root unless explicitly backed up separately.
- Keep Kopia ciphertext and its repository **outside** the source root and public GitHub, ideally off host with an independently authorized, versioned destination. Safeguard Kopia repository passwords and recovery material separately. Rclone file sync is not an equivalent encrypted historical backup.

## Acceptance drill — disposable data only

1. Prepare a brand-new, isolated Linux test root and test repository, with synthetic commits. Record expected branch names and commit SHA, run `gcgit --root TEST_ROOT verify TEST_REPO`, and verify no sensitive inputs or live host paths are included.
2. Establish a disposable **encrypted Kopia** repository with owner-approved credentials and location. Confirm its encryption/recovery configuration and `kopia repository status`. Do **not** connect to or modify a production repository for a test.
3. After quiescing the disposable Git source, capture the exact `TEST_ROOT` with Kopia directly or the verified GoreeCloud Backup alpha's authenticated `backup` job. Record successful job ID, snapshot identifier, timestamps, source path, expected ref SHA and the backup repository destination. A successful job alone does not establish recoverability.
4. Independently check snapshot integrity. GoreeCloud Backup provides a structural verification job (`kopia snapshot verify --verify-files-percent=0 --file-parallelism=2`) and an opt-in **full file verification** (`--verify-files-percent=100`); the latter requires the explicit phrase `VERIFY ALL BACKUPS` and can incur storage/bandwidth costs. Its implementation uses a fresh private Kopia cache to avoid relying on previously cached objects. A full check is not a substitute for a real restore.
5. Restore the chosen snapshot to a **new nonexistent test destination** using GoreeCloud Backup's `restore` operation (it expects the **Kopia snapshot root directory object ID**, not necessarily the manifest ID, and `confirm: RESTORE`). Confirm the restored directory layout before selecting the restored `gcgit --root` path. Do not replace the original root or modify live service configuration.
6. Under the intended isolated test identity, check `0700` root/repository-directory permissions. Run `gcgit --root RESTORED_ROOT doctor`, `gcgit --root RESTORED_ROOT verify TEST_REPO`, compare `git --git-dir RESTORED_ROOT/repos/TEST_REPO.git show-ref` with pre-backup ref OIDs, confirm `receive.denyDeletes` and `receive.denyNonFastForwards`, and clone into another new test directory. Compare the fixture contents byte for byte.
7. Confirm a **wrong key / missing encrypted repository credentials** cannot recover plaintext, and that restoration refuses a pre-existing destination. Check cleanup of any temporary credentials, caches, and restored fixture after preserving only nonsecret evidence. Do not run destructive corruption drills against any existing backup.
8. Record pass/fail, engine versions, authorized test host, snapshot IDs (where not sensitive), SHA comparisons, duration, and unresolved gaps in approved GoreeCloud project records. Only a fully reviewed real-environment drill can qualify actual deployment/recovery acceptance.

## Operational boundaries

GoreeCloud Git's optional local web runs on TCP `127.0.0.1:8787` by default. GoreeCloud Backup's alpha dashboard also defaults to loopback port 8787; **do not launch both on the same port**. When intentionally co-locating reviewed development instances, choose a distinct loopback port (for example `gcgit serve-web --port 8788`) and keep both behind appropriate authenticated private access.

GoreeCloud Backup's API uses short, bounded jobs and may time out on large encrypted repositories. Interrupted/failed snapshots or restores can leave partial output. Do not automatically retry uncertain operations, declare a restore successful from a green integrity check, or treat passing CI as actual encrypted disaster-recovery acceptance.

**Current evidence boundary:** GoreeCloud Git's unit suite includes a **disposable filesystem snapshot-to-new-root simulation**, which exercises Git integrity, refs, server configuration and native clone. It is not an encrypted Kopia/Backup API integration test, off-host replication test, key escrow audit or production restore drill. Those remain open in [Git readiness issue #1](https://github.com/GoreeCloud/git/issues/1).
