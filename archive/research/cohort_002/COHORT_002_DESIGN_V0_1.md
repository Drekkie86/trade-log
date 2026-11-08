# Christiania — Cohort 002 Design v0.1

Status: design draft — **not preregistered**  
Dependency: Cohort 001 completes or is formally diagnosed first  
Purpose: estimate the empirical dependence and cost parameters required by the detectability harness.

## 1. Primary question

Cohort 002 is not primarily an edge test.

It asks:

> How much statistically independent information does Christiania actually gain by observing more contracts, more underlyings, and more market days?

The most consequential unknown is the correlation of **paired edge observations across underlyings on the same day**.

## 2. Why this matters

The detectability harness showed two very different possible worlds:

- if cross-underlying paired-edge correlation is low, breadth can materially increase effective N;
- if it is high, scanning more names mostly adds nominal observations and multiple-testing exposure rather than real information.

Cohort 002 should estimate which regime Christiania is closer to.

## 3. Proposed initial breadth

Start deliberately small:

- 3 underlyings;
- selected to be liquid;
- preferably from meaningfully different economic / sector exposures;
- same collection session;
- same collection rules and timestamp discipline.

Do not jump immediately to a 20- or 100-name scanner.

The first purpose is measurement of dependence, not maximum coverage.

## 4. Required paired observation concept

For a later candidate/control experiment:

`paired_edge_ru = candidate_net_pnl / candidate_max_risk - control_net_pnl / control_max_risk`

For Cohort 002 itself, the system must at minimum preserve enough frozen observations to compute that quantity later at a prespecified horizon.

Every candidate/control pair must be identifiable as belonging to:

- one market session-day;
- one underlying;
- one snapshot;
- one rule family;
- one outcome horizon;
- one candidate;
- one matched control.

## 5. Empirical parameters Cohort 002 should make estimable

### 5.1 Within-underlying dependence

Estimate dependence among paired observations from the same underlying and session-day.

Target output:

- intraclass-style correlation or equivalent variance decomposition;
- variance of the underlying-day mean;
- marginal gain in effective N from 1, 2, 5, 10+ pairs within one underlying-day cluster.

### 5.2 Cross-underlying paired-edge correlation

This is the key addition.

For each session-day, compute an underlying-level paired-edge summary and estimate the cross-underlying dependence structure.

Do not substitute correlation of raw stock returns.

The quantity of interest is correlation of **paired edge**, because candidate-minus-control differencing may remove common return factors while leaving common volatility / regime factors.

### 5.3 Day-to-day persistence

Estimate serial dependence of the daily paired-edge summary.

The current synthetic harness uses an AR(1)-style persistence parameter only as a stress-test assumption. Empirical data should replace it.

### 5.4 Heavy-tail / noise scale

Estimate:

- marginal dispersion of paired edge;
- robust scale;
- tail heaviness;
- frequency and magnitude of extreme observations.

Do not force a Student-t model merely because the current simulator uses one.

### 5.5 Costs

Persist separately:

- commission / fees;
- spread paid;
- estimated or observed slippage;
- any tax or transaction levy applicable to the structure;
- total cost in EUR;
- total cost in risk units.

Candidate and control costs must both be represented.

The detectability harness needs a distribution, not only an average.

## 6. Underlying selection principle

The initial three names should maximize **informational contrast**, subject to liquidity and provider quality.

Good selection dimensions include:

- different sectors;
- different volatility regimes;
- different typical option liquidity;
- no deliberate event concentration unless event/non-event is a prespecified dimension.

Do not cherry-pick names because recent backtests look attractive.

## 7. Snapshot synchronization

Cross-underlying dependence is meaningful only when observations belong to comparable market states.

Persist:

- provider observation timestamp;
- normalized Christiania timestamp;
- market-state classification;
- quote-quality classification;
- age / staleness metadata where available.

If one underlying is observed materially later than another, preserve that fact.

## 8. Outcome horizon

Before Cohort 002 becomes a real experiment, freeze one or a small number of outcome horizons.

Avoid selecting the best-looking horizon after observing results.

Possible future examples:

- fixed calendar horizon;
- fixed trading-day horizon;
- option-expiry outcome;
- structure-specific terminal payoff.

The final choice belongs in the preregistration, not this design draft.

## 9. Multiple testing discipline

Cohort 002 should not become a broad hunt across many edge rules.

If multiple rule families are evaluated:

- register the family count;
- preserve all evaluations, not only winners;
- use FDR in discovery;
- reserve later time periods for confirmation.

Breadth of underlyings and breadth of hypotheses are different things.

## 10. Effective-N output

The eventual Cohort 002 analysis should report:

- nominal N;
- number of session-days;
- number of underlying-days;
- number of pairs;
- within-underlying dependence;
- cross-underlying paired-edge correlation;
- serial dependence;
- effective N;
- efficiency = effective N / nominal N.

The most important chart/table is an empirical version of the current synthetic
`underlyings_per_day × cross_underlying_edge_corr` surface.

## 11. What Cohort 002 must not claim

Until an edge family is separately preregistered and tested, Cohort 002 must not claim:

- profitable strategy;
- validated edge;
- expected return;
- Sharpe ratio;
- live fill quality from indicative quotes;
- superiority of a model family.

Its first job is to tell Christiania how much information its data actually contains.

## 12. Exit criterion for design phase

Before implementation, freeze:

1. exact underlyings;
2. exact collection cadence;
3. exact candidate/control matching definition;
4. exact outcome horizon;
5. exact cost fields and cost semantics;
6. exact dependence estimators;
7. minimum number of session-days before any inference;
8. discovery / confirmation boundary.

Only then should Cohort 002 be preregistered and coded.
