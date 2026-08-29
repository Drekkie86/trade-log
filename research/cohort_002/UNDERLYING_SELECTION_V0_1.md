# Cohort 002 — Underlying Selection v0.1

Selected initial trio:

- `AAPL`
- `XOM`
- `JPM`

## Why these three

`AAPL` preserves continuity with Cohort 001.

`XOM` introduces a large energy exposure whose option behaviour can respond to
a materially different economic driver set.

`JPM` introduces a large financial exposure with another distinct business and
volatility context.

The trio is deliberately small. The question is not “how many tickers can we
scan?” but “how much independent information does each additional underlying
actually contribute?”

## Selection discipline

This selection is made before Cohort 002 outcome data exist.

A name should be replaced only for an operational reason documented before
preregistration, such as:

- provider cannot resolve it reliably;
- option universe cannot be collected completely;
- required instrument is unavailable;
- persistent data-quality failure.

It must not be replaced because another symbol appears to backtest better.

## Validation command

Run:

`python check_cohort_002_underlyings_live.py`

The script is read-only and checks:

- complete Massive 7–45 DTE chain retrieval;
- Saxo primary-stock resolution;
- Saxo underlying quote retrieval;
- at least one Massive-to-Saxo option-contract bridge.

Quote quality is printed but is not itself the identity-seam gate. Open-market
`EXECUTABLE` behaviour remains a separate market-data-quality question.
