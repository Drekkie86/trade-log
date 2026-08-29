# Christiania — Cohort 002 Design v0.2

Status: implementation-ready design draft — not yet preregistered  
Cohort 001: unchanged and independent

## Exact initial underlyings

1. `AAPL` — continuity with Cohort 001 / large-cap technology
2. `XOM` — energy exposure
3. `JPM` — financial exposure

The purpose of this trio is not to maximize expected edge. It is to create a
small, liquid, economically differentiated cross-section for measuring how
paired-edge observations co-move across underlyings.

No underlying may be substituted after outcome data are observed merely because
another name produces a more attractive result.

Before preregistration, all three must pass the read-only provider seam check:
Massive complete chain retrieval, Saxo primary underlying resolution, and at
least one Massive-to-Saxo option-contract bridge.

## Collection structure

### Session unit

Primary dependence unit: US regular-session trading day.

### Collection window

Collect during the same stable intraday window for all three underlyings.

The exact clock-time window must be frozen in the Cohort 002 preregistration.
Do not collect one name at the open and another near the close.

### Universe

For every underlying:

- option expiries 7–45 DTE;
- calls and puts;
- complete Massive chain required;
- preserve every normalized option observation;
- preserve exclusions rather than silently dropping them.

### Sampling

Use the same delta/DTE stratification concept across all three names so the
cross-underlying comparison is not driven by different sampling rules.

Initial design target:

- DTE bins: 7–14, 15–30, 31–45
- absolute-delta bins: .10–.20, .20–.35, .35–.50, .50–.65, .65–.80
- CALL / PUT

This creates the same 30 potential strata per underlying.

The final Cohort 002 preregistration must state whether one primary contract or
candidate/control pairs are selected per stratum. Do not decide this after
seeing results.

## Candidate/control requirement

Cohort 002 exists to estimate the information content of paired edge.

The final experiment therefore needs a frozen candidate/control rule.

Required identity fields:

- session day
- underlying
- snapshot id
- rule-family id
- candidate id
- matched-control id
- outcome horizon
- max risk for each structure
- cost source

Primary later estimand:

`paired_edge_ru = candidate_net_pnl / candidate_max_risk - control_net_pnl / control_max_risk`

Undefined-risk structures are excluded from this primary estimand.

## Outcomes

Outcome horizon must be preregistered before Cohort 002 launches.

The analysis must retain enough raw outcome information to recalculate:

- terminal candidate PnL
- terminal control PnL
- cost-adjusted PnL
- risk-unit PnL
- paired edge RU

No best-looking horizon selection after the fact.

## Empirical parameters to estimate

Cohort 002 should feed the detectability harness with:

1. within-underlying paired-edge dependence;
2. cross-underlying paired-edge correlation;
3. day-to-day persistence;
4. empirical noise scale;
5. empirical tail behaviour;
6. candidate/control cost distributions;
7. nominal N and effective N.

The key quantity is correlation of paired edge, not correlation of raw stock
returns.

## Effective-N analysis

Report at minimum:

- session-days
- underlying-days
- total pairs
- nominal N
- within-underlying dependence
- cross-underlying paired-edge correlation
- serial dependence
- effective N
- efficiency = effective N / nominal N

The eventual empirical surface should mirror the synthetic
`underlyings_per_day × cross_underlying_edge_corr` surface.

## Multiple testing

Breadth of underlyings is not breadth of hypotheses.

If multiple rule families are evaluated:

- register the family count;
- retain every tested family;
- use FDR for discovery;
- reserve later temporal data for confirmation.

## Explicit non-claims

Cohort 002 is not allowed to claim a profitable strategy merely because its
dependence estimates are favourable.

Until a separate edge experiment is preregistered and confirmed, no claims of:

- validated edge
- expected profit
- Sharpe ratio
- sustainable win rate
- model superiority

## Pre-preregistration gates

All must be satisfied before Cohort 002 is frozen:

1. AAPL, XOM and JPM pass provider seam validation.
2. Exact intraday collection window is frozen.
3. Candidate/control matching rule is frozen.
4. Outcome horizon is frozen.
5. Cost semantics are frozen.
6. Dependence estimators are frozen.
7. Minimum session-day count is frozen.
8. Discovery/confirmation boundary is frozen.

Cohort 001 does not depend on any of these gates.
