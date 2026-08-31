# Shadow Structure Bridge v1

This is the bridge between a surfaced empirical anomaly and a possible
defined-risk expression.

It deliberately stops **before shadow-candidate admission**.

## Why a separate proposal layer exists

`LOCAL_IV_RESIDUAL_V1` says that one contract's implied volatility differs
from its nearest usable strike neighbors.

That does not automatically imply:

- buy the contract;
- sell the contract;
- buy volatility;
- sell volatility;
- positive expectancy.

Christiania therefore first asks whether the observation can be expressed
with a bounded-loss structure under frozen rules.

## Frozen builder

Identity:

- builder family: `LOCAL_IV_BUTTERFLY_EXPRESSION_V1`
- builder version: `1.0.0`
- rule version: `LOCAL_IV_BUTTERFLY_RULES_V1`

The builder requires equal-distance lower and upper strike neighbors.

For `IV_RICH_LOCAL`:

- buy 1 lower-strike option;
- sell 2 target options;
- buy 1 upper-strike option.

This is recorded as `LONG_1_2_1_BUTTERFLY`.

For `IV_CHEAP_LOCAL`:

- sell 1 lower-strike option;
- buy 2 target options;
- sell 1 upper-strike option.

This is recorded as `REVERSE_1_2_1_BUTTERFLY`.

The structure is only proposed when all three legs can be mapped to the same
persisted ThetaData snapshot, have contract multipliers, and have the required
bid/ask side.

## Conservative entry and risk

Hypothetical entry uses:

- BUY at ask;
- SELL at bid.

Theoretical expiry max loss is calculated from the complete multi-leg payoff
at the piecewise-linear breakpoints.

Risk currency is explicitly `USD`.

This is **not yet compared to the user's EUR bankroll**.

## Why proposals are not candidates yet

The active bankroll is denominated in EUR. Schema v11 therefore refuses to
pretend that a USD max-loss figure has passed the EUR sizing rule.

Before admission to `shadow_candidates`, Christiania still needs:

1. an explicit USD→EUR FX observation with provenance;
2. sizing-policy application;
3. cost-model handling;
4. the intended governance/admission checks.

Until then:

`PROPOSED != ADMITTED`

This avoids turning a research anomaly into a shadow trade by accident.

## Persistence

Migration 011 adds immutable `shadow_structure_proposals`.

All surfaced anomalies processed by the builder are persisted as either:

- `PROPOSED`, or
- `BLOCKED` with an explicit reason.

The builder is idempotent for the same hypothesis evaluation and builder
version.
