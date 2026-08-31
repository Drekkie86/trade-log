# Local IV Residual Hypothesis Scanner v1

This is Christiania's first deterministic **hypothesis** scanner.

It is intentionally not a trade recommendation engine.

## Research question

Within one underlying / expiration / option-right slice, does an otherwise
structurally eligible contract have an implied volatility materially above or
below a linear interpolation between its nearest usable lower- and
higher-strike neighbors?

This is a local surface irregularity detector.

It does **not** establish that the irregularity is mispricing.

## Frozen v1 rule family

Identity:

- scanner family: `LOCAL_IV_RESIDUAL_V1`
- scanner version: `1.0.0`
- rule version: `LOCAL_IV_RESIDUAL_RULES_V1`
- hypothesis family: `LOCAL_SURFACE_IV_RESIDUAL`
- hypothesis version: `1.0.0`

Defaults:

- input must first pass `BASIC_TRADABILITY_V1`
- absolute delta band: 0.10–0.80
- local IV residual surface threshold: 0.03 (3 volatility points)
- lower/upper neighbors must be structurally eligible and inside the same
  delta band
- same underlying, expiry, and option right
- interpolation is strike-linear

## Output labels

A surfaced observation is labelled:

- `IV_RICH_LOCAL`, or
- `IV_CHEAP_LOCAL`

Those labels describe the empirical surface shape only.

They do **not** mean:

- sell this option;
- buy this option;
- arbitrage;
- positive expectancy;
- executable edge.

## Full selection-surface persistence

Migration 010 adds:

- `hypothesis_scanner_runs`
- `hypothesis_scanner_evaluations`

Every structurally eligible input is persisted, including observations that:

- fall outside the delta band;
- cannot get bracketing usable neighbors;
- are evaluated but below threshold;
- are surfaced.

This matters because persisting only positive findings would destroy the
multiple-testing denominator and make later scanner-performance analysis
untrustworthy.

Rows are immutable after insertion.

## Why ML still waits

This deterministic scanner creates a clean empirical baseline. Once repeated
live runs and subsequent outcome observations exist, an ML model can be tested
as a challenger against this exact frozen family.

The model must add out-of-sample information after costs; it does not get to
replace the baseline simply because it is more sophisticated.
