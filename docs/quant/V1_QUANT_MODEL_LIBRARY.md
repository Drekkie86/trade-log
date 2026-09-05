# Christiania V1.0 Quantitative Model Library

## Charter

The V1 quantitative library exists to make Christiania mathematically strong **without converting model output into an unearned trading decision**. Every model added by this package is research-only. Decision and admission flags remain disabled.

## Included model families

- Black-Scholes-Merton European vanilla pricing with continuous dividends;
- Black-76 forward/futures option pricing;
- robust implied-volatility inversion with no-arbitrage bounds;
- analytic first- and higher-order Greeks with finite-difference validation;
- Cox-Ross-Rubinstein European/American binomial trees;
- Crank-Nicolson finite-difference European BSM PDE cross-validation;
- risk-neutral Monte Carlo with antithetic variates and a discounted-underlying control variate;
- Heston stochastic-volatility pricing and bounded calibration diagnostics;
- Merton lognormal jump-diffusion pricing;
- raw SVI smile calibration and sampled diagnostics;
- Hagan lognormal SABR implied-volatility approximation;
- PCHIP total-variance smile interpolation;
- sampled call monotonicity, convexity, bounds and calendar-total-variance diagnostics;
- Breeden-Litzenberger risk-neutral density extraction from call-price slices;
- Dupire local-volatility extraction from a call-price grid, failing closed where the PDE inversion is not identifiable;
- close-to-close, Parkinson, Garman-Klass, Rogers-Satchell and Yang-Zhang realized-volatility estimators;
- EWMA and Gaussian GARCH(1,1) volatility forecasts;
- event-variance decomposition and implied-vs-realized variance comparison;
- historical tail diagnostics including VaR, CVaR, skewness, kurtosis and a Hill tail-index estimate;
- spot/vol/time scenario grids;
- generic option-structure payoff, defined-risk, EV-after-costs, probability-of-profit and loss-tail diagnostics;
- model-disagreement summaries.

## Governance

No model in `src/quant` is permitted to:

- import or call broker-order functionality;
- set candidate admission decisions;
- set model decision flags;
- mutate the frozen prospective protocol;
- change the frozen `LOCAL_SURFACE_QUADRATIC_V2` primary role;
- claim that model/market disagreement is edge.

`src/quant/registry.py` therefore hard-codes `decision_enabled=False` and `admission_enabled=False` for every registered V1 quant model.

## Validation philosophy

The package deliberately uses redundant numerical methods. Black-Scholes prices are compared with trees and Monte Carlo; analytic Greeks are compared with finite differences; implied-volatility inversion is round-tripped; stochastic-volatility and jump models have limiting-case tests; structure risk is tested for bounded and unbounded payoffs.

Mathematical sophistication is treated as a source of *diagnostics and falsification*, not authority.

## Pricing-measure EV is not a real-world forecast

Structure evaluation in V1 uses risk-neutral/lognormal pricing assumptions to compare model value with entry premium and explicit costs/slippage. The reported pricing-measure EV and risk-neutral probability of profit are **not** asserted to be real-world expected return or a calibrated forecast probability. Christiania must earn any physical-measure probability model prospectively before it can make that stronger claim.
