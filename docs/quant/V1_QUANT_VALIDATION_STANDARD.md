# V1 Quantitative Validation Standard

Christiania's quantitative library must satisfy four layers of validation.

## 1. Domain safety

Invalid economic/model inputs fail explicitly: non-positive spot/strike, negative time, invalid correlation, negative jump intensity, malformed OHLC data, impossible option prices and invalid calibration datasets.

## 2. Mathematical invariants

Tests cover:

- put-call parity;
- no-arbitrage lower/upper option-price bounds;
- European tree convergence toward BSM;
- American put value not below its European counterpart;
- BSM implied-volatility price round-trip;
- analytic-vs-numerical Greeks;
- Monte Carlo confidence coverage around the closed form;
- Heston zero-vol-of-vol limit to BSM;
- Merton zero-jump limit to BSM;
- positive/non-negative variance and surface constraints;
- finite, deterministic seeded simulations.

## 3. Calibration diagnostics

Calibrators return convergence state, RMSE, MAE, maximum absolute error, objective value and parameter-boundary hits. A numerical optimizer returning a parameter vector is not enough to call calibration successful.

## 4. Governance firewall

Quant models are challengers/diagnostics only in V1. Tests scan the quantitative package for broker-order and admission/decision coupling and require the registry to keep every model disabled for decision/admission use.
