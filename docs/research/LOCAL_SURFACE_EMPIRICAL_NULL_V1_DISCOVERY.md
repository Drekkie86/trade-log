# LOCAL_SURFACE_EMPIRICAL_NULL_V1 — Discovery Statistics

## Purpose

This layer estimates the empirical distribution of `LOCAL_SURFACE_RESIDUAL_V2` observations using only dates already registered as discovery/burned evidence. It exists to learn the shape, scale, heterogeneity and dependence of V2 residuals before any confirmatory decision rule is designed.

## Source firewall

Rows are eligible only when their `us_session_date` falls inside `research/edge_discovery/DISCOVERY_WINDOW_REGISTRY.json`. A future confirmation date is therefore excluded unless the registry is explicitly amended to burn it.

## Robust distribution estimates

Residuals are grouped by:

- option right (`C` / `P`),
- DTE bucket (`7–13`, `14–20`, `21–30`, `31–45`, other),
- absolute-delta bucket (`0.10–0.25`, `0.25–0.40`, `0.40–0.60`, `0.60–0.80`, other).

Each cell stores empirical quantiles, mean/std, median/MAD and a MAD-derived robust scale. Sparse cells are deterministically shrunk toward their same-right parent, whose location/scale is itself shrunk toward the global distribution. This is an empirical-Bayes-like stabilization device, not a Bayesian posterior and not a significance test.

## Dependence diagnostics

Repeated observations are summarized at four clustering levels:

- contract/session,
- surface/session,
- underlying/session,
- session date.

For each level Christiania records cluster sizes, a one-way ICC-like estimate when estimable, an unequal-cluster-size design-effect approximation and an effective-N proxy. These are exploratory diagnostics only. They are not used by the scanner, bridge, admission, or any trading logic.

## Explicitly absent

This version does **not** compute or persist:

- z-scores,
- p-values,
- empirical tail probabilities used as p-values,
- BH/FDR decisions,
- surfaced V2 signals,
- candidate creation,
- admission decisions,
- trading instructions,
- edge claims.

The database enforces `p_values_enabled = 0`, `fdr_enabled = 0`, and `decision_enabled = 0` on every null-model run.

## Operational flow

1. `backfill_discovery_surface_v2.py` fills missing V2 observations only for registered discovery research runs.
2. `fit_local_surface_empirical_null_v1.py` fits and persists one discovery-only null snapshot.
3. `report_local_surface_empirical_null_v1.py` writes a descriptive Markdown/JSON report to Downloads.

Repeated model fits are versioned by configuration and the maximum V2 observation id in the discovery dataset. A later discovery snapshot may therefore coexist with an earlier one without mutation.
