# Forecasting + Surface Intelligence V1

## Purpose

Package B strengthens Christiania's volatility-forecasting substrate and surface-model comparison before any new edge family is activated.

It is deliberately **research-only**. This package creates no trade candidate, activates no hypothesis family, enables no p-value/FDR path and grants no challenger model promotion authority.

## Forecast validation

`src/quant/forecast_validation.py` provides common scoring and tournament infrastructure for variance forecasts:

- bias;
- MAE;
- RMSE;
- QLIKE;
- forecast-interval coverage and width;
- interval calibration error when an expected coverage is supplied;
- bootstrap confidence intervals around mean QLIKE loss;
- per-regime tournaments.

Lower loss is better. A tournament winner is descriptive evidence only.

## Rolling-origin forecast experiment

`src/quant/rolling_variance_forecast.py` converts an observed return series into strictly rolling-origin comparisons among:

- historical sample variance;
- EWMA variance;
- GARCH(1,1) variance.

At each origin, models see only the trailing training window. Realized variance is computed from the following forecast horizon. The current regime label is also derived only from the trailing window, avoiding look-ahead contamination.

The GARCH horizon forecast uses the fitted one-step variance and the fitted persistence recursion to average expected variance across the requested horizon.

## Surface intelligence

`src/research/surface_intelligence_v1.py` compares:

- incumbent: `LOCAL_SURFACE_QUADRATIC_V2`;
- challenger: `NEAREST_BRACKET_LINEAR_V1`.

Both are evaluated leave-one-out on the same surface slice. The edge strikes are not falsely treated as bracket-comparable observations. The result reports MAE, RMSE, challenger win rate, median absolute-error improvement and residual-sign agreement.

The incumbent remains frozen. The challenger state is always `RESEARCH_ONLY_CHALLENGER` in this package.

## Existing-database runtime

`src/research/forecast_surface_runtime_v1.py` is read-only and uses Christiania's existing evidence database.

For forecast evaluation it:

1. selects the latest valid underlying price per underlying/session date;
2. converts those session prices to log returns;
3. reports `ACCUMULATING_HISTORY` until enough returns exist;
4. then runs rolling-origin historical/EWMA/GARCH tournaments.

For surface evaluation it:

1. selects the latest research-run surface slice with at least five valid Theta IV strikes;
2. compares the frozen quadratic incumbent with the nearest-bracket linear challenger;
3. exposes the result without persisting or promoting it.

No live database mutation or migration is required.

## Browser surface

`pages/02_Forecasting_Surface_Intelligence.py` exposes the current runtime state, forecast rankings, model metrics and surface challenger diagnostics.

The page explicitly shows `Decision authority = NONE_RESEARCH_ONLY`.

## Scientific boundary

Package B answers questions such as:

- Which volatility forecast has lower out-of-sample loss on the history currently available?
- Does model performance change by trailing volatility regime?
- Is a simple local linear bracket a useful challenger to the frozen quadratic surface model?
- Is Christiania still accumulating enough daily history for honest forecast evaluation?

It does **not** answer:

- whether IV/RV, VRP or another edge is currently tradable;
- whether a challenger should replace the frozen incumbent;
- whether any option should be bought or sold.

Those require later programme-family allocation, prospective evidence, costs, robustness, calibration and risk mathematics.
