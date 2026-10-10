# Bounded prospective science by genuine session (research V1)

Status: read-only date-sliced research instrument, not a replacement for the frozen H1-H4 evaluator, persisted checkpoint, calibration decision, or trading signal.

## Problem and provenance

On 10 October 2026 production held 17 eligible post-freeze session dates (through October 5) and 6,596,065 prospective observation rows. Its persisted H1-H4 evaluations still only covered six dates through September 17, with 1,058,895 checkpoint rows. The old unrestricted evaluator aggregates and sorts millions of records; do not run it on the actively used production DB.

The separate Oct 6-9 historical EOD archive contains only DTE 0-7, and no contemporaneous original research runs. It cannot increase the prospective independent-date counter.

## Technical design

Module: src.research.bounded_prospective_session_v1

- Reuses the EXACT original frozen _centered_cte() and _flush_linear_group() implementations. Does not modify any frozen scientific hypothesis or original data.
- Defaults to EXPLAIN QUERY PLAN for one research run: metadata only, zero option quote data read. Full day evaluation requires explicit --execute-one-session and never writes to the database.
- Verifies latest freeze and calibration null, and selects a canonical, post-freeze session date. All observation SQL is restricted by BOTH research_run_id and us_session_date.
- Refuses full/unindexed production source table scans: expects indexed SEARCH o on the residual observation table, no SCAN o.
- Opens in SQLite URI mode=ro with PRAGMA query_only=ON. Limits: 64 runs per date, 500,000 rows, 20s default, hard configurable 120s maximum, 80m VM opcodes. Any incomplete evaluation fails closed, never reports a partial scientific result as successful.
- H1: frozen-null-centered 14-20 DTE per-date residual; H2: original same-snapshot interpolation comparator; H3: frozen market-spread / Greek-age conditioning; H4: original contract/date episode units and SHA-256 signed integrity of episode list.
- The separate combine_completed_sessions verifies unique date coverage, matching frozen null, complete episode digests, then reconstructs H4 cross-date recurrence ranking. It retains H2 **per independent date**, not pseudo-independent millions of rows.

## Scientific limitations

Local-linear H2 uses neighboring strikes **from the same historical snapshot**. Quadratic measures a residual centered against a **frozen null**; they are not identical forward-prediction protocols. More in-snapshot interpolation accuracy is not validated future prediction, option expectancy, fillable profits or a trading admission. H4 selected top100 is not a population hit rate; H3 associations not causal; within-day rows correlated.

No p-values, FDR, admissions, automatic model selection, edge, order, or trading path enabled. This module does NOT persist new H1-H4 checkpoint records; issue #93 stays open.

## Operational gates

1. CI on exact main Windows/Python3.13 and Ubuntu release smoke.
2. Production readiness + exact active SHA, no overlapping backups/restores.
3. Metadata-only EXPLAIN for one eligible date using module CLI --session-date and --db-path; without --execute-one-session. Inspect query indexed-access verdict.
4. After independent budget proof, one explicit day with bounded 20s, 500k row and SQLite VM step caps. Stop immediately on failure rather than bypassing safeguards.
5. Only after safe, completed date fragments across all 17 sessions, create independently validated, date-weighted 17-day descriptive science report; compare six old vs eleven later dates.
6. Separately score ONLY forecasts frozen before later observed outcomes; absent matched pairs, predictive ability and net expectancy are NOT MEASURABLE.

No production package, service, timer, schema or DB changes are part of this initial research increment.
