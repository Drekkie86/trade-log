# Christiania — Edge Discovery Protocol v1.1

Status: DESIGN FREEZE CANDIDATE — effective only once committed and blob-hashed.

Purpose: define how Christiania may move from an observed market pattern to a
candidate edge claim without confusing in-sample pattern discovery with
validated positive expectancy.

## 1. Core principle

Christiania must distinguish:

1. IDEA
2. SETUP
3. CONTEXT
4. TRADABILITY
5. EMPIRICAL FINDING
6. CANDIDATE EDGE
7. VALIDATED EDGE
8. HARVESTABLE EDGE AT CURRENT SCALE

Only stage 7 may be described as a validated statistical edge. Only stage 8
may be described as harvestable at Christiania's current account scale.

A candidate may be economically interesting before it is validated, but the UI
and research artefacts must say so explicitly.

## 2. The Edge Statement

Every candidate edge family must have an Edge Statement created before
confirmation begins.

Template:

> For [eligible population], when [predefined conditions] hold, taking
> [predefined trade/structure] at [predefined entry convention] and exiting at
> [predefined horizon/exit convention] is expected to produce positive
> [predefined net expectancy metric] after [predefined costs], relative to
> [predefined control/comparator].

The statement must be frozen with all logic filled in except the future result.

The Edge Statement is not evidence. It is a preregistered claim to be tested.
A preregistration is not frozen merely because a JSON field says so. It becomes
frozen only when committed and identified by an immutable Git blob/hash. A
result must live in a separate artefact that references that preregistration.

## 3. Discovery and confirmation are separate datasets

Discovery data may be used to:

- generate candidate features;
- estimate rough effect sizes;
- identify plausible regimes;
- design a candidate rule;
- estimate required sample size;
- reject obviously uneconomic ideas.

Discovery data may NOT be used to confirm the rule that it created.

Confirmation must use observations not used to choose:

- thresholds;
- features;
- payoff structure;
- DTE band;
- premium band;
- liquidity condition;
- underlying family;
- exit rule;
- direction;
- statistical test;
- dependence estimator;
- independence unit.

Every discovery window must be recorded in
`research/edge_discovery/DISCOVERY_WINDOW_REGISTRY.json` before any
confirmation preregistration is accepted. August 2026 ThetaData AAPL/XOM/JPM
is discovery data and is permanently burned for confirmation.

Any non-mechanical access to a candidate holdout window contaminates that
window for confirmation and must be recorded in
`research/edge_discovery/HOLDOUT_ACCESS_REGISTRY.json`.

Temporal split is preferred for market data.

## 4. Multiplicity is first-class evidence

Every discovery exercise must declare a hypothesis family.

For each family record:

- family_id;
- description;
- eligible population;
- candidate features searched;
- thresholds searched;
- structures searched;
- horizons searched;
- number of hypotheses/tests;
- selection statistic;
- multiplicity correction;
- number surfaced;
- confirmation status.

A rule found after searching 100 variants is not evaluated as though it was the
only rule considered.

Christiania **must** use multiplicity control for discovery. Confirmation must
use either a preregistered single-hypothesis test or a preregistered family-wise
or false-discovery procedure appropriate to the declared family.

`hypothesis_count` is not trusted as a hand-entered number. Every evaluated
variant must be logged in the hypothesis evaluation log and the count used for
validation must be derived from that log.

Family-level error control is not enough. Before any scanner/discovery family
is activated, a programme-level family budget for the research period must be
frozen. If the budget is exhausted, the result is `INSUFFICIENT EVIDENCE`; the
programme may collect more data but may not silently open another family.

## 5. Measurement universe is not executable universe

Do not let a bankroll or liquidity filter silently rewrite the data-generating
population.

Each observation should be classified separately along these axes:

### Observation status

- OBSERVATION_FATAL
- FEATURE_LIMITATION
- TRADABILITY
- ECONOMIC

### Tradability features

Examples:

- bid > 0;
- ask > 0;
- absolute spread;
- spread / ask;
- spread / mid;
- quote size;
- premium;
- DTE;
- moneyness;
- quoted same-session crossing penalty;
- historical next-session outcome;
- broker availability;
- account affordability;
- defined-risk max loss.

These are measured economic variables.

They may become preregistered candidate conditions later, but must not be
quietly discarded during data collection merely because they make a trade look
bad.

## 6. Costs are part of the hypothesis

A gross edge is not a trading edge.

Every candidate must specify cost provenance:

- QUOTED
- ASSUMED
- ACTUAL_FILL

At minimum report:

- gross expectancy;
- quoted same-session crossing penalty;
- commissions/fees;
- modeled slippage if applicable;
- net expectancy;
- sensitivity to worse fills.

Do not call an ask-at-entry to bid-at-next-session return a transaction-cost
estimate. It contains option price movement, theta, volatility changes and
underlying movement. It is a holding-period outcome under an executable quote
convention, not pure crossing cost.

## 7. Controls and comparator

Every candidate edge should have a comparator where possible.

Examples:

- matched contract/control;
- matched stratum;
- same underlying / nearby strike;
- random eligible contract;
- synthetic null;
- do-nothing cash baseline;
- alternative structure expressing the same thesis.

The comparator must be defined before confirmation.

## 8. Confirmation result vocabulary

Allowed:

- VALIDATED POSITIVE EDGE
- NO DETECTABLE EDGE
- INSUFFICIENT EVIDENCE
- ECONOMICALLY NEGATIVE AFTER COSTS
- NOT HARVESTABLE AT CURRENT SCALE
- DATA QUALITY FAILURE
- MODEL DEPENDENT / NOT ROBUST
- DECAYED / REVALIDATION REQUIRED

Avoid:

- "works"
- "profitable strategy"
- "high conviction"
- "edge found"

unless the corresponding statistical and economic requirements are met.

## 9. Edge decay and persistence

A validated edge is not permanent.

Track:

- rolling expectancy;
- confidence/credible interval;
- fill quality drift;
- spread drift;
- regime dependence;
- effect-size decay;
- calibration drift;
- sample count since validation.

If a predefined persistence/decay condition fails, the edge is demoted to
`DECAYED / REVALIDATION REQUIRED`. It cannot remain labelled validated merely
because it was validated historically.

Decay monitoring is diagnostic. It should not become a new unregistered search
for replacement thresholds.

## 10. Process quality is separate from economic edge

Good execution discipline can preserve an edge but does not create one.

Christiania should score process quality separately from edge quality.

Process examples:

- followed entry rule;
- respected max loss;
- used required order type;
- no discretionary override;
- data complete;
- model version frozen.

Economic edge remains a probability-weighted net-return property.

## 11. Speculation Mode

Speculation Mode remains distinct.

It may use:

- hard capped max loss;
- scenario analysis;
- P(breakeven);
- P(2x), P(5x), P(10x), when defensible;
- catalyst timing;
- liquidity;
- hostile case;
- model disagreement.

It must display:

SPECULATION — NO VALIDATED EDGE CLAIM

Speculation outcomes must not be pooled into validated-edge performance.

## 12. Promotion ladder

An empirical pattern can only be promoted as follows:

OBSERVATION
-> EMPIRICAL FINDING
-> PREREGISTERED CANDIDATE
-> OUT-OF-SAMPLE CONFIRMATION
-> ECONOMIC ROBUSTNESS
-> VALIDATED EDGE
-> LIVE/PAPER HARVESTABILITY CHECK
-> HARVESTABLE EDGE AT CURRENT SCALE

A live trade is not required to validate statistical existence of an edge, but
actual fills are required to validate harvestability at Christiania's scale.

## 13. Current ThetaData finding classification and retractions

Current status:

EMPIRICAL FINDING — DISCOVERY DATA ONLY

The August 2026 AAPL/XOM/JPM ThetaData staging window is registered discovery
data. It may not be reused for confirmation.

Findings that survive review:

- the Massive <-> ThetaData contract-identity seam matched cleanly for the
  tested non-expired AAPL/XOM/JPM contracts;
- the ThetaData-native staging population contains a substantial zero-bid mass;
- quoted spread quality varies materially across the full listed chain;
- pooled chain statistics are strongly affected by quote state, premium and
  moneyness and therefore must not be presented without conditioning.

Retired v1/v2 interpretations:

- the cheap-option ask-to-next-bid bucket results are not evidence of pure
  execution cost; the old matcher mixed held-to-expiry outcomes with surviving
  next-session observations;
- the v2 near-zero median-based cross-underlying dependence estimate is
  withdrawn. Mean and median estimators disagree and the available n is too
  small to identify dependence reliably;
- no pooled full-strike-ladder percentile may be used as an executable-universe
  estimate without moneyness stratification.

Diagnostics v3 must separate held-to-expiry, calendar-span, moneyness, quoted
crossing and next-session outcome estimands before any descriptive number is
reused.

None of these findings is evidence of a trading edge.

## 14. Cohort 001 precedence

Cohort 001 remains the frozen data-quality baseline scheduled for Monday
2026-08-31. Research refactors, ThetaData diagnostics, Cohort 002 work and
scanner work must not weaken, rewrite or silently displace its preregistered
launcher or protocol.
