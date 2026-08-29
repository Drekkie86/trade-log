# Christiania — ThetaData empirical diagnostics v2

v1 revealed that the broad option universe is dominated by structurally
important zero-bid / wide-spread observations.

A spread/mid ratio of exactly 2.0 occurs when bid = 0 and ask > 0:

`(ask - 0) / ((ask + 0) / 2) = 2`

Therefore the p75/p90/p95 values of exactly 2.0 in v1 are not a numerical
curiosity. They show that a large fraction of the measurement universe has no
displayed bid.

v2 does not filter those rows away.

Instead it reports the same economic quantities by explicit quote-state,
premium and DTE strata, and provides robustness views for positive-bid and
tighter-spread populations.

This implements the measurement-universe / executable-universe distinction:
all observations remain measurable, while execution realism is analysed as a
separate dimension.

Cross-underlying statistics remain exploratory and are NOT Cohort 002 paired
edge correlations.
