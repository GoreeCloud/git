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
6. Under the intended isolated test identity, check `0700` root, `repos/`, and each restored bare repository directory; Git also refuses symlinked `HEAD` and `config` control files. Never automatically repair a restore with incorrect permissions before investigating it. Run `gcgit --root RESTORED_ROOT doctor`, `gcgit --root RESTORED_ROOT verify TEST_REPO`, compare `git --git-dir RESTORED_ROOT/repos/TEST_REPO.git show-ref` with pre-backup ref OIDs, confirm `receive.denyDeletes` and `receive.denyNonFastForwards`, and clone into another new test directory. Compare the fixture contents byte for byte.
7. Confirm a **wrong key / missing encrypted repository credentials** cannot recover plaintext, and that restoration refuses a pre-existing destination. Check cleanup of any temporary credentials, caches, and restored fixture after preserving only nonsecret evidence. Do not run destructive corruption drills against any existing backup.
8. Record pass/fail, engine versions, authorized test host, snapshot IDs (where not sensitive), SHA comparisons, duration, and unresolved gaps in approved GoreeCloud project records. Only a fully reviewed real-environment drill can qualify actual deployment/recovery acceptance.

## Optional local encrypted Kopia/Git recovery drill

`scripts/smoke-kopia-git-recovery.py` is an **opt-in, disposable, local-only** acceptance test. It does **not** automatically install Kopia, schedule a backup, access a real private repository, select an external storage provider, or modify GoreeCloud Backup's actual repository or credentials. **The script does not itself enforce network isolation**; run it in an offline sandbox to ensure an installed Kopia binary cannot contact the network, including update checks.

With an independently reviewed, externally installed Kopia executable and an authorized **network-isolated development sandbox**, run:

```bash
KOPIA_BIN=/path/to/reviewed/kopia python3 scripts/smoke-kopia-git-recovery.py
```

The script creates a private bare Git fixture, pushes an original test commit, records its ref and receive-protection settings, and generates a disposable web token. It creates a **new encrypted Kopia filesystem repository separate from that source root** with a random password held only in a child-process environment, then snapshots the quiesced source. It connects separately with a **fresh verification cache** and runs structural and **100% file verification**, rejects incorrect credentials and an already existing restore destination, and restores the snapshot root object to another new private directory. It checks the restored Git ref, object integrity, receive settings, native clone contents, and restored token rotation. A supplemental plaintext-marker check is a smoke test, **not** cryptographic proof.

**Verified isolated development evidence (November 6, 2026):** An independently retrieved official Kopia **v0.23.1** Linux x64 release asset had SHA-256 `416d0f84a3dbb321a8b2d8f0997b1a0a6e915babe79ee76fa6e4d2bd1e1c5178`, matching the digest exposed by its official GitHub release metadata. The pinned external CLI was executed read-only inside an **offline Bubblewrap sandbox** with private temporary storage; the complete synthetic encrypted Git snapshot, fresh-cache verification, wrong-password and existing-destination negatives, restore, token rotation, refs and Git clone drill **passed**. No Kopia release files or backup credentials were committed to this repository.

**Still not verified:** Actual **off-host** encrypted replication, approved durable Kopia key recovery, live GoreeCloud Backup alpha API orchestration, real private Git repository restore, realistic performance/RPO/RTO, retained lifecycle data, production backup scheduling, and owner acceptance. The separate [GoreeCloud Backup](https://github.com/GoreeCloud/backup) engine remains the authority for future integrated encrypted backup/restore operations.

## Optional authenticated GoreeCloud Backup API Git restore drill

The separately maintained [GoreeCloud Backup](https://github.com/GoreeCloud/backup) alpha exposes a bearer-authenticated loopback job API that delegates to the independently installed Kopia CLI. `scripts/smoke-backup-api-git-recovery.py` now tests **both actual systems together** with a disposable owner-private bare Git fixture:

```bash
KOPIA_BIN=/absolute/path/to/reviewed/kopia \
GOREECLOUD_BACKUP_BIN=/absolute/path/to/reviewed/goreecloud-backup \
python3 scripts/smoke-backup-api-git-recovery.py
```

**Run this only inside a network-isolated disposable sandbox.** The script itself does not create a network namespace or download/install either executable. It requires absolute paths to executable files and refuses to run without both. The operator must independently inspect and build the Backup service from its current authorized source, verify the external Kopia binary's official release checksum, and ensure no host service or configured cloud repository can be reached. Neither the Backup API server nor Kopia is started by normal Python CI.

The test generates fresh, synthetic Git commits, a private `gcgit` root, a synthetic web token, an ephemeral **encrypted** filesystem Kopia repository and randomly generated independent API/Kopia credentials. It launches GoreeCloud Backup bound to **loopback inside the sandbox** and authenticates each job through the real API. It checks denied unauthenticated requests and missing restore/full-verification confirmation, creates a Git snapshot while fixture writes are quiesced, waits for the Backup job to finish, and runs both **fresh-cache structural and 100% Kopia file verification** through the API. It obtains the snapshot root object ID through the snapshots job, verifies that an occupied destination is rejected without alteration, and restores to a new private root. First it compares the restored Git branch OID, receive-protection settings, Git fsck and native clone content, verifies restored web token bytes and rotates the token before restored use. **Then it tests recovery from an independent local copy of the encrypted Kopia repository:** compare every repository file digest; stop the first API; make the original synthetic data, encrypted repository and Kopia configuration paths unavailable; reject a wrong repository password; connect to the copy with a new Kopia configuration and fresh cache; start a second Backup API with a different bearer token and reject the old token; run structural and full verification, restore into a second fresh private root, and recheck Git refs/config/fsck/clone plus restored token rotation.

**Verified isolated development evidence (November 6, 2026):** The authorized Linux laptop built the separate GoreeCloud Backup service from source commit `944fec373acfbf72112b0dc3f5d5f0a75dbf8e4c` using Go 1.27.3 with network module downloads disabled (the repository has no external Go dependencies). Kopia v0.23.1 Linux x64 SHA-256 was independently checked against the official release metadata (`416d0f84a3dbb321a8b2d8f0997b1a0a6e915babe79ee76fa6e4d2bd1e1c5178`). The **actual authenticated Backup API → encrypted Kopia → isolated GoreeCloud Git restore** passed under Bubblewrap `--unshare-net` with both source checkouts and binaries mounted read-only and all test data in private temporary storage. The service was stopped after the test; no real private repositories, host listeners, production Backup repository, cloud services, credentials or host configuration were modified.

**Newly verified local copy-recovery evidence (November 7, 2026):** The expanded Git/Backup API acceptance exercised that independent encrypted repository copy and second fresh API/Kopia restore successfully in an offline Bubblewrap sandbox against the latest inspected Backup main commit `d79b13f0f0494bad61b6be23cb0307acb5c37e67`. The official Kopia v0.23.1 Linux asset checksum remained verified. The original paths were renamed only **within the disposable test** and no existing repository, host account or production configuration was changed.

**Still unverified:** A physically/off-host encrypted destination and restore, password escrow/recovery under an independently authorized account, durable scheduled snapshot delivery, operator key revocation on a real host, real production source data, overall RPO/RTO, workload scalability, and founder-approved deployment. This drill does **not** license or install GoreeCloud Backup as a production service, and does not complete the disaster-recovery acceptance gate.

## Operational boundaries

GoreeCloud Git's optional local web runs on TCP `127.0.0.1:8787` by default. GoreeCloud Backup's alpha dashboard also defaults to loopback port 8787; **do not launch both on the same port**. When intentionally co-locating reviewed development instances, choose a distinct loopback port (for example `gcgit serve-web --port 8788`) and keep both behind appropriate authenticated private access.

GoreeCloud Backup's API uses short, bounded jobs and may time out on large encrypted repositories. Interrupted/failed snapshots or restores can leave partial output. Do not automatically retry uncertain operations, declare a restore successful from a green integrity check, or treat passing CI as actual encrypted disaster-recovery acceptance.

**Current evidence boundary:** Unit tests exercise disposable filesystem-copy recovery; opt-in live drills exercise encrypted local Kopia CLI restore, the actual authenticated GoreeCloud Backup API, and a **copied encrypted repository with the original paths unavailable**. These establish local encrypted Git recovery behavior only; they do not prove physical/off-host replication, recoverable credentials outside the testing process, disaster recovery of real private data, durable scheduling, or production readiness. Those gates remain open in [Git readiness issue #1](https://github.com/GoreeCloud/git/issues/1).
