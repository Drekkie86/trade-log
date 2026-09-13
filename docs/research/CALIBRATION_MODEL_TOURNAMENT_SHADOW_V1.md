# Calibration + Model Tournament + Prospective Shadow V1

## Purpose

Package D makes Christiania distinguish between **having a model** and **having earned trust in that model**.

The package is deliberately prospective and review-oriented. It does not promote a model automatically, does not enable p-values/FDR, does not activate a new edge family and does not create broker authority.

## Two probability channels

Christiania keeps these questions separate:

1. `P(thesis correct)` — was the underlying research thesis correct under its frozen definition?
2. `P(trade profitable)` — did the specific structure produce a profitable outcome after the applicable costs/marks?

A profitable trade does not prove the thesis was correct. A correct thesis does not prove the structure was profitable. Package D therefore refuses to pool the two channels.

`src/research/calibration_tournament_v1.py` provides a common probability-observation contract with an explicit `channel` field of `THESIS` or `PROFIT`.

## Calibration metrics

For a model/channel/cohort slice the package computes:

- Brier score;
- log loss;
- mean predicted probability;
- observed event frequency;
- calibration-in-the-large;
- expected calibration error;
- mean absolute calibration gap;
- reliability bins with count, mean probability, observed frequency and gap;
- number of observations;
- number of independent dates.

Calibration is descriptive until sample/date sufficiency is met.

## Paired model tournament

Incumbent/challenger comparisons are paired on the same immutable `observation_key`.

The comparison reports:

- incumbent Brier loss;
- challenger Brier loss;
- challenger-minus-incumbent paired loss difference;
- bootstrap confidence interval for the mean paired difference;
- challenger per-observation win rate;
- paired sample count;
- independent-date count.

The tournament fails closed when outcomes or independent-date identities disagree across the paired models.

A descriptively better challenger is **not** automatically promoted.

## Promotion review gate

`promotion_review(...)` is a review-eligibility gate, not a decision engine.

Default prerequisites are intentionally conservative:

- at least 100 observations;
- at least 20 independent dates;
- Brier score no worse than the configured review ceiling;
- expected calibration error no worse than the configured review ceiling;
- robustness evidence explicitly passed.

The only positive state is:

`ELIGIBLE_FOR_PROMOTION_REVIEW`

and its authority remains:

`NONE_AUTOMATIC_REVIEW_ONLY`

If any prerequisite is missing the state is `CONTINUE_SHADOW` with explicit reasons.

## Read-only prospective/shadow runtime

`src/research/prospective_shadow_runtime_v1.py` summarizes existing Christiania evidence without mutating the live database.

It exposes:

- latest prospective freeze identity and dates;
- number of frozen prospective hypotheses;
- independent prospective dates when the partition view is available;
- p-value/FDR/admission/decision firewall state;
- shadow candidate counts by latest lifecycle state;
- complete and incomplete shadow marks;
- profitable, losing and zero net marks;
- marked candidate and research-run counts;
- whether decision-time probability fields are actually present.

If probabilities were not captured immutably at decision time, the runtime reports that absence instead of reconstructing probabilities with hindsight.

## Existing shadow machinery

Package D extends, rather than replaces, Christiania's existing shadow infrastructure:

- `shadow_lifecycle.py` remains the lifecycle state machine;
- `shadow_admission.py` remains the admission/risk boundary for the existing cohort;
- `shadow_outcome_collector.py` remains the conservative mark collector;
- the frozen local-surface prospective programme remains governed by `model_governance_prospective_freeze_v1.py`.

## Browser surface

`pages/04_Calibration_Shadow.py` exposes the prospective freeze, inference firewall, shadow lifecycle evidence and probability-channel readiness.

The page deliberately treats missing immutable probability capture as a scientific finding/gap rather than silently filling it.

## Scientific boundary

Package D answers:

> **How well calibrated is this model on genuinely prospective outcomes, and is the evidence mature enough to justify a human promotion review?**

It does not answer:

> **Should this trade be taken now?**

That is Package E's decision-governance problem.
