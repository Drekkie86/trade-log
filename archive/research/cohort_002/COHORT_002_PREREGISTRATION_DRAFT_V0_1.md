# Christiania — Cohort 002 Preregistration Draft v0.1

Status: DRAFT — not yet frozen / not yet launch-authoritative  
Purpose: empirical dependence and cost-measurement cohort  
Cohort 001: unchanged and independent

## 1. Scientific purpose

Cohort 002 is a measurement cohort, not an edge experiment.

Primary question:

> How much statistically independent information does Christiania gain from
> multiple option pairs, multiple underlyings, and repeated market days?

The key target is the same-day cross-underlying correlation of **paired option
outcomes after within-underlying matching**, not the correlation of raw stock
returns.

No profitability, Sharpe, win-rate, or validated-edge claim is permitted from
this cohort.

## 2. Underlyings

Frozen design trio:

- AAPL
- XOM
- JPM

All three passed the read-only Massive/Saxo provider seam validation before
this draft was prepared.

Replacement is allowed only before formal preregistration for a documented
operational/data-quality reason. A symbol may not be replaced because another
symbol produces a more attractive historical result.

## 3. Observation schedule

### Primary session unit

US regular-session trading day.

### Target collection time

One synchronized collection batch per eligible trading day.

Target batch start:
**13:30 America/New_York**

Operational tolerance:
**13:25–13:45 America/New_York**

All three underlyings must be collected in one batch. The batch stores the
actual provider timestamps and the collection sequence.

Reason:
This is well clear of the opening and closing auctions while remaining
operationally practical from Belgium.

No second same-day batch may be substituted merely because the first batch
looks unusual.

## 4. Chain universe

For each underlying:

- complete Massive option chain required;
- 7–45 calendar DTE;
- CALL and PUT;
- normalized observations retained;
- exclusion reasons retained;
- no silent survivor-only universe.

DTE bins:

- 7–14
- 15–30
- 31–45

Absolute-delta bins:

- [0.10, 0.20)
- [0.20, 0.35)
- [0.35, 0.50)
- [0.50, 0.65)
- [0.65, 0.80]

Final upper boundary 0.80 is inclusive.

CALL / PUT × 3 DTE bins × 5 delta bins = 30 potential strata per underlying.

## 5. Null measurement pairs

Cohort 002 does not embed an edge thesis.

Instead it creates **null measurement pairs** within each underlying-day.

### 5.1 Eligible stratum

A stratum must contain at least two contracts that pass the frozen data-quality
eligibility rules.

### 5.2 Number of pairs

Target:
**5 null measurement pairs per underlying per trading day.**

If fewer than five strata contain at least two eligible contracts, retain all
available pairs and persist the shortfall. Do not replace missing pairs using a
different rule.

### 5.3 Stratum selection

Select up to five eligible strata using a deterministic pseudorandom ordering
derived only from:

- cohort identifier;
- trading date;
- underlying symbol;
- immutable stratum identifier.

No price outcome or future information may enter the ordering.

The seed material must be persisted so selection is exactly reproducible.

### 5.4 Contract A

Within the selected stratum, rank contracts using the Cohort 001-style
distance/tie-break discipline:

1. absolute distance to delta-bin midpoint;
2. earlier expiry;
3. lower strike;
4. lexical option symbol;
5. immutable quote id.

The first contract becomes Contract A.

### 5.5 Contract B

Contract B is the nearest remaining contract to Contract A using:

1. same expiry preferred;
2. smallest absolute delta difference;
3. smallest strike difference;
4. lexical option symbol;
5. immutable quote id.

Contract B must be distinct from Contract A.

### 5.6 Label symmetry

The scientific estimand is A minus B.

Because the pair is deliberately not an edge signal, the deterministic
assignment must not be interpreted as a directional recommendation.

A sensitivity analysis may also report the sign-reversed B-minus-A
distribution to verify that no accidental labeling asymmetry drives results.

## 6. Outcome horizon

Primary outcome horizon:

**next eligible US trading day, same target collection window.**

This is a one-trading-day horizon.

Reason:

- keeps even the shortest 7–14 DTE contracts within a comparable horizon;
- produces repeated daily dependence observations;
- avoids mixing expiry mechanics into the primary dependence estimate;
- minimizes post-hoc horizon selection.

Longer horizons may be explored only in a separately versioned analysis and
must not replace the primary horizon after results are visible.

## 7. Outcome valuation

Persist two distinct outcome views.

### 7.1 Gross mark-to-mid outcome

Entry reference:
frozen entry mid.

Exit reference:
next-day frozen exit mid.

Purpose:
estimate market-outcome dependence without mechanically folding quoted spread
into the response.

### 7.2 Paper executable-cost outcome

For a hypothetical long option:

- entry at frozen ask;
- exit at next-day frozen bid;
- plus explicit commission/fees assumptions.

If a quote side is absent, mark the paper-executable outcome unavailable;
do not synthesize a bid or ask.

Actual real fills, if they later exist, are stored separately and may not be
silently substituted for paper assumptions.

## 8. Risk normalization

For a hypothetical long option:

`max_risk_eur = entry_ask * contract_multiplier + entry_costs`

Primary risk-unit return:

`net_pnl_ru = net_pnl_eur / max_risk_eur`

Primary paired-edge-style measurement:

`paired_edge_ru = A_net_pnl_ru - B_net_pnl_ru`

Undefined-risk structures are outside this cohort.

## 9. Cost fields

Persist separately wherever available:

- entry bid;
- entry ask;
- entry mid;
- exit bid;
- exit ask;
- exit mid;
- quoted entry half-spread;
- quoted exit half-spread;
- contract multiplier;
- commission assumption;
- other fee/levy assumption;
- total paper round-trip cost EUR;
- total paper round-trip cost RU;
- actual fill price if a real trade exists;
- actual commission/fees;
- actual slippage versus frozen reference.

Cost provenance must state whether a value is:

- QUOTED
- ASSUMED
- ACTUAL_FILL

## 10. Primary empirical outputs

After the minimum observation requirement is met, estimate:

1. within-underlying same-day dependence;
2. cross-underlying correlation of daily paired-edge summaries;
3. day-to-day serial dependence;
4. pair-level and cluster-level noise scale;
5. robust empirical tail diagnostics;
6. paper cost distribution;
7. nominal N;
8. effective N;
9. efficiency = effective N / nominal N.

Do not substitute raw stock-return correlation for paired-edge correlation.

## 11. Dependence estimators

Primary daily underlying summary:

mean paired_edge_ru across available pairs for that underlying-day.

Primary cross-underlying estimator:

Pearson correlation matrix of the three daily underlying summaries using only
days where both members of a pair are observed.

Robust sensitivity:

Spearman correlation matrix.

Primary serial-dependence estimator:

lag-1 autocorrelation of the equal-weight mean across available underlying-day
summaries.

Within-underlying dependence:

variance-ratio / intracluster-style estimate comparing pair-level variance with
variance of the underlying-day mean.

Uncertainty:

block bootstrap by trading day, with the block-length rule used by the
detectability harness unless superseded by a separately versioned empirical
calibration.

## 12. Minimum sample requirement

Interim descriptive reports are permitted at:

- 20 session-days;
- 40 session-days.

No synthetic detectability parameter may be promoted to
`EMPIRICAL_COHORT_002` before:

**60 eligible session-days**

and at least:

- 50 paired-edge daily summaries for AAPL;
- 50 for XOM;
- 50 for JPM;
- 45 same-day observations for each underlying pair.

If these completeness gates are not met, the cohort remains
`INSUFFICIENT EMPIRICAL COVERAGE`.

## 13. Missingness

Missing contracts, failed provider calls, unavailable bid/ask sides and
unresolved Saxo mappings remain explicit.

Do not impute an outcome merely to preserve a balanced panel.

The analysis must report missingness by:

- day;
- underlying;
- stratum;
- provider;
- failure category.

## 14. Multiple testing / discovery boundary

Cohort 002 contains **no edge-rule discovery family**.

For profitability/edge hypotheses:

`k = 0` in this cohort.

Any later candidate-rule discovery belongs in a separate preregistered cohort
or experiment with its own multiplicity control and temporal confirmation set.

This prevents the dependence-measurement dataset from quietly becoming a
strategy-mining dataset.

## 15. Empirical parameter provenance

If the completeness gates are satisfied, the detectability harness may consume
Cohort 002 estimates using:

`PARAMETERS_SOURCE=EMPIRICAL_COHORT_002`

The report must also include:

- exact date range;
- eligible session-days;
- underlying-days;
- total pairs;
- missingness;
- estimator version;
- cost-source version.

The detectability harness must still run its own null calibration and report
empirical FPR.

## 16. Non-claims

Cohort 002 cannot establish:

- positive expected value;
- a profitable strategy;
- a sustainable win rate;
- a Sharpe ratio;
- model superiority;
- executable Saxo fill quality from stale or indicative quotes.

Its purpose is to measure the information structure Christiania must work with.

## 17. Relationship to Cohort 001

Cohort 001 remains the first official data-quality baseline.

Cohort 002 must not delay, modify, or reinterpret Cohort 001.
