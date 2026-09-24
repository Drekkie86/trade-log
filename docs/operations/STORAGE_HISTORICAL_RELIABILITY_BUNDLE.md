# Christiania Storage & Historical Research Reliability Bundle

## Purpose

This bundle turns Storage V2C from a manually orchestrated destructive
maintenance path into a guarded hot/cold research lifecycle.

It does **not** automatically prune any production session and it does **not**
physically compact the SQLite database. Deployment installs the safeguards and
historical-analysis capabilities. A later operator decision is still required
before destructive pruning.

The package is intentionally one coherent release because the safety properties
depend on the pieces being present together:

1. canonical maintenance ownership and zero-database-holder proof;
2. schema v34 parent-delete indexes;
3. historical cold-store analysis and hot/cold parity;
4. reference-aware chunked deletes inside one SQLite transaction;
5. a transactional in-database prune commit ledger;
6. recoverable external prune receipts;
7. CI and operator gates that exercise the complete contract.

## Non-negotiable invariants

- Research archives remain immutable Storage V2 format-v1 evidence.
- Old archives are never rewritten to look like a newer production schema.
- Hot pruning may remove only rows already proven reference-safe by V2C.
- The newest configured hot research window remains untouched.
- Local archive verification and off-host immutable restore proof remain
  mandatory immediately before destructive work.
- Historical Analysis V1 must produce identical canonical results from the hot
  source and the archived source before pruning is eligible.
- Every foreign key into a V2C parent table must have a leading child-side
  support index.
- The destructive delete phase remains one atomic SQLite transaction even
  though rows are deleted in bounded batches.
- The database commit and immutable prune evidence are one durability event.
- A missing external receipt can be recreated from the committed database
  ledger; a committed session can never be pruned twice.
- Production prune execution requires the canonical Christiania maintenance
  state.
- Theta remains active during maintenance; database consumers and the public
  OAuth edge are quiesced.
- Maintenance entry proves no process still holds the DB/WAL/SHM files.
- No VACUUM or physical compaction is part of this package.

## Schema v34

Migration 034 adds four child-side indexes proven missing by the complete
migration-history audit:

- `shadow_candidates(reference_contract_id)`
- `hypothesis_scanner_evaluations(reference_contract_id)`
- `hypothesis_scanner_evaluations(option_quote_id)`
- `local_surface_residual_v2_observations(reference_contract_id)`

SQLite checks child references while deleting a parent. Without these indexes,
a large parent delete can repeatedly scan child tables and degrade toward
quadratic behavior. The Sep-16 maintenance incident exposed this on
`listing_reference_contracts`.

V2C no longer trusts migration history alone. Every prune plan mechanically
enumerates live foreign keys into:

- `listing_reference_contracts`
- `option_quotes`

and requires a non-partial index whose leading columns cover each child FK.
Any missing support produces a blocking
`MISSING_PRUNE_PARENT_FK_INDEX` result.

## Historical Analysis V1

The archive remains the immutable raw-evidence tier. The active database
continues to hold low-volume governance, candidate, strategy and outcome
evidence that V2C intentionally preserves when referenced.

Historical Analysis V1 defines deterministic analytical surfaces over the
archive coverage:

1. run inventory;
2. quote-universe quality and field coverage;
3. provider-model coverage;
4. provider-observation availability;
5. hypothesis-scanner outcomes;
6. Surface V2 residual behavior.

Each metric has deterministic ordering and a canonical SHA-256. A session-level
canonical hash combines the metric hashes, session date, exact run IDs and
analysis version.

The canonical research hash deliberately excludes storage-tier identity and
schema version. A v33 archive and a v34 hot database may therefore compare
equal when their research meaning is identical. Both schema versions remain
recorded as provenance.

### Hybrid historical reader

`open_historical_session` exposes one verified historical session with:

- archived raw evidence as the read-only main SQLite schema;
- the current Christiania database attached read-only as schema `hot`;
- connection-wide `PRAGMA query_only=ON` before the caller receives it.

This is the research surface for future replay, counterfactual evaluation and
performance attribution. It avoids restoring an old full production database
and preserves the distinction between immutable cold observations and current
governance/outcome evidence.

## Hot/cold analytical parity gate

Every V2C plan now runs Historical Analysis V1 on both sources using the exact
archive run IDs.

The plan is blocked when:

- a historical query cannot execute against either source; or
- any metric hash differs; or
- the combined canonical session hash differs.

The successful hot and archive hashes are carried into the prune plan and
receipt.

This gate is intentionally stronger than row-count reconciliation. Count
matching remains required, but it is no longer treated as proof that archived
evidence is analytically interchangeable with the hot copy.

## Bounded atomic delete execution

The reference-aware planner still computes the full delete sets before any row
is removed.

Apply execution now consumes those immutable temp delete sets in bounded
primary-key batches. The default batch size is 25,000 rows.

Each batch:

- remains inside the one outer `BEGIN IMMEDIATE` transaction;
- uses the SQLite progress handler, so an unexpectedly slow individual batch
  still emits heartbeat output;
- reports batch row count and cumulative `deleted/expected` progress;
- fails if a batch makes no progress;
- reconciles exact totals before commit.

Batching improves observability and bounds individual SQL statements. It does
not permit partial success: an error or interruption before COMMIT can still
roll the complete transaction back.



### Atomic-prune WAL and capacity preflight

Batching bounds individual DELETE statements but deliberately does not split
the transaction. The whole session remains one atomic commit, so Christiania
must assume the transaction WAL can grow materially.

Immediately before the production write transaction Christiania:

1. requires SQLite WAL mode;
2. runs `wal_checkpoint(TRUNCATE)` and requires a non-busy, zero-byte WAL;
3. calculates logical database bytes from the larger of the main file and
   `page_count * page_size`;
4. measures filesystem free space;
5. reserves one logical-database-sized WAL allowance plus the same RC0
   free-space reserve used by verified backup policy; and
6. refuses the prune before `BEGIN IMMEDIATE` when that headroom is absent.

The resulting logical size, free bytes and required bytes are persisted in the
prune receipt for later audit.

## Transactional prune commit ledger

Schema v34 adds `research_archive_prune_commits_v1`.

The table is low-volume immutable evidence. UPDATE and DELETE are blocked by
triggers.

Immediately before SQLite COMMIT, Christiania constructs the complete prune
receipt and inserts its canonical JSON plus SHA-256 into the ledger inside the
same transaction as the row deletions.

Therefore:

- if the transaction rolls back, neither the prune nor its ledger survives;
- if the transaction commits, both the prune and its durable evidence survive.

The external `.prune-receipt.json` is written after COMMIT for operator and
archive-directory visibility. It is no longer the sole proof of commit.

If the process fails after COMMIT but before the external receipt is written,
the next invocation:

1. detects the committed ledger first;
2. verifies the ledger receipt SHA-256 and canonical JSON;
3. recreates a missing external receipt atomically;
4. refuses to execute the prune again.

If an existing external receipt disagrees with the database ledger, the
operation fails closed.

## Canonical production maintenance

Destructive production pruning is no longer allowed merely because the caller
passed a confirmation string.

When the default production DB path is used, `archive-prune-session` requires:

- `/run/christiania/maintenance.state` to exist;
- app, daemon and OAuth proxy to be inactive;
- Theta to remain active.

The canonical maintenance entry additionally:

- stops the configured timers;
- refuses to enter while a backup, audit, restore drill or other managed
  one-shot job is already active, rather than interrupting it;
- records exactly which runtime units were active beforehand;
- stops OAuth before the app;
- stops app and daemon;
- resolves the active Christiania database path;
- checks DB, WAL and SHM files for process holders with `fuser` or `lsof`;
- fails closed if holder inspection is unavailable or any holder remains.

This closes the orphaned read-only planner/WAL-holder failure mode observed
during the Sep-16 attempt. After remote verification, the destructive path
revalidates maintenance ownership and proves zero DB/WAL/SHM holders again
immediately before opening SQLite.

Production prune planning is refused while canonical maintenance is active.
Planning belongs before maintenance entry; once maintenance owns the runtime,
no second read-only planner may pin a fresh WAL snapshot.

### Maintenance rehearsal

The bundled command:

```bash
sudo /opt/christiania/deploy/christiania-maintenance rehearse
```

performs **no database operation**.

It exercises the real maintenance enter/exit path, verifies quiescence and
Theta continuity, then restores the exact recorded runtime. A rehearsal error
uses the same recovery path and retains maintenance state when restoration is
incomplete.

A successful rehearsal must end with:

- `CHRISTIANIA_MAINTENANCE_REHEARSAL_QUIESCE_PASS`
- `CHRISTIANIA_MAINTENANCE_REHEARSAL_PASS`
- no maintenance state file remaining.

## Operator commands

Read archived-session analysis:

```bash
python christiania_ops.py archive-analyze-session \
  --session-date YYYY-MM-DD \
  --source archive \
  --json
```

Run the same analysis against hot evidence:

```bash
python christiania_ops.py archive-analyze-session \
  --session-date YYYY-MM-DD \
  --source hot \
  --json
```

Compare hot and archived research semantics:

```bash
python christiania_ops.py archive-compare-session \
  --session-date YYYY-MM-DD \
  --json
```

Read-only V2C planning remains available outside a maintenance window:

```bash
python christiania_ops.py archive-prune-plan \
  --session-date YYYY-MM-DD \
  --verify-remote \
  --json
```

Destructive apply requires the canonical maintenance state and explicit
matching session confirmation.

## Production rollout gates

Deployment of this bundle and execution of a prune are separate decisions.

### Gate A — release validation

Before merge:

- Windows full Christiania quality gate green on the exact PR head;
- Linux release smoke green on the exact PR head;
- migration 034 tests green;
- maintenance shell syntax and executable mode green;
- storage/history regression set green;
- final diff and migration review complete.

### Gate B — deployment

The standard immutable release receiver performs the v33→v34 migration through
Christiania's existing release-migration/rollback-copy path.

After deployment prove:

- exact deployed commit;
- schema v34;
- `PRAGMA integrity_check = ok`;
- `PRAGMA foreign_key_check` empty;
- all four new support indexes present;
- prune commit ledger + immutability triggers present;
- control plane READY;
- public edge PASS;
- app/daemon/Theta/OAuth/Caddy active.

### Gate C — maintenance rehearsal

Run the canonical non-destructive rehearsal and then prove the control plane and
public URL recover to READY/PASS.

A rehearsal failure blocks all destructive storage work.

### Gate D — Sep-16 research parity

Before any prune:

- run archive analysis;
- run hot analysis;
- run hot/cold comparison;
- require parity PASS and matching canonical hashes.

### Gate E — full V2C plan

Run remote-revalidating prune plan and inspect:

- local archive verified;
- remote immutable restore gate verified;
- run lineage exact;
- outside hot window;
- archive/hot row counts exact;
- FK parent-delete indexes PASS;
- Historical Analysis V1 parity PASS;
- expected deletable/preserved counts;
- no blockers.

### Gate F — destructive apply

Only after Gates A–E pass:

1. enter canonical maintenance;
2. prove zero DB/WAL/SHM holders;
3. execute one explicitly confirmed prune session;
4. observe bounded batch progress;
5. require trigger restoration, FK check, reconciliation, ledger staging and
   transaction commit;
6. require/recover external receipt;
7. exit maintenance;
8. prove production READY and public edge PASS.

No second prune is bundled into the same operator transaction.

## Physical compaction remains separate

Logical pruning increases SQLite freelist space but does not promise to shrink
`trade_log.db`.

VACUUM, VACUUM INTO, backup/restore compaction or filesystem relocation remain
a separate Storage V2D decision after post-prune measurements of:

- DB file size;
- page count;
- freelist count/bytes;
- WAL size;
- free filesystem headroom;
- verified recovery points.

This bundle deliberately performs no automatic physical compaction.
