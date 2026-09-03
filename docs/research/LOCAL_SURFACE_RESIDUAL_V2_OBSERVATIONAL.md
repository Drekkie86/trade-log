# LOCAL_SURFACE_RESIDUAL_V2 — Observational Instrumentation

## Status

`LOCAL_SURFACE_RESIDUAL_V2` is a discovery-only measurement layer. It is not a trading hypothesis, does not surface candidates, and cannot feed structure construction or admission.

V1 remains frozen and unchanged.

## Measurement

For each structurally eligible, Massive-reference-mapped option within the frozen absolute-delta band, V2 groups contracts by underlying, expiration and right.

For a target strike, V2 excludes that target from the fit and fits a quadratic to the remaining usable strikes. Strike values are centered and scaled around the omitted target for numerical stability. The persisted primary measurement is:

`loo_residual = observed_iv - fitted_iv`

No residual threshold is applied.

## Minimum geometry

A quadratic has three fitted parameters. V2 requires at least five usable strikes in the full group, leaving at least four points after target omission and therefore at least one residual degree of freedom.

The per-target fit diagnostics are persisted, but `fit_rmse` is not treated as a calibrated uncertainty estimate and is not used to create a z-score.

## Persisted diagnostics

- observed and fitted IV
- raw and absolute LOO residual
- usable strike count
- LOO fit-point count
- fit degrees of freedom
- fit SSE and RMSE
- design-matrix condition number
- explicit non-evaluable reason when measurement cannot be made

## Hard firewall

The v19 schema enforces `surfaced_count = 0` and `decision_enabled = 0` for every V2 run. The V2 observation state has no `SURFACED` value.

`full_research_cycle.py` continues to construct proposals only from the persisted V1 hypothesis-scanner run ID.

## Discovery dataset

`v_local_surface_residual_v2_discovery_dataset` joins V2 residual observations to contemporaneous bid/ask spread, DTE and the v18 Greek timing diagnostics. This is intended as raw material for a future pooled/shrunk empirical null model.

The view does not calculate p-values, z-scores or FDR decisions.

## Future boundary

The intended future sequence remains:

`LOO residual -> pooled/shrunk null model -> calibrated p-value -> frozen multiplicity procedure -> surfaced hypothesis`

No later stage may be introduced using September discovery data as confirmation evidence.
