# MODEL_GOVERNANCE_PROSPECTIVE_FREEZE_V1

Purpose: freeze the post-v23 discovery state before collecting additional independent dates.

## Boundary
- V1 remains frozen.
- Quadratic V2 remains observational and is the frozen primary research model, not a trading model.
- Nearest-bracket local-linear V1 remains an observational challenger; there is no automatic model selection.
- Black-Scholes-Merton and Bayesian persistence slots are reserved only; they are not implemented and cannot emit evidence.
- All dates through the latest v23 source session are pre-freeze discovery.
- Later dates are labelled post-freeze prospective by a database view.
- No p-values, BH/FDR, candidate/admission path, model auto-selection, edge claim, or trading decision is enabled.

## Frozen questions
1. Does DTE 14–20 transfer instability persist across new independent dates?
2. Does local-linear generalize better than frozen quadratic V2 out of sample, rather than merely fitting these two days better?
3. Do spread and timing-quality effects replicate prospectively?
4. Do persistent same-sign episodes recur across independent dates?

First descriptive review: 5 independent prospective dates. Preregistration review remains reserved for 20+ independent dates.


## Recovery provenance covariate

From schema v25 onward, prospective residual observations can be queried through
`v_local_surface_v2_prospective_partition_v2`, which carries per-underlying
recovery provenance from collection. A recovered observation is not excluded or
reweighted automatically; recovery status is an observational covariate only.

No frozen hypothesis, model role, threshold, p-value/FDR firewall, admission
rule, or trading decision is changed by this instrumentation.
