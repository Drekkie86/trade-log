# Package F — Casino + 0DTE Lab V1

## Charter

> **Casino in spirit, quant in discipline.**

Package F is deliberately separated from Christiania's Main Engine. It exists to research higher-variance ideas such as 0DTE structures without weakening the standards required for normal manual-review eligibility.

The Casino is a scientific instrument, not a signal toy. Spectacular historical returns are not evidence of edge.

## Architectural separation

Casino V1 uses the explicit namespace:

`CASINO_V1`

Its authority is:

`RESEARCH_SHADOW_ONLY_NO_EXECUTION`

Main Engine authority is unchanged by Casino output. Casino research cannot activate an edge family, promote a Main Engine model, or submit a broker order.

## Risk budget

Every Casino experiment receives a hard maximum-loss budget:

`min(casino_cap, bankroll × max_loss_fraction)`

Unknown or unbounded maximum loss fails closed to `NO_TRADE`.

A defined-risk structure that exceeds the experiment budget also resolves to `NO_TRADE`, regardless of win probability or apparent upside.

## 0DTE volatility diagnostic

The 0DTE diagnostic compares variance over **remaining time**, not annualized volatility numbers in isolation.

It reports:

- implied remaining variance;
- forecast remaining variance;
- optional remaining jump variance;
- implied-minus-forecast variance gap;
- variance ratio;
- put-minus-call IV skew;
- optional gamma/theta cash-exposure ratio;
- liquidity state from bid/ask spread fraction.

A positive variance gap is labelled:

`CASINO_RESEARCH_DIAGNOSTIC_NOT_EDGE_PROOF`

It is not automatically interpreted as short-volatility edge because event risk, skew, liquidity, path dependency and transaction costs can dominate the trade.

## Scenario EV

Casino V1 evaluates explicit probability-weighted scenarios after transaction costs and slippage.

It reports:

- expected net P&L;
- probability of net profit;
- discrete 95% loss CVaR;
- expected-P&L-to-max-loss;
- hard risk-budget state.

A candidate enters only `CASINO_SHADOW_CANDIDATE`. No output is executable.

## Liquidity

Liquidity is an independent gate. Poor or unknown liquidity prevents shadow candidacy even if modeled EV is positive.

This is intentional for 0DTE, where spread and slippage can consume a large share of theoretical edge.

## Dealer positioning

Dealer positioning is accepted only when the value has an explicit measured source. If no such input exists, the diagnostic reports:

`NOT_MEASURED_DO_NOT_INFER`

Christiania does not manufacture dealer-gamma narratives from price action, social-media claims or unsupported heuristics.

## Read-only live evidence runtime

`src/research/casino_0dte_runtime_v1.py` scans the existing evidence database read-only for contracts whose expiration equals the immutable US session date.

It counts:

- independent 0DTE sessions;
- snapshots;
- quotes;
- underlyings;
- Greek observations;
- usable spread observations.

The runtime creates no new table, migration, admission or execution path.

## Browser surface

`pages/06_Casino_0DTE_Lab.py` exposes:

- current 0DTE evidence availability;
- remaining-variance diagnostics;
- skew/gamma/theta/liquidity research fields;
- explicit Casino risk policy;
- editable scenario-EV analysis;
- `NO_TRADE` as a valid and common outcome.

## Scientific boundary

Package F asks:

> **Is there enough measurable compensation to justify tracking this deliberately high-variance, tightly capped experiment in a separate shadow laboratory?**

It does not answer whether the experiment should be traded with live money. That authority does not exist in Casino V1.
