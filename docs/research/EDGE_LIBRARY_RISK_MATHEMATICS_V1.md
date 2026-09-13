# Edge Library + Risk Mathematics V1

## Purpose

Package C turns Christiania's risk doctrine into executable research machinery without activating any new trading authority.

The core doctrine is:

> **Risk selection, not risk avoidance.**

A trade is not rejected merely because it can lose. Christiania should measure whether the downside is bounded, how large and concentrated the loss distribution is, how much capital can be impaired, and whether the estimated compensation is adequate under explicit assumptions.

Package C remains **research-only**. It creates no broker order, no automatic approval, no new hypothesis-family activation and no claim that a positive volatility gap is a proven edge.

## Governed Edge Library

`src/research/edge_library_v1.py` encodes the initial edge families and their scientific state:

- variance risk premium — `RESEARCHABLE_DEFINED_RISK_ONLY`;
- IV versus forecast-RV gap — `CORE_CANDIDATE_REQUIRES_FORECAST_MODEL`;
- demand pressure — `CANDIDATE_REQUIRES_DATA_BASELINES`;
- idiosyncratic volatility — `CANDIDATE_REQUIRES_FACTOR_MODEL`;
- option momentum — `SHADOW_ONLY`;
- quarterly variance seasonality — `SHADOW_ONLY`;
- earnings/event premium — `EVENT_RESEARCH`;
- correlation/dispersion — `RESEARCH_ONLY_CAPITAL_INCOMPATIBLE`;
- 0DTE — `CASINO_UNVERIFIED_UNTIL_PROVEN`.

Every current library entry is `NOT_ACTIVATED` and requires defined risk for eventual capital use.

The Edge Library is therefore a governed research inventory, not a strategy menu.

## IV versus forecast-RV diagnostic

`variance_gap_diagnostic(...)` compares annualized implied variance with a daily realized-variance forecast annualized on 252 trading days.

It reports:

- implied variance;
- forecast variance;
- annualized forecast volatility;
- variance gap;
- variance ratio;
- an optional normalized gap when a forecast-error standard deviation is available.

The normalization is performed in variance units. The result is explicitly labelled `RESEARCH_DIAGNOSTIC_NOT_EDGE_PROOF`.

## Read-only live research runtime

`src/research/edge_risk_runtime_v1.py` uses the existing evidence database without mutation.

For each selected underlying it:

1. takes one end-of-session observation per available session date;
2. builds log returns;
3. reuses Package B's rolling-origin Historical / EWMA / GARCH tournament;
4. selects the historically best QLIKE model descriptively;
5. produces the current forecast from the trailing window;
6. estimates historical forecast-error dispersion for optional normalization;
7. selects the nearest available option expiration to the configured horizon;
8. uses the median Theta IV across strikes within ±10% of spot for that expiration;
9. emits a descriptive IV-versus-forecast-RV diagnostic.

This is deliberately not called a signal. Horizon matching is approximate, the IV statistic is a surface summary rather than an executable structure price, and historical tournament leadership does not establish future superiority.

The runtime exposes:

- `decision_authority = NONE_RESEARCH_ONLY`;
- `family_activation_authority = NONE_PROGRAMME_BUDGET_UNFROZEN`.

## Structure risk-selection mathematics

`src/quant/risk_selection.py` extends the existing option-risk stack with an explicit assumption-conditioned terminal distribution.

Inputs include:

- annual drift;
- annual volatility;
- optional Poisson jump intensity;
- mean log jump;
- jump volatility;
- transaction costs;
- slippage;
- bankroll and maximum-loss fraction.

For a multi-leg option structure it reports:

- exact expiry payoff bounds where finite;
- bounded/unbounded-loss state;
- assumption-conditioned expected P&L;
- median and standard deviation of P&L;
- probability of profit and loss;
- 5/25/50/75/95 P&L percentiles;
- 95% VaR and CVaR of loss;
- maximum loss / bankroll fraction;
- probability of losing at least the entire bankroll under the simulated distribution;
- maximum whole structures permitted by a hard maximum-loss budget;
- expected-P&L-to-max-loss and expected-P&L-to-CVaR ratios.

The expected P&L is **not** labelled alpha, edge or forecast truth. It is conditional on the supplied distribution assumptions.

## Bounded-risk enforcement

The engine identifies unbounded short-call exposure from terminal payoff slope. A structure with unbounded loss receives:

`REJECT_UNBOUNDED_LOSS`

when evaluated against a bankroll budget.

A bounded structure can still exceed the configured risk budget without being called a bad trade. That state is:

`EXCEEDS_SINGLE_STRUCTURE_RISK_BUDGET`

This distinction is important: risk governance and expected-value quality are separate questions.

## Browser surface

`pages/03_Edge_Risk_Lab.py` exposes:

- the governed Edge Library;
- current read-only IV/forecast-RV diagnostics;
- a manual two-leg bounded-risk sandbox;
- explicit distribution assumptions and jump inputs;
- bankroll-budget diagnostics.

The page cannot submit an order or activate an edge family.

## Scientific boundary

Package C provides the mathematics needed to ask:

> **How much are we being paid, under explicit assumptions, to accept exactly this bounded risk?**

It does not yet answer whether a candidate deserves promotion to manual review. That requires Package D prospective calibration/model tournament/shadow evidence and later Package E decision governance.
