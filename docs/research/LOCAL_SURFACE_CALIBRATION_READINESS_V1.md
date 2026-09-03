# LOCAL_SURFACE_CALIBRATION_READINESS_V1 — Discovery Only

Purpose: recover timing diagnostics for pre-v18 evidence without rewriting historical provider rows, collapse repeated 15-minute observations into contract/session episodes, inspect cross-day recurrence, and evaluate quality-conditioned residual persistence.

## Historical timing recovery

`provider_model_timing_reconstruction_v1` derives the same signed timing quantities used by the live v18 instrumentation from persisted raw timestamps. Native v18 values remain untouched. The effective timing view labels every value as `NATIVE_V18`, `RECONSTRUCTED_FROM_PERSISTED_RAW_V1`, or `UNAVAILABLE`.

## Unit of analysis

The calibration-readiness layer treats a contract/session episode as the primary descriptive unit. It persists peak residual, median residual, persistence ratio `abs(median)/peak`, and sign-consistency fraction. It separately groups the same contract across distinct session dates.

## Scientific firewall

This package does not create p-values, calibrated tail probabilities, FDR/BH decisions, candidates, admissions, or edge claims. Schema constraints force `p_values_enabled = 0`, `fdr_enabled = 0`, and `decision_enabled = 0`.

Readiness depends on independent dates, not raw quote rows:
- fewer than 5 dates: `INSUFFICIENT_INDEPENDENT_DATES`
- 5–19 dates: `EXPLORATORY_STABILITY_ONLY`
- 20+ dates: `READY_FOR_PREREGISTRATION_REVIEW_ONLY`

Even the final state requires a separate preregistration decision before any inferential layer can be built.
