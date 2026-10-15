# Shadow Lab candidate evidence gate — 15 October 2026

Status: read-only diagnostic, newest 40 candidates, actual main Shadow Lab page. Not order execution or scoring.

## Production evidence

- 507 research runs; latest on October 15.
- 3,621 structure proposals.
- Legacy wallet policy: 149 historical decisions (15 admitted, 134 blocked), last September 17.
- New intrinsic-risk policy: 295 admissions at initial inspection; 297 when preview was run.
- 44,025 marks on first inspection, none eligible, no recorded risk plans under either policy and zero canonical outcome observations.
- Global Theta timestamp contract live_probe_state remains NOT_RUN and decision_enabled=0. A historic FRESH label is not independent timestamp proof.
- Recent-40 gate query completed against production SQLite in 6.55ms read-only. All 40 sampled candidates had marks, 0 had prospective recorded risk plans, and 0 had independently verified package receipts.

## Implemented

Canonical Shadow Lab read model loads a bounded sample of the newest 40 candidates, including policy source from the union view (legacy versus intrinsic), older raw quote/Greek classifications, admission quote reference, global Theta source-clock proof, prospectively database-recorded immutable risk plan, subsequent marks, eligible mark counts and separately recorded canonical outcome counts.

Per-candidate reasons: ENTRY_QUOTE_REFERENCE_MISSING, LEGACY_QUOTE_CLASS_NOT_FRESH, PROVIDER_CLOCK_LIVE_PROBE_NOT_VERIFIED, ENTRY_LEG_ASOF_RECEIPTS_NOT_VERIFIED, PROSPECTIVE_RISK_PLAN_NOT_RECORDED, NO_EVIDENCE_ELIGIBLE_OUTCOME_MARK, INDEPENDENT_ENTRY_EXIT_PACKAGE_RECEIPTS_MISSING.

Scoring remains explicitly NOT_ELIGIBLE even if an older observation is FRESH or a mark is flagged eligible: canonical independent native-package entry/exit receipts are not recorded or verified. No historic candidate is retroactively promoted.

The actual main Shadow Lab sidebar displays the recent sample, missing evidence and separate legacy/new cohort totals. It labels the recent sample NOT the complete population. The current 11-strategy synthetic workbench is retained, separated from this real evidence gate.

No new tables, migration, SQLite writes, broker calls, order permissions, admission changes, daemon changes or retrospective reconstruction. No change to the EUR 500 defined-risk experiment or intrinsic-research risk policy.

## Release requirements

Unit/contract tests, no cross-page scans, exact main CI, Python3.13 Linux lock, bounded production critical page performance, backup/rollback headroom, detached release and post-activation app, daemon, Theta and health checks. Production query benchmark was 6.55ms for newest 40 candidates. No proof of broker executable P&L.

## Remains P0

1. Independently validate Theta v3 timestamp semantics (DST/precision and per-leg as-of provenance).
2. Preregister and freeze explicitly reviewed entry/exit/stop/event rules BEFORE initial mark using existing immutable risk plan tables. No made-up risk rules.
3. Production-grade durable opportunity/NO_TRADE/evidence journal and migration only when recovery safeguards permit.
4. Verify Saxo source permissions/quote depth/native complex-package price only, bounded budgets and realistic fees/FX.
5. Match independent complete entry/exit package receipts, record censoring and all rejected/no-trade opportunities.
6. Compare conservative net expectancy and uncertainty on a frozen forward holdout. No inferred fills.
7. Sustainable backup architecture issue #113, restore/headroom #84: no deleting protected recovery copies.
