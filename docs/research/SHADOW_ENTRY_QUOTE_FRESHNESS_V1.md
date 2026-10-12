# Shadow Entry Quote Quality V1 — Gate A P0 correction

Status: **DRAFT, no deployment authority**. Reviewed alongside Gate A issue #96.

## Defect addressed

Prior intrinsic shadow admission checked that the target ThetaData quote and Greek observation were marked PRESENT, then labelled the admitted candidate FRESH without computing decision-time age for the actual butterfly legs. The old local schema-v27 sample found 14/15 admitted candidates had an oldest leg quote >60 seconds old when admission occurred, conditional on documented ET timestamps. These observations are not current production evidence.

## New rule

The module src/research/shadow_entry_quote_quality_v1.py is a read-only, bounded, exact-ID per-leg gate. It does not create a second shadow ledger.

A future candidate is labelled FRESH only when all of the following hold:

1. The latest stored ThetaData timestamp-semantics validation has DOCUMENTED_AND_LIVE_VALIDATED, live_probe_state=PASSED, compatible America/New_York offset/DST/documentation checks, and a validation timestamp no later than the decision.
2. The structure contains 1–8 distinct persisted quote IDs.
3. Each quote belongs to the same underlying, research run and ThetaData provider, matches its leg's expiration/strike/right, and all quotes belong to one recorded source snapshot.
4. The frozen entry pricing must declare BUY_AT_ASK_SELL_AT_BID and contain exactly one record per required quote ID, with matching side, quantity and source-side entry price. Missing, duplicated and changed frozen leg prices are blocked, never recomputed silently.
5. A proposal must exist at or before the frozen admission decision timestamp, and the decision timestamp must explicitly identify its timezone.
6. Every leg has nonnegative, noncrossed, explicitly FETCHED bid and ask, each with an interpretable provider quote timestamp and independent bid/ask timestamps.
7. Provider source quote, bid and ask ages at immutable admission time are in [0,15] seconds, source times do not postdate source capture, snapshot age is in [0,15] seconds, and all leg timestamps are mutually no more than 15 seconds apart.

Limits reuse the existing first-cohort FRESH classification contract and are tagged SHADOW_ENTRY_PER_LEG_ASOF_15S_V1. They are conservative engineering gating rules, **not statistically calibrated trading-edge thresholds**. Do not optimize them on historical outcomes without preregistration.

New rejected proposals record a BLOCKED immutable admission decision and structured entry_quote_quality evidence; accepted candidate freshness comes from the successful gate result, not a literal hard-coded value. The same admission_at is used for as-of evaluation and the persisted decision timestamp.

## Boundaries

- No conversion of old candidate labels; no historical rewrites; no broker orders and no production changes.
- FRESH means **leg-level source time and bid/ask integrity passed**. It does not establish an executable multi-leg package, broker-approved order size, reliable size-at-touch, Saxo commission, assignment/expiry treatment, verified net P&L or trading edge.
- These rules may legitimately block all future candidates if provider clock-validation evidence is missing. That is intentional: no fabricated validation rows or silent gate bypass.
- Synthetic tests insert a clearly labelled *mock* validated timestamp record. Production validation must originate from actual documentation and live evidence.
- The checker uses bounded exact option-quote ID lookups (eight or fewer) and one latest validation row; this is not a production performance certification.

## Tests

Run: python -m pytest -q tests/test_shadow_entry_quote_quality_v1.py tests/test_shadow_admission.py tests/test_shadow_risk_lifecycle_v1.py tests/test_shadow_lifecycle_runtime_v1.py

The fixture now uses **three separate source quote IDs** for the 95/100/105 butterfly instead of reusing one target quote ID across strikes, plus a frozen session clock. Tests verify fresh acceptance, per-leg stale blocking, immutable reasons, idempotence, clock validation failures, source-run mismatch, duplicate IDs, quote-age boundaries, future timestamps and wrong strike identity.

## Remaining Gate A dependencies

Current production census, provider-validation provenance, stage 1 quote-side size/liquidity, broker package tradability, contemporaneous independent outcome timing, actual fees/slippage/tax/FX costs and forward out-of-sample economic validity are **unverified**. No strategy may be promoted or traded based on this patch or the Stage-0 calculator.
