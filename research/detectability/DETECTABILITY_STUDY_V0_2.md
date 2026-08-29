# Christiania Detectability Study v0.2

## Status

**Synthetic planning harness only. Not an empirical edge estimate and not an empirical MDE estimate.**

Every report prints `PARAMETERS_SOURCE` and `COST_PARAMETERS_SOURCE`. Until these point to empirical Christiania cohorts, all power, cost, multiplicity, and effective-N outputs answer conditional *what-if* questions only.

## Pass 1 — inference repair

v0.1 used the lower bound of a percentile moving-block bootstrap confidence interval as if it had nominal coverage. Under heavy tails and dependence, the null false-positive rate was materially too high, especially at short horizons.

v0.2 therefore:

- uses an adaptive moving-block length `max(2, round(days ** (1/3)))`;
- retains the bootstrap lower-bound only as a test statistic;
- calibrates its critical value empirically under a simulated null;
- validates the false-positive rate on a disjoint null seed stream;
- reports empirical FPR as a first-class output.

The 20-day fixed-seed calibration test is a regression guard against the v0.1 failure.

## Pass 2 — economics, multiplicity and breadth

### Costs

`effect_ru` is now explicitly a **gross injected paired edge**. The simulator subtracts a non-negative stochastic incremental cost draw:

`observed paired edge = gross effect - incremental cost + dependent noise`

The default remains zero cost and is labeled `SYNTHETIC_NONE`. Cost scenarios must carry their own provenance. This is not yet a claim about Saxo commissions, spread capture, Belgian TOB, or any other empirical trading cost.

### Multiple testing

Discovery experiments can test `discovery_hypotheses_k` families. One family receives the injected effect and the remaining families are null. Empirical p-values come from the calibrated null statistic distribution and Benjamini-Hochberg is applied at `fdr_q`.

This keeps pre-specified confirmation power conceptually separate from discovery power under multiplicity.

### Cross-underlying breadth

The simulator now has:

- `underlyings_per_day`
- `cross_underlying_edge_corr`

The latter is deliberately the correlation of **paired candidate-minus-control edge**, not raw returns. This matters because matched differencing may remove common market movement while leaving, or not leaving, common strategy/regime effects.

The real value is unknown. Cohort 002 should include multiple underlyings specifically so Christiania can estimate cross-underlying paired-edge dependence empirically.

### Effective N

The study reports an iid-equivalent sample size by variance ratio:

`N_eff = marginal variance of one paired observation / variance of the grand mean`

Nominal N is:

`days × underlyings × pairs_per_underlying_day`

The ratio `N_eff / nominal_N` makes dependence loss visible. It is a planning diagnostic, not a substitute for clustered inference in a real experiment.

## Interpretation guard

No conclusion of the form **“Christiania can detect an edge of X RU”** may be drawn while the following are synthetic:

- idiosyncratic scale;
- common/regime scale;
- within-underlying same-day correlation;
- cross-underlying paired-edge correlation;
- temporal dependence;
- tail index;
- incremental cost distribution.

A calibrated harness can still return an economically unfavorable answer once empirical parameters arrive. That is a successful outcome if it accurately shows that a plausible edge is not distinguishable from noise at Christiania's scale.

## Cohort sequencing

Detectability work must not delay Cohort 001. Cohort 001 remains a data-quality baseline and has no dependency on this module.

Cohort 002 should be designed to collect enough multi-underlying paired observations to estimate the dependence and cost inputs required here.
