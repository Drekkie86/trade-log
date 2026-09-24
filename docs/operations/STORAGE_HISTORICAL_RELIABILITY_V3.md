# Christiania Storage & Historical Research Reliability V3

## Purpose

This package hardens Christiania's hot/cold research architecture after the first production V2C prune attempt exposed two separate weaknesses:

1. a large parent DELETE could become pathologically slow when SQLite had to repeatedly scan unindexed child foreign-key columns; and
2. preserving archive bytes is not enough unless archived research evidence is directly usable for later model replay and analytical re-evaluation.

V3 treats those as one reliability problem. Storage reduction is allowed only when the evidence remains verifiably recoverable and analytically usable.

This package does not make pruning automatic.

## Release scope

V3 contains four coordinated layers:

1. maintenance-boundary hardening;
2. schema/index hardening;
3. bounded reference-aware pruning;
4. verified historical research read-through and hot/cold analytical parity.

The package intentionally does not perform VACUUM, physical compaction, automatic remote deletion, or unattended destructive pruning.

## 1. Maintenance boundary

Canonical commands:

    sudo /opt/christiania/deploy/christiania-maintenance enter
    sudo /opt/christiania/deploy/christiania-maintenance exit
    sudo /opt/christiania/deploy/christiania-maintenance rehearse

The rehearsal performs no SQLite write, checkpoint, prune or compaction. It records the exact active DB-consumer, secure-edge and timer state; stops scheduled timers; refuses entry if an in-flight one-shot backup, audit, health or recovery job is still active; stops OAuth, app and daemon while keeping Theta active; proves quiescence; restores the exact recorded runtime state; refreshes the supervisor; and requires the deployment-safe control-plane contract.

If rehearsal verification fails after maintenance entry, the failure trap attempts runtime restoration before returning failure. Incomplete restoration keeps the state file visible instead of silently clearing it.

The state-ownership file is acquired atomically so two operators cannot simultaneously own one maintenance window.

## 2. Schema v34: prune-parent FK support indexes

SQLite enforces child foreign keys during parent deletion. A parent delete can therefore perform repeated child-table scans when the child's FK columns do not have a leading supporting index.

The schema-wide V2C audit found four missing child-side indexes:

- shadow_candidates(reference_contract_id)
- hypothesis_scanner_evaluations(reference_contract_id)
- hypothesis_scanner_evaluations(option_quote_id)
- local_surface_residual_v2_observations(reference_contract_id)

Migration 034 adds exactly those four indexes. It changes no research evidence, foreign-key semantics, immutability semantics, or admission/model behaviour.

### Dynamic FK/index audit

src.operations.prune_fk_index_audit discovers every live foreign key whose parent is listing_reference_contracts or option_quotes. For every discovered relationship it proves that the child table has either a primary key whose leading columns match the FK or an index whose leading columns match the FK.

A later migration that adds another child FK without an appropriate support index will therefore fail the audit even though that relationship did not exist when V3 was written.

Operator command:

    python christiania_ops.py archive-prune-index-audit
    python christiania_ops.py archive-prune-index-audit --json

The normal quality gate runs the same audit against a freshly built, fully migrated database. This makes V2C FK/index coverage a repository-level schema invariant.

## 3. Bounded atomic pruning

V2C remains reference-aware. The planner still computes the complete session-scoped delete sets before dropping any immutability guard.

V3 changes how those already-approved delete sets are executed. Each target delete set is traversed in ascending ID order and executed in bounded batches.

Default batch size: CHRISTIANIA_PRUNE_DELETE_BATCH_ROWS=25000.

Accepted range: 1 through 100000 rows.

One-invocation override:

    python christiania_ops.py archive-prune-session --session-date YYYY-MM-DD --confirm-session YYYY-MM-DD --delete-batch-rows 25000

Every batch reports target table, batch number, expected rows in the ID range, rows actually deleted, cumulative rows deleted, total delete-set size, and statement elapsed time. A batch row-count mismatch raises immediately.

### Atomicity is unchanged

Chunking is not chunked commit. All six target families still execute inside the same explicit BEGIN IMMEDIATE transaction.

The transaction still performs full plan revalidation, exact trigger capture/hash, allow-listed delete-trigger removal, every bounded delete batch, exact total-row reconciliation, trigger restoration/hash comparison, foreign_key_check, post-delete candidate reconciliation, and one final COMMIT.

Any exception before the final commit rolls back the transaction. If SQLite has already automatically rolled back an interrupted statement, Christiania checks conn.in_transaction and preserves the original interruption error rather than masking it with a second invalid rollback.

The receipt records both configured batch size and actual batch count per target table.

## 4. Verified historical research read-through

V2 archives remain immutable compressed SQLite evidence. V3 does not rewrite old archives to the current production schema.

open_verified_archive_connection() validates the immutable manifest and compressed payload binding, decompresses to a transient SQLite file while computing the uncompressed SHA-256, requires hash and size equality, opens the file mode=ro, enables PRAGMA query_only, requires integrity_check=ok, then closes and destroys the transient copy when the query context exits.

This is the raw historical evidence interface for future replay code. It is not limited to a precomputed report. The archive's original source_schema_version remains explicit provenance.

## 5. Analytical profile

V3 adds a deterministic session-level analytical profile that can be run using the same logic against either the hot production evidence or the immutable cold session archive.

For every archived family the profile records row count, minimum ID, maximum ID and ID population sum. It also records deterministic availability/timestamp metrics and categorical distributions for research-run status, option right, provider-model provider, provider-observation state/family, scanner state/direction and Surface V2 state/reason. Replay-relevant raw fields are streamed in evidence-ID order into typed SHA-256 fingerprints; floating-point values use their exact Python/SQLite binary value representation rather than order-sensitive SQL sums.

The canonical analytical payload is serialized deterministically and SHA-256 hashed. Source location and current/source schema version remain provenance but are intentionally excluded from the analytical hash because migration 034 changes indexes, not archived research meaning.

## 6. Hot/cold analytical parity

Operator commands:

    python christiania_ops.py archive-profile-session --session-date YYYY-MM-DD
    python christiania_ops.py archive-parity-check --session-date YYYY-MM-DD

Parity state is HOT_ARCHIVE_ANALYTICAL_PARITY_PASS or HOT_ARCHIVE_ANALYTICAL_PARITY_FAIL.

A pass requires identical table-identity profiles, scalar analytical metrics, ordered raw-field analytical fingerprints, categorical distributions and canonical analytical SHA-256.

This detects more than missing rows. A hot quote-value change can fail parity even when row count and row IDs remain unchanged. Archive payload hashes remain the byte-level durability proof; the ordered fingerprints are the deterministic query-path proof for replay-relevant fields.

The archive manifest and payload hashes prove evidence durability. Analytical parity proves that Christiania can actually read the cold evidence through its supported historical query path and obtain the same research population and metrics it obtains from the hot copy. V3 requires both.

## 7. V2C eligibility gates after V3

Existing gates remain: local archive verification, immutable off-host restore verification, session/run lineage, hot-window boundary, exact archive/live target counts, reviewed schema version, reference-safe delete-set reconciliation, and at least one deletable row.

V3 additionally requires prune-parent FK index coverage PASS and HOT_ARCHIVE_ANALYTICAL_PARITY_PASS.

The plan surfaces FK-index audit state, every missing FK/index relationship, hot analytical SHA-256, archive analytical SHA-256 and analytical parity state.

The destructive apply recomputes those gates against the transaction-protected hot state. It does not trust an earlier successful CLI check.

## 8. Historical performance interpretation

Storage V2C deliberately preserves hot rows that remain referenced by later strategy, governance, selection, candidate, shadow or replay evidence.

Christiania's low-volume decision/performance lineage therefore stays hot while the large unused/rejected market universe can move cold.

The intended future analysis model is hybrid:

    HOT decision / governance / outcome lineage
      +
    COLD verified full historical market/research universe
      =
    retrospective replay / re-scoring / performance attribution

This avoids keeping an unbounded raw market warehouse in the primary SQLite database while preserving the historical universe needed to re-run new models and test counterfactuals.

## 9. Operational sequence

A safe future prune sequence is:

1. deploy V3 through the normal immutable release receiver;
2. verify schema v34 migration and production control-plane state;
3. run christiania-maintenance rehearse;
4. run archive-prune-index-audit;
5. run archive-profile-session;
6. run archive-parity-check;
7. run archive-prune-plan --verify-remote;
8. review the complete plan and blocker list;
9. enter canonical maintenance;
10. re-run the destructive command with exact session confirmation;
11. verify receipt, FK integrity, trigger restoration and control-plane/public edge recovery;
12. exit without physical compaction.

Physical compaction remains a separate V2D decision after post-prune file size, freelist, disk headroom and recovery requirements have been measured.

## 10. Explicit non-goals

V3 does not auto-prune a session, auto-VACUUM the production database, rewrite historical archives, delete off-host evidence, weaken Object Lock retention, delete research_runs, delete referenced evidence merely to reclaim space, change trading strategy/model/admission/bankroll policy, or convert retrospective evidence into prospective proof.

Storage remains subordinate to evidence integrity and research reproducibility.
