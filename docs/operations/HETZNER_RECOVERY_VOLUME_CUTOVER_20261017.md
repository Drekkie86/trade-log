# Christiania recovery volume — migration/cutover runbook (17 October 2026)

**State: code guards prepared; NOT authorized for production configuration
cutover until the seed, complete restore drill, and preflight pass.**
No schema-035 deployment, backup deletion, retention reduction or disablement of
recovery checks is authorized by this document.

## Verified production evidence

- Hetzner Volume `107172834`, EXT4, mounted at
  `/mnt/HC_Volume_107172834`, on a separate block device from the DB.
- Root disk: ~33 GiB available. Volume: ~93 GiB available before seed.
- Original `/var/lib/christiania/backups` contains two ordinary full
  backup points (1 and 8 October; ~26 GiB each) plus a separate v33 release
  rollback (~20 GiB). They are **still protected**.
- Detatched low-priority seed unit: `christiania-volume-seed-20261017.service`.
  State: `/mnt/HC_Volume_107172834/backups/volume_seed_status.json`.
  Only `phase: COMPLETE`, `ExecMainStatus=0`, and independent restore
  evidence may establish readiness. A checksum alone is insufficient.
- Bucket `christiania-evidence-9b615b97f59b` currently contains research
  evidence only; no proved full SQLite database offsite recovery copy.

## Fail-closed config for future volume cutover (DO NOT activate prematurely)

Keep the following three variables in the protected runtime env together:

```text
CHRISTIANIA_RECOVERY_VOLUME_MOUNTPOINT=/mnt/HC_Volume_107172834
CHRISTIANIA_BACKUP_DIR=/mnt/HC_Volume_107172834/backups
CHRISTIANIA_RESTORE_DRILL_SCRATCH_DIR=/mnt/HC_Volume_107172834/scratch
```

The scratch directory must exist, be owned by the Christiania service user
and remain on the mounted volume; it is intentionally never created implicitly.
Backup and release rollback writes fail closed if the configured mount is absent
or the requested path escapes the mounted filesystem. Restore drills fail if the
scratch config is missing, even when Linux has a writable fallback `/tmp`.
The `get_runtime_setting` values are not secrets, but live runtime env files
must not be printed or copied wholesale.

## Activation gates

1. Confirm mounted volume ID, independent filesystem and free space. Create
   `scratch` with restrictive owner/mode, but no broad `chmod -R`.
2. Confirm seed job `COMPLETE`; verify compressed manifest+hash, schema,
   integrity, foreign keys and a full **restore drill from the new volume**.
   Disclose whether recovered dataset is 9 days old rather than current.
3. Confirm verified recovery points on original root remain untouched.
   Test the exact mount-absent failure paths on a disposable test environment.
4. Install service-level mount dependencies (such as `RequiresMountsFor=`)
   for backup/compression/restore and release migration, matching the live
   volume mount path; test timer activation, no concurrent storage operation,
   no root-disk fallback. Roll back env change if any preflight fails.
5. Only after safe backup integrity + rollback headroom: create a **fresh**
   verified backup from live v34 DB, then test restoring it on volume scratch.
6. Offsite encrypted, checksummed SQLite copy with restoration proof is a
   separate P0 requirement. Hetzner Volume alone shares failure risk with VM.
7. For schema-35 release, preserve two ordinary recovery points, ensure enough
   room for another full rollback snapshot *plus* reserved headroom; run exact
   merged-main GitHub release gate, production-scale performance probe, and
   idempotent release preflight before approval. Never use
   `-RecoveryNoSchemaChange` for migration 035.

## No false capacity promise

100 GB raw volume yields ~93 GiB usable before copies; three simultaneous
~27–30 GiB full databases plus reserve may NOT fit. The backup retention and
rollback preflights must compute actual logical DB bytes and reserves. If
insufficient, compress/rotate only independently verified copies, provision
more headroom, or implement verified offsite recovery rather than bypass gates.
