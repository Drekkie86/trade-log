# Counterfactual Rejection Audit V1

## Status

This programme is **RETROSPECTIVE DISCOVERY — NOT EDGE EVIDENCE**.

Its purpose is to measure what happened to structures that were admitted versus
structures that were rejected only by Christiania's historical EUR-500 wallet
policy, while preserving the exact original decisions and decision-time evidence.

It does **not** turn the historical wallet cap into a trading signal.

## Frozen cohort

The freeze requires the exact pre-label inventory observed through the
2026-09-17 completed research session:

- 149 defined-risk `PROPOSED` structures in total;
- 15 `ADMITTED_AT_TIME`;
- 134 `REJECTED_AT_TIME_WALLET_ONLY`:
  - 133 were blocked by `ACTIVE_PORTFOLIO_EXCEEDS_EUR_500_BANKROLL`;
  - 1 was blocked by `ONE_UNIT_EXCEEDS_EUR_500_BANKROLL`;
- all 134 wallet-only rejects are already present in immutable historical replay
  as `WOULD_ADMIT` after removal of the external bankroll rule;
- the union of the 15 admitted and 134 wallet-rejected structures must equal the
  complete historical `PROPOSED` population exactly.

Membership is immutable after freeze.

The legacy wallet/account state is **cohort provenance only** and is explicitly
forbidden as a predictive feature.

## Decision-time feature contract

For every frozen cohort member, the freeze snapshots only information available
at the original decision time, including:

- V1 local-IV residual and absolute residual;
- delta and implied volatility;
- scanner residual threshold;
- target bid/ask and spread-to-mid;
- structure identity;
- theoretical defined maximum loss;
- estimated cost;
- account-independent intrinsic risk.

Wallet/account balance is not included.

Future information may be used only to label eventual outcome.

## Outcome contract

The only V1 outcome-label source is
`historical_outcome_recovery_v1` with measurement role
`RETROSPECTIVE_EXPIRY_RECONSTRUCTION`.

Allowed descriptive labels are:

- `RETROSPECTIVE_EXPIRY_RECON_NET_POSITIVE`;
- `RETROSPECTIVE_EXPIRY_RECON_NET_ZERO`;
- `RETROSPECTIVE_EXPIRY_RECON_NET_NEGATIVE`.

These labels remain explicitly retrospective and `outcome_eligible=0`.

They are **not** validated package execution P&L and must not be described as
such.

Independent-leg conservative liquidation replay is explicitly excluded as a
winner/loser label.

Missing or unresolved outcomes stay missing. There is no imputation.

## Freeze-time maturity state

At the frozen 2026-09-17 research boundary:

- 6 cohort structures had already expired;
- all 6 were unresolved because
  `MISSING_EXPIRY_SESSION_UNDERLYING_SNAPSHOT`;
- 0 recovered expiry labels existed;
- 143 structures had future expiries and correctly had no recovery record yet.

The first future expiries include five original admitted structures expiring on
2026-09-18. The frozen cohort maximum expiry is 2026-10-30.

## No intermediate outcome peeking

The programme deliberately does not run rolling winner/loser checkpoints.

The final descriptive audit may run only when the latest completed Christiania
research session is **strictly later than the maximum frozen cohort expiration**.

This prevents rule tuning while outcome labels arrive.

Unresolved outcomes at the final trigger remain unresolved and are reported
explicitly.

## Frozen descriptive metrics

The primary descriptive economic quantity is:

`estimated_net_pnl_usd_minor / frozen_intrinsic_risk_usd_minor`

reported separately for admitted-at-time and wallet-rejected-at-time cohorts.

Secondary descriptors are:

- raw reconstructed estimated net P&L in USD minor units;
- three-way positive / zero / negative outcome counts;
- the symmetric positive versus non-positive 2x2 count table;
- recovery and missingness counts.

No p-values, FDR, model training, admission changes, automatic rule selection,
or trading authority are enabled.

## Rejection stages not included in V1

Two larger rejected populations remain deliberately outside this programme:

- scanner observations that were not surfaced;
- surfaced anomalies that the structure builder blocked.

Those populations do not have the same frozen executable multi-leg structure as
the admitted cohort. They require a separate counterfactual-expression protocol
before any payoff comparison would be scientifically symmetric.

V1 does not manufacture structures for them after seeing future outcomes.

## Scientific interpretation

This audit can reveal whether the historical external wallet gate materially
changed which already-constructed structures entered the original shadow cohort.

It cannot prove:

- that wallet rejection is predictive;
- that the historical scanner has positive expectancy;
- that expiry reconstruction is executable economic P&L;
- that any discovered subgroup is a trading edge.

Any candidate rule suggested by this retrospective audit must be frozen
separately and survive fresh prospective evidence before it can influence
Christiania's scientific decision process.
