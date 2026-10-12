# Shadow Lab rollout on the 12 October operational baseline

**Release candidate base:** `main` operational fix `81cbc73` (already deployed).
**Bundle:** Offline Gate A/B/C research components combined from draft PR #108.
**Status:** Code integration candidate, NOT a fully operating broker-paper system.

## Current actual production Shadow Lab (read-only audit 12 Oct 21:05 UTC)
- 265 shadow candidates; 149 admission decisions (15 ADMITTED, 134 BLOCKED)
- 31,979 marks, all INDEPENDENT_LEG_LIQUIDATION_STRESS and outcome_eligible=0
- 0 shadow_outcome_observations, 0 risk plans
- Theta timestamp semantics NOT_RUN, decision_enabled=0
- 0 independently validated package outcomes

## Code in this bundle
- Deterministic, offline 11-family strategy feasibility/falsification evaluator.
- Fail-closed, as-of per-leg entry quality check. **Operational effect:** new
  shadow admissions without verified contemporaneous source timestamp semantics
  are BLOCKED, rather than labelled fresh without evidence.
- Conservative fee/FX quote-side two-time paper leg P&L. Always ineligible as
  proof of independently executable package fills.
- Two bounded Saxo options quote read adapters, BOTH disabled by default;
  native multi-leg is a PRICE-only POST, never an order endpoint.
- Source attempt and NO TRADE journal as **reference staging schema only**
  in docs/research; no production table/migration or autonomous writer.
- Freeze on shadow SCORED state without independently verifiable receipts.

**There are no Streamlit page changes in this bundle.** Deploying code alone
does NOT show a new strategy-testing control, persistent prospective journal,
live Saxo prices, paper fills or verified P&L in the Shadow Lab UI.

## Required acceptance to call Shadow Lab operational
1. Independent ThetaData timestamp live probe and source precision verification,
   or candidate source explicitly not eligible.
2. Predeclared candidate risk plans (entry, maximum loss, exit, event rules,
   size, fees, FX, tax); no retroactive plan on old candidates.
3. Gated production journal migration and append-only attempt/NO TRADE source
   path, with provider entitlement and request-budget evidence.
4. Actual broker-native multi-leg executable package entry and exit quality or
   independently authenticated paper fill receipts; no fills inferred from
   per-leg prices, no positive expectancy from stale quotes.
5. Streamlit Shadow Lab / Decision Desk visibly distinguishes opportunity
   population, source quality, rejects, NO TRADE, paper stress and validated
   outcome. Show precise Brussels-local dates and research coverage.
6. Forward holdout strategy comparison with realistic net EUR costs, controls,
   no survivorship filtering; live bankroll remains capped and isolated.
7. On code activation: exact combined-main CI, Python3.13 Linux lock, same
   schema/WAL, no concurrent job, rollback, enough disk and production read
   models/performance; detached deployment and live verification.
