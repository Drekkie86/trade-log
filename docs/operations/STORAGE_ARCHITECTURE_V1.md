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
- completed research accumulated after the newest recovery point reaches the
  materiality threshold (`CHRISTIANIA_BACKUP_MIN_NEW_RESEARCH_ITERATIONS`,
  default 25 — one normal full sampling window);
- at least one completed research iteration is still unprotected and the
  recovery point exceeds the hard maximum age
  (`CHRISTIANIA_BACKUP_MAX_AGE_HOURS`, default 168 hours).

If none apply, the scheduled job exits successfully with `SKIPPED` and does
not copy the database. Small post-backup research deltas are tracked but do not
immediately trigger another 15+ GB copy; weekends or provider outages with no
new completed research never trigger a copy merely because time passed.

The protection boundary is the backup snapshot-start timestamp encoded in the
backup filename, not the file's completion mtime. This conservatively treats a
research iteration that completed while the online copy was running as new
unprotected evidence.

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
time instead of appearing hung. Storage attribution likewise emits periodic
progress while SQLite `dbstat` scans the database.

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

## Off-host recovery requirement — Storage V2B

Same-device local backups and evidence archives do not protect against total
server or disk loss.

Storage V2B uses an S3-compatible remote object store with **Object Lock** as
the off-host immutability boundary. Hetzner Object Storage is the production
target, but the implementation remains S3-compatible.

The remote bucket must have Object Lock enabled at bucket creation time.
Christiania refuses a bucket where Object Lock cannot be proven enabled.

For every uploaded research-evidence archive Christiania:

1. deep-verifies the local archive before upload;
2. uploads the compressed archive with S3 `COMPLIANCE` retention;
3. uploads the exact local manifest with the same retention;
4. requires a version ID for both objects;
5. verifies remote object size and SHA-256 metadata;
6. verifies object retention mode and retain-until timestamp;
7. downloads the archive back from the remote object version;
8. verifies the downloaded compressed SHA-256;
9. decompresses the remote object and verifies the uncompressed SHA-256;
10. downloads the remote manifest and proves byte-for-byte equality;
11. uploads an immutable verification receipt; and
12. writes a separate local remote-proof record only after the whole remote
    restore round trip succeeds.

The remote-proof gate is:

`OFFHOST_IMMUTABLE_RESTORE_VERIFIED`

The original local archive manifest remains immutable and is never rewritten
from `prune_eligible=false`. A later pruning package must require a valid
remote-proof record and revalidate the corresponding immutable remote object
versions before deleting any hot evidence.

Default remote retention is 365 days and is configurable, but Christiania
refuses values below 30 days.

No automatic remote upload timer is enabled by Storage V2B. The first remote
archive is promoted manually and verified before unattended scheduling is
considered.

## Hot/cold research evidence — Storage V2

Production measurement on 21-Sep-2026 showed that primary-database growth is
real evidence allocation rather than freelist waste. The high-volume families
are provider observation availability, provider-model observations, normalized
option quotes, listing-reference contracts, LOCAL_SURFACE_RESIDUAL_V2
observations, and hypothesis-scanner evaluations. A recent normal 15-minute
research run persists roughly 282k rows across those six families, so the hot
database cannot remain an unbounded historical warehouse.

Storage V2 introduces **whole-session cold archives** without deleting hot
evidence.

### Hot retention boundary

The default hot window is the newest 50 completed research runs
(`CHRISTIANIA_EVIDENCE_KEEP_HOT_COMPLETED_RUNS=50`). An older US session is
archive-eligible only when:

- every run in that session is terminal;
- the entire session lies below the hot-run boundary; and
- no verified archive manifest already exists for the session.

A session is never split across the hot/cold boundary.

### Archive coverage V1

Each archive contains the high-volume research evidence closure required to
reconstruct one archived session:

- `research_runs`;
- `research_daemon_iterations`;
- `market_snapshots`;
- `option_quotes`;
- `provider_model_observations`;
- `listing_reference_contracts`;
- `provider_observation_availability`;
- `hypothesis_scanner_runs`;
- `hypothesis_scanner_evaluations`;
- `local_surface_residual_v2_runs`;
- `local_surface_residual_v2_observations`.

The archive is a compact SQLite database without production query indexes.
Index pages are an execution concern for the hot store, not evidence.

### Archive creation contract

Creation is fail-closed:

1. select one whole eligible terminal session;
2. create one read-consistent source snapshot transaction;
3. copy every covered table subset into a temporary archive database;
4. compare source and archive row counts table by table;
5. run SQLite `integrity_check` on the archive;
6. SHA-256 the uncompressed archive;
7. gzip to a temporary payload;
8. stream-decompress and prove the payload SHA-256 matches the uncompressed
   archive;
9. SHA-256 the compressed file;
10. atomically promote the compressed payload and JSON manifest;
11. re-verify the promoted archive; and only then
12. remove the temporary uncompressed archive.

The manifest records format version, coverage contract, source schema, session
date, exact run IDs, per-table row counts, sizes, both hashes and integrity
state.

### Read-through

`archive-find-run` resolves a historical run ID to its session archive without
materializing the payload. `archive-read-run` then materializes that archive
transiently, opens it read-only and proves the archived run's per-table evidence
counts. This is the first read-through contract for future historical research
consumers.

### Pruning remains blocked

Storage V2 deliberately does **not** delete archived rows from the hot database
yet. Every manifest is emitted with:

- `prune_eligible=false`; and
- `prune_block_reason=OFFHOST_IMMUTABLE_COPY_NOT_CONFIRMED`.

A same-disk archive is not enough evidence redundancy to justify destroying
the hot copy. Hot-row pruning is a later gate after an independently verified
off-host immutable copy exists and the full downstream foreign-key closure for
provider/reference evidence is proven.

This avoids turning a storage optimization into silent research-data loss.

## Capacity interpretation

When the database grows by one byte per day, a three-copy rolling full-backup
set can add roughly three bytes of retained backup footprint over the same
period, in addition to the byte added to the primary database. Capacity
planning therefore considers copy amplification, not only primary database
growth.


## Reference-aware hot pruning — Storage V2C

Storage V2C is the first destructive phase and therefore has a stricter gate
than archive creation.

A session may be considered only when:

- its local Storage V2 archive still verifies;
- its separate V2B remote proof exists;
- the proof state is `OFFHOST_IMMUTABLE_RESTORE_VERIFIED`;
- the local manifest bytes still match the manifest hash recorded by the remote
  proof;
- the run IDs still belong to the same terminal session;
- the session remains completely outside the newest 50 completed-run hot
  window;
- the live row counts for every high-volume family still match the archive
  manifest; and
- the active database schema is the reviewed expected schema.

### References decide what can leave the hot store

V2C does not blindly remove every archived row. Rows that remain parents of
later research/governance evidence stay hot.

The first reference-aware families are:

- `local_surface_residual_v2_observations`: preserved when referenced by
  empirical-null membership;
- `hypothesis_scanner_evaluations`: preserved when referenced by shadow
  structure proposals;
- `provider_model_observations`: preserved when referenced by timing
  reconstruction;
- `provider_observation_availability`: preserved when referenced by shadow
  candidates;
- `listing_reference_contracts`: preserved while any surviving shadow,
  scanner, provider-availability or Surface V2 evidence refers to the contract;
- `option_quotes`: preserved while any surviving candidate/control,
  selection/exclusion, Saxo, provider-model, scanner or Surface V2 evidence
  refers to the quote.

The prune planner computes the full delete sets in dependency order before any
destructive action.

### Immutability-trigger handling

Christiania's hot evidence tables deliberately have no-delete triggers. V2C
does not remove those protections permanently.

For an explicitly confirmed prune transaction Christiania:

1. re-verifies the local archive deeply;
2. re-downloads and re-verifies the exact immutable remote archive object
   versions;
3. acquires a SQLite write transaction;
4. captures and hashes the exact reviewed no-delete trigger SQL;
5. temporarily drops only the six allow-listed delete triggers;
6. deletes only the precomputed reference-safe row IDs;
7. recreates the exact captured triggers;
8. proves the restored trigger hashes match the pre-prune hashes;
9. runs SQLite `foreign_key_check`;
10. reconciles before/deleted/preserved row counts; and only then
11. commits and writes a prune receipt.

Any failure before commit rolls back both data changes and transactional DDL.

The session and `research_runs` lineage remain in the hot database. V2C does
not delete research-run identity.

### Physical compaction

Reference-aware deletion increases SQLite freelist space but does not
immediately reduce the file size. Physical compaction is deliberately a
separate follow-up operation after the first production prune receipt has been
reviewed. This keeps logical evidence deletion and O(database-size) file
rewriting as two independently auditable gates.


## Storage & Historical Research Reliability V3

The V3 hardening package extends V2C with schema-wide parent-delete FK/index coverage, bounded atomic delete batches, verified read-only archive analytics, and a mandatory hot/cold analytical parity gate.

Detailed contract: docs/operations/STORAGE_HISTORICAL_RELIABILITY_V3.md

V3 does not automatically prune or compact production storage.
