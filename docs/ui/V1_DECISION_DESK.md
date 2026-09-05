# Christiania V1 Decision Desk

The Decision Desk is the candidate-level synthesis surface for Christiania V1. It is designed to answer one operational research question without weakening governance: **given everything currently stored about a candidate, is there any reason it should progress beyond shadow research?**

The first valid conclusion is always `NO TRADE`.

## Inputs brought together

For one selected shadow candidate the desk presents:

- exact backend hypothesis and scanner identity;
- surfaced IV residual and persisted threshold;
- exact multi-leg shadow structure and conservative inception prices;
- shadow admission decision, reserved EUR risk and cost estimate;
- subsequent shadow marks and validated-outcome count;
- settlement and exercise-style gate;
- explicit session risk/stop controls;
- stored spot, IV, rate, dividend-yield and contract-multiplier inputs;
- full research-only model suite, aggregated to the actual multi-leg structure;
- aggregated structure Greeks;
- explicit blockers and final disposition.

## Settlement gate

Christiania V1 fails closed. No contract is assumed to be cash-settled from its ticker, exchange, exercise style or option category alone.

Initial explicit product allow-list:

- `SPX` — Cboe S&P 500 Index options; cash-settled, European exercise.
- `XSP` — Cboe Mini-SPX Index options; cash-settled, European exercise.

Product facts were verified against Cboe product documentation on 2026-09-05. Unknown products and metadata conflicts are blocking until deliberately reviewed and added to policy.

This is intentionally stricter than the research scanner universe. Christiania may continue to study physically settled equity/ETF options, while the Decision Desk refuses to progress them to live/manual-review eligibility.

## Risk and stop controls

The active bankroll cap remains EUR 500. The Decision Desk adds two explicit session controls:

1. maximum loss budget per trade;
2. planned loss trigger as a fraction of reserved defined risk.

Zero means unconfigured and blocks progression. The trigger is a monitoring threshold, **not a guaranteed execution price**. Defined-risk maximum theoretical loss remains the primary protection.

The persisted scanner residual threshold is also surfaced as a thesis-invalidation reference. Christiania does not yet submit or manage exit orders.

## Quantitative dossier

Only the selected candidate runs the full model suite. Christiania does not run expensive models for every board row during navigation.

For each persisted structure leg the desk requires stored:

- spot;
- strike;
- IV;
- rate;
- dividend yield;
- entry price;
- contract multiplier;
- expiration date.

If any required input is absent, the model dossier fails closed instead of substituting a default.

Model prices are aggregated using the persisted long/short quantities and contract multiplier. The desk shows model consensus and model range, but explicitly labels probability-weighted EV as `NOT CALIBRATED FOR DECISION USE`.

## Research rank

Research rank is not a recommendation score. It is a deterministic review order using existing evidence: verified cash-settlement status, shadow admission, model-input completeness, validated outcome count, mark count, anomaly magnitude and recency/candidate identity.

A candidate can rank first and still have the final disposition `NO TRADE`.

## Governance

A candidate cannot clear the Decision Desk while scientific decision governance remains disabled. No UI interaction changes database evidence, enables a model, promotes a hypothesis or creates a broker order path.

## Package 11 — Decision Desk V2 synthesis

Decision Desk V2 keeps the Package 10 safety dossier and adds candidate-specific synthesis. No global enabled model or unrelated hypothesis can grant permission to a candidate. `LOCAL_IV_RESIDUAL_V1` resolves explicitly to the frozen local-surface governance family; unknown scanner families fail closed.

Manual-review eligibility now requires all of the following to be true at the same time: exact cash-settlement policy plus persisted contract identity/multiplier, admitted shadow state, explicit bounded risk controls, candidate-specific governance permission, fresh/tight quote quality, clean collection state, exact expiration timestamp semantics, integrated event-risk context, and calibrated net EV. Missing evidence is a blocker rather than a guessed default.

The current system intentionally cannot satisfy every manual-review gate. Exact expiration timestamps, event/jump calendar integration, calibrated probability-weighted net EV, and live-probed SPX/XSP provider compatibility remain explicit gaps. The expected V1 result is therefore often `NO TRADE` or `CONTINUE SHADOW`.

The model dossier no longer presents an indiscriminate arithmetic consensus. BSM/CRR/finite-difference/GBM Monte Carlo are benchmark diagnostics; Heston and Merton are uncalibrated stress models unless calibrated parameters are explicitly supplied. Scenario rows are deterministic stress cases with no probabilities and therefore are not expected value.

The cash-settled research universe is explicitly SPX/XSP, but live collection is not enabled until provider compatibility is actually probed end to end. Existing equity/ETF candidates remain valid shadow research while being blocked from live/manual eligibility because of physical-delivery/assignment risk.
