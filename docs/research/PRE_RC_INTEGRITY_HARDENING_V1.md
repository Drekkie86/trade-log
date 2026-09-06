# Christiania V1 — Pre-RC Integrity Hardening

Package 13.5 closes review findings before hosted RC work.

## Risk-plan origin

`shadow_risk_plans.created_at` is an effective/requested timestamp and is **not** trusted as proof of when the plan was actually recorded. Migration 027 adds DB-generated `shadow_risk_plan_recordings.recorded_at`. New plans are refused outright if any shadow mark already exists for the candidate. This rule does not compare caller-controlled timestamps.

## Outcome populations

Raw shadow marks and predeclared risk-trigger exits are separate measurement populations. `PREDECLARED_RISK_EXIT_OUTCOME` rows live in `shadow_risk_exit_outcomes`; they are never silently substituted for `VALIDATED_PACKAGE_OUTCOME` marks. The union view `v_shadow_outcome_populations_v1` preserves an explicit `measurement_role`.

## Migration execution

The supported generic migrator uses `src/database/migration_runner.py`, executes each pending migration inside `BEGIN IMMEDIATE` / `COMMIT`, validates the target schema before commit, and rolls back all statements on failure. A regression test deliberately fails mid-migration and verifies that earlier DDL does not survive.

## Provider capability proof

Cash-settled live-data proof is integrity checked, code-version bound, and time limited. Tampered, stale, old-format, or code-mismatched evidence fails closed. The state name `LIVE_DATA_CONTRACT_VALIDATED*` deliberately describes data-contract capability, not executable liquidity or trade eligibility.

## Settlement semantics

PM-settled XSP/SPXW use the official index close event and resolve the actual XNYS close from the market calendar. Christiania does not hard-code 16:00 ET for early-close sessions. Standard SPX remains AM/Special Opening Quotation with no fabricated single settlement timestamp.

## Decision Desk

V1's `ELIGIBLE FOR MANUAL REVIEW` disposition remains intentionally unreachable while event-risk context and calibrated net EV are unavailable. A behavioral regression test locks this invariant.
