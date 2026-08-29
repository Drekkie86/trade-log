# Cohort 002 — Freeze Decisions v0.1

These are the design decisions now proposed for freezing before implementation.

## Frozen proposal

- Underlyings: AAPL, XOM, JPM
- One batch per US trading day
- Target start: 13:30 America/New_York
- Tolerance window: 13:25–13:45
- Complete 7–45 DTE Massive chain
- Same 30-stratum DTE/delta/right geometry across all three names
- Five null measurement pairs per underlying-day
- Deterministic, outcome-blind stratum selection
- One-trading-day primary outcome horizon
- Gross outcome: mid-to-mid
- Paper executable-cost outcome: ask-to-bid for hypothetical long option
- Primary normalized measure: paired difference in risk-unit return
- Interim descriptive reports at 20 and 40 days
- Empirical parameter promotion only after 60 eligible session-days and
  completeness gates
- No edge-rule discovery inside Cohort 002
- `PARAMETERS_SOURCE=EMPIRICAL_COHORT_002` only after the promotion gates pass

## Why null measurement pairs

Cohort 002 should measure the dependence structure without smuggling in a
strategy thesis.

Pairing closely matched options within the same underlying-day removes much of
the common level movement. The remaining paired outcome is closer to the
quantity the detectability harness actually needs to understand.

This does not guarantee that a future real candidate/control rule has identical
dependence. It provides the first empirical baseline.

## Why one trading day

A one-day horizon is short enough to remain comparable across the 7–45 DTE
universe and creates repeated daily observations without waiting for expiry.

Longer-horizon behaviour can be studied later under a separate version.

## Why 60 days

Three underlyings produce at most three daily underlying summaries. Correlation
estimates from 20 observations are too unstable for promotion into a serious
detectability model.

Twenty and forty days remain useful diagnostics, but 60 days is the first
promotion gate, not a claim that 60 days is sufficient for every future
question.

## What remains before formal preregistration

Implementation details must still be mapped onto the actual database schema and
runner code.

No code should be made launch-authoritative until:

1. schema/storage impact is reviewed;
2. deterministic selection is tested;
3. outcome collection/reconciliation is tested;
4. full test suite is green;
5. a final preregistration file is hashed and committed.

Cohort 001 is not changed by this document.
