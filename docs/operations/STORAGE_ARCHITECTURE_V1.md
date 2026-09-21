# Christiania Storage Architecture V1

## Purpose

Christiania's research database grows quickly because raw market evidence is
preserved immutably. Storage management must never trade away evidence
integrity for convenience.

The operating rule is:

> Preserve every meaningful recoverability and evidence guarantee; eliminate
> redundant local copies and fail before storage pressure can corrupt the
> runtime.

## Current storage tiers

### Hot primary

The active SQLite database remains on the production host and is authoritative
for current research operations.

No research evidence is deleted from the hot database by this change.

### Local verified backups

The daily timer is now a **backup-decision check**, not an instruction to
blindly write another full database copy.

A new full verified SQLite recovery point is created when at least one of these
conditions is true:

- no recovery point exists;
- the newest recovery point uses a different schema version;
- completed research exists after the newest recovery point;
- the newest recovery point exceeds the hard maximum age
  (`CHRISTIANIA_BACKUP_MAX_AGE_HOURS`, default 168 hours).

If none apply, the scheduled job exits successfully with `SKIPPED` and does
not copy the database. This prevents weekends or provider outages with no new
completed research from producing redundant 15+ GB copies.

Local backups are fast recovery points for logical/operator failures. They are
not disaster recovery when they share the same underlying device as the
production database.

Before creating a full temporary backup, Christiania must prove that the backup
filesystem has enough free space for:

1. one full source-sized temporary SQLite copy; and
2. the configured production free-space reserve.

Retention pruning still happens only after the new backup has been fully
created, integrity-checked, foreign-key-checked, and atomically promoted.

### Release rollback database copies

Schema-migration rollback copies remain separate from daily backups. Their
retention policy is intentionally unchanged by this change.

### Application releases

Application release directories are reproducible from Git and dependencies and
are not research evidence.

After a deployment has fully activated and rollback traps have been disarmed,
Christiania keeps four successful commit-named release directories in total:

- the active release; and
- the three newest inactive predecessors.

The active release is always protected even if filesystem timestamps are
unexpected. Non-commit directories such as the failed-release quarantine are
ignored.

Release-directory pruning is post-activation housekeeping. A pruning failure is
reported as a warning and does not invalidate an otherwise healthy activation.


## Backup observability

Full backup creation reports explicit phases and coarse copy progress:

- capacity preflight;
- copy start / percentage progress / completion;
- SQLite `integrity_check`;
- `foreign_key_check`;
- atomic promotion;
- retention pruning.

The systemd journal therefore shows which O(database-size) phase is consuming
time instead of appearing hung.

`python christiania_ops.py storage-audit` provides read-only SQLite
`dbstat` attribution so hot/cold design is based on measured table/index
footprint rather than total-file guesses.

## Compressed local backup tier

To reduce full-copy amplification without weakening recoverability, Christiania
stores the newest retained verified backup as an ordinary SQLite `.db` file
for the fastest local restore path and may compress older retained backups with
gzip.

Compression is no longer part of the daily recovery-point job. It is a separate
bounded maintenance operation and processes at most one eligible older backup
per invocation by default. A systemd service/timer definition is shipped with
Reliability V2, but the timer remains intentionally disabled until the separated
path has been validated in production.

Compression is permitted only after the source backup has already passed:

- schema-version verification;
- SQLite integrity verification; and
- foreign-key verification.

Before deleting the uncompressed source, Christiania:

1. computes the SHA-256 of the verified source backup;
2. writes the compressed file to a temporary path;
3. fsyncs the compressed bytes;
4. decompresses the temporary file as a stream and verifies that the payload
   SHA-256 exactly matches the original verified source;
5. records an immutable JSON manifest containing the source and compressed
   hashes, sizes, schema version, integrity state and compression parameters;
6. atomically promotes the compressed file and manifest;
7. re-verifies the promoted compressed file and payload; and only then
8. deletes the uncompressed older copy.

The weekly restore drill supports compressed backups by materializing the
archive into a temporary SQLite database and running the same schema,
integrity, and foreign-key checks as an ordinary backup restore.

Compression is a local capacity optimization only. It does not satisfy the
off-host disaster-recovery requirement.

## Off-host recovery requirement

Same-device local backups do not protect against total server or disk loss.

Christiania therefore still requires an off-host immutable backup tier before
local backup retention should be reduced further. The off-host design must
include:

- verified source backup before upload;
- cryptographic checksum / manifest;
- independent retention;
- restore drill from the remote object, not merely upload success;
- no deletion of the only verified copy;
- explicit failure alerting.

No off-host provider is hard-coded in V1.

## Hot/cold research evidence

No table is archived or deleted from the primary database by this change.

The read-only `storage-audit` operator command identifies high-growth SQLite
objects before a cold-evidence split is designed. Any future archive must
preserve immutable provenance and allow deterministic reconstruction of
research datasets; archival must never silently change historical denominators.

## Capacity interpretation

When the database grows by one byte per day, a three-copy rolling full-backup
set can add roughly three bytes of retained backup footprint over the same
period, in addition to the byte added to the primary database. Capacity
planning therefore considers copy amplification, not only primary database
growth.
