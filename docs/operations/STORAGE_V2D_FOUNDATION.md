# Christiania Storage V2D Foundation

## Purpose

Storage V2D turns the V2/V2B/V2C archive work into a durable hot/cold research
architecture.

The bundle is deliberately larger than an isolated performance patch. The
September 16 maintenance incident exposed three coupled requirements:

1. old high-volume research evidence must remain scientifically usable after it
   leaves the hot database;
2. destructive pruning must be bounded, observable and schema-safe; and
3. maintenance itself must be a controlled runtime state transition rather
   than an operator-maintained list of services.

V2D therefore ships the analytical and operational safety foundation together.
Deployment of V2D does **not** itself delete historical evidence and does not
compact the database.

## Non-goals

V2D does not:

- automatically prune a session;
- run `VACUUM`;
- rewrite old archive databases to a newer schema;
- change strategy, scanner or admission semantics;
- convert archive evidence into a new derived scientific result;
- make Object Storage the primary query engine;
- permit a failed parity or index audit to be overridden by an operator flag.

## Evidence tiers

### Hot primary

The production SQLite database remains authoritative for current operation,
governance, candidate/trade state and the newest research window.

Reference-aware V2C semantics remain: high-volume rows that are still parents
of surviving governance or research evidence are preserved hot.

### Immutable cold raw evidence

A whole-session V2 archive contains the high-volume raw research closure:

- research runs and daemon iterations;
- market snapshots;
- normalized option quotes;
- provider model observations;
- listing reference contracts;
- provider observation availability;
- hypothesis scanner runs/evaluations;
- local Surface V2 runs/observations.

The archive is immutable. If it was created under schema v33 and production is
now v34 because v34 added indexes, the archive stays v33. Indexes are an
operational property, not historical evidence.

### Hot governance + cold universe

The intended long-term analytical model is hybrid:

- actual candidate/trade/governance/outcome evidence stays available in the hot
  operational layer when referenced;
- the very large unused/rejected option universe may live cold;
- retrospective model replay opens verified cold raw evidence read-only and
  combines it with the relevant hot governance/outcome layer.

This is preferable to keeping the primary SQLite file as an unbounded research
warehouse or restoring full historical production backups for routine research.

## Full-content parity contract

Row counts alone are not sufficient proof that an archive is analytically
equivalent to the source evidence.

V2D fingerprints every table in `ARCHIVE_TABLE_SPECS` twice:

1. the exact session-scoped extraction from the hot database using the same SQL
   contract used by archive creation; and
2. the corresponding table in the verified materialized cold archive.

### Canonical fingerprint

For each table Christiania:

- uses a deterministic row ordering;
- includes ordered column names in the digest;
- encodes every SQLite value with an explicit type tag;
- preserves IEEE-754 float bytes rather than decimal reformatting;
- includes NULL, integer, text and binary values unambiguously;
- hashes every row with SHA-256;
- records row count, ordered columns and content SHA-256.

Parity requires the complete fingerprint objects to be equal for every archive
table.

A one-value difference, missing row, extra row, changed type or changed column
shape fails parity.

### Parity receipt

A successful parity run writes a local
`*.parity-receipt.json` bound to:

- exact session date and run IDs;
- exact archive manifest filename and SHA-256;
- compressed and uncompressed archive payload hashes;
- immutable archive source schema version;
- current production schema version;
- every hot table fingerprint;
- every cold table fingerprint;
- state `HOT_COLD_CONTENT_PARITY_VERIFIED`.

The receipt is an operational gate, not a replacement for the immutable remote
proof. V2C still revalidates the local archive and V2B remote object proof
before destructive work.

A schema upgrade invalidates a previous parity receipt until parity is rerun
under the new active schema. The archive itself is not rewritten.

## Verified cold analytical access

`open_verified_archive_session()` is the canonical code path for future cold
research consumers.

Before yielding a SQLite connection it:

1. locates exactly one archive for the requested session;
2. verifies the compressed payload against the immutable manifest;
3. materializes the gzip payload into a temporary database;
4. hashes the uncompressed bytes while materializing;
5. verifies exact uncompressed size and SHA-256;
6. opens the materialized SQLite database with `mode=ro&immutable=1`;
7. runs `PRAGMA integrity_check`;
8. verifies embedded archive metadata against the manifest; and
9. enables SQLite `query_only`.

The materialized file exists only for the context lifetime and is deleted on
exit.

`archive-session-profile` is the first operator-facing analytical consumer. It
proves the archive can be queried as research data rather than merely restored
as disaster-recovery bytes. It reports the archived table population, option
quote universe/completeness, provider-model population and scanner-state
population.

Future replay modules should consume the same verified session context rather
than implementing independent decompression or trust logic.

## Parent-delete FK index contract

SQLite checks child foreign keys while deleting parent rows. Without a child
index beginning with the FK columns, each parent delete can require repeated
child-table scans.

That was the mechanism behind the pathological
`listing_reference_contracts` delete observed during the September 16 V2C
attempt.

### Schema v34

Migration 034 adds the support indexes that were absent in the reviewed schema:

- `shadow_candidates(reference_contract_id)`;
- `shadow_candidates(entry_quote_observation_id)`;
- `shadow_candidates(entry_greek_observation_id)`;
- `hypothesis_scanner_evaluations(reference_contract_id)`;
- `hypothesis_scanner_evaluations(option_quote_id)`;
- `local_surface_residual_v2_observations(reference_contract_id)`.

Existing leading indexes/unique indexes already cover downstream foreign keys
into the other V2C target parents. The generic audit, rather than this
hard-coded list, is the enduring requirement.

### Generic audit

The enduring contract is not the hard-coded list above.

`archive-prune-index-audit` enumerates every table, groups every SQLite foreign
key, selects only FKs whose parent is:

- `listing_reference_contracts`; or
- `option_quotes`;

and requires a non-partial child index whose leading columns exactly match the
FK child columns in order. The audited parent set is the complete V2C delete
set:

- `local_surface_residual_v2_observations`;
- `hypothesis_scanner_evaluations`;
- `provider_model_observations`;
- `provider_observation_availability`;
- `listing_reference_contracts`;
- `option_quotes`.

A new migration that introduces another child reference without an appropriate
index makes the audit fail automatically. V2C plan/apply then becomes
ineligible.

## Bounded atomic deletes

V2D keeps V2C's single explicit `BEGIN IMMEDIATE` transaction. There is no
partial-commit mode.

The difference is statement size.

For each target table Christiania:

1. uses the already materialized reference-safe delete ID set;
2. reads the next ordered bounded group of IDs;
3. deletes only that ID range intersected with the reviewed temp delete set;
4. requires SQLite `changes()` to equal the exact expected batch size;
5. emits cumulative real row progress;
6. advances only after the batch reconciles; and
7. continues until the full reviewed delete population is consumed.

Default batch size is 50,000 rows. The reviewed configurable bounds are 1,000
through 250,000 via `CHRISTIANIA_PRUNE_DELETE_BATCH_SIZE`.

All batches remain in the same transaction. An exception, operator interrupt or
failed reconciliation rolls the transaction back.

The receipt records the batch size used.

## V2C eligibility after V2D

A prune plan is eligible only when all previous V2C gates still pass **and**:

- a valid current-schema hot/cold parity receipt exists;
- the parity receipt is bound to the current archive manifest/payload/run IDs;
- every prune-parent child FK has a supporting leading index.

The plan surfaces parity and FK-index state explicitly.

The apply path validates parity before expensive remote/destructive work, then
rechecks the full plan inside the write transaction.

## Maintenance contract

The canonical command is:

```text
sudo /opt/christiania/deploy/christiania-maintenance <command>
```

Supported commands:

- `status`
- `enter`
- `exit`
- `rehearse`

### Enter

Maintenance:

1. atomically claims the root-owned runtime state file;
2. records which core DB consumers, OAuth edge and timers were active;
3. stops scheduling timers;
4. refuses to proceed if any one-shot backup/audit/restore/health job is
   already active;
5. stops OAuth;
6. stops daemon/app DB consumers;
7. proves those consumers are down;
8. proves Theta remains active; and
9. only then declares maintenance entered.

It does not kill an active backup or restore drill.

### Exit

Exit restores only the services/timers recorded as active before entry and
keeps the state file if restoration is incomplete.

### Rehearsal

`rehearse` performs no SQL, checkpoint, archive operation, prune or compaction.

It:

1. snapshots runtime state;
2. enters maintenance;
3. proves Theta stays active;
4. proves DB consumers/OAuth/timers are quiesced;
5. proves no one-shot work became active;
6. exits maintenance;
7. snapshots runtime state again;
8. requires exact before/after equality; and
9. emits `MAINTENANCE_REHEARSAL_PASS`.

This is the production prerequisite before the next destructive storage window.

## Operator commands

### Audit FK support indexes

```bash
python christiania_ops.py archive-prune-index-audit --json
```

Expected state: `passed=true`, no missing entries.

### Query cold research evidence

```bash
python christiania_ops.py archive-session-profile \
  --session-date 2026-09-16 \
  --json
```

This is read-only and transiently materializes the verified archive.

### Prove hot/cold content parity

```bash
python christiania_ops.py archive-parity \
  --session-date 2026-09-16 \
  --json
```

This may scan millions of rows. Progress is emitted to stderr while JSON remains
clean on stdout.

A successful run creates the session parity receipt.

### Inspect prune plan

Only after the prior gates:

```bash
python christiania_ops.py archive-prune-plan \
  --session-date 2026-09-16 \
  --verify-remote \
  --json
```

Planning is non-destructive.

## Release rollout

V2D rollout is intentionally split into deployment and evidence proving.

### Phase 1 — CI/release

Require:

- full Windows Python 3.13 quality gate;
- Linux release smoke;
- fresh DB migration to v34;
- migration/foreign-key integrity;
- maintenance shell syntax;
- all archive/prune regressions.

### Phase 2 — production deployment

Deploy through the immutable release receiver. Schema v34 is a real migration;
the release migration/rollback machinery remains authoritative.

Before the release rollback snapshot is created, the migration path now applies
the same WAL-aware capacity contract as normal verified backups:

- logical source size is the greater of main-file bytes and
  `page_count * page_size`;
- one complete rollback copy must fit;
- the configured production free-space reserve must remain after that copy;
- capacity failure occurs before a rollback snapshot is created or rollback
  metadata is committed into the receiver's pre-created private pointer
  workspace.

A failure while the SQLite backup API is writing the temporary rollback copy
removes that partial temporary file. A rollback artifact is promoted only after
SQLite verification, file fsync, atomic rename and directory fsync.

After activation require:

- exact release identity;
- schema v34;
- `christiania-status` READY;
- public edge PASS;
- resource policy PASS;
- no active maintenance state.

### Phase 3 — non-destructive maintenance rehearsal

Run:

```bash
sudo /opt/christiania/deploy/christiania-maintenance rehearse
```

Require `MAINTENANCE_REHEARSAL_PASS`, then refresh supervisor and prove
Christiania returns READY/public-edge PASS.

### Phase 4 — storage/readability gates

Run, in order:

1. prune FK index audit;
2. Sep-16 cold session profile;
3. Sep-16 full hot/cold content parity;
4. local archive deep verification;
5. remote immutable proof verification;
6. non-destructive prune plan.

At the end of V2D rollout, stop.

Do **not** run `archive-prune-session` as part of bundle validation.

## Rollback

### Before schema migration commits

The normal release receiver rollback path restores the previous release and
database according to the release migration contract.

### After v34 migration

Migration 034 only adds indexes and a schema-version row. It does not transform
evidence values.

A failed activation uses the normal release/database rollback mechanism. Do not
manually drop indexes on production as an improvised rollback.

### Parity/profile failure

No database mutation has occurred. Preserve the archive/receipt evidence and
investigate. Do not prune.

### Maintenance rehearsal failure

The command's failure trap attempts restoration. If restoration is incomplete,
the maintenance state file is intentionally retained and must be inspected
before another maintenance attempt.

## Acceptance criteria

The bundle is accepted only when all of the following are demonstrated:

- schema v34 deployed;
- generic prune FK audit PASS;
- public application READY after deployment;
- maintenance rehearsal PASS;
- Sep-16 verified cold profile succeeds;
- Sep-16 full-content parity PASS;
- parity receipt validates;
- remote V2B proof still verifies;
- prune plan reports parity PASS and FK-index PASS;
- no destructive prune has occurred during bundle rollout.

Only after those facts are captured should a later maintenance package decide
whether and when to execute V2C pruning.
