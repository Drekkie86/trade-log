# System backup status and deployment identity correction — 2026-10-25

## Incident

On production after schema-v37 recovery and the Saxo read-only deployment,
the Christiania **System** page incorrectly displayed:

- **Backups ✗ — No valid backup found**
- **Christiania 1.0.0-rc1** in the sidebar

The nightly independent-volume writer restored and validated
`christiania_backup_20261025T003233Z.db.gz` (schema v37,
39,727,546,368 uncompressed bytes), and the separate volume
restoration audit at 2026-10-25T03:43Z reported PASSED.
The RC0 supervisor correctly reported `backup-recovery-point: PASS`,
`supervisor_state=HEALTHY` and `ready=true`.

### Root cause of false alarm

The fast backup inventory `inventory_backups_fast()` deliberately marks
EVERY file `NOT_REVERIFIED` to avoid multi-gigabyte gzip decompression
and O(database size) integrity checks on every dashboard load.
`system_checks()` interpreted that deliberately absent
`latest_valid_age_hours` as proof that no backup exists, and used a
red failure badge. These represent different evidence populations.

### Fixed health decision

The new bounded `backup_system_status_v1.py` reads:

1. the Christiania service-owned supervisor status JSON, rejecting a
   missing, future, stale or failed `backup-recovery-point` check;
2. the latest backed-up archive using the **same v3 manifest validator**
   as the production recovery policy. Checks real gzip archive size,
   source/destination SHA-256 *format*, schema, completed restore trial,
   timestamp and archive identity without decompressing anything;
3. if the independent full-restore audit references that same archive,
   its state, schema, verification level and restored size must qualify.
   A PASSED audit is reported separately; an audit for an older archive
   is **not** misrepresented as proof of the newest nightly backup.

The primary System page now draws its backup row from this **verified
recovery evidence**, not from the metadata-only inventory. Unavailable
or stale evidence is **UNKNOWN**, not proof of a failed backup.
Genuine latest-archive audit or supervisor failures remain red.

Interactive read path: bounded JSON + metadata, no SQLite integrity
scan, large archive verification, dynamic historical query or provider
call. Read is cached 90 seconds; Refresh deck clears the cache.

### Useful release identity

The static product label `Christiania 1.0.0-rc1` no longer occupies the
sidebar footer. Instead it shows the actual deployed commit from the
service-readable immutable `DEPLOYED_COMMIT` release marker, linked
to its exact GitHub commit, and the current database schema.
If the deployed marker is missing/unreadable, it says identity
unavailable; it does not fall back to the static product version.
The existing Ops technical fingerprint retains the formal product
release label for historical reference.

### Verification / release constraints

- Live read-only canary of the new module under the `christiania`
  service user reported `VERIFIED`, schema v37, age 14.6 hours and
  **Independent full-restore audit PASSED**.
- Tests cover stale, corrupt, missing, failed, mismatched-schema and
  metadata-only backup states, plus frontend screenshot regression.
- Local full suite: 1,722 passed, 10 skipped, 38 subtests passed.
- No schema migration, token-store change or broker/order authority.
- Release via exact-main GitHub gate and production-scale performance
  probe, guarded server-owned no-schema-change deploy, rollback on failure.
