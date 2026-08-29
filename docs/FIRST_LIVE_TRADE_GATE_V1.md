# Christiania — First Live Defined-Risk Trade Gate v1

Status: BLOCKING CHECKLIST

A first real trade is an execution/harvestability experiment, not proof of edge.
It may proceed only when all blocking items below are satisfied.

## Blocking before first real trade

- Cohort 001 remains untouched and its scheduled run/status is resolved.
- Repository state used for the trade is committed and identifiable by Git HEAD.
- Trade is defined-risk; no naked short option or margin-variable downside.
- Exact maximum loss including commissions/fees is known before order entry.
- Total active speculative bankroll remains inside the hard account cap.
- Simultaneous correlated exposure and experiment stop/drawdown rule are written.
- Saxo instrument identity is resolved and broker availability verified.
- A current quote can be classified as executable under the intended order convention.
- Intended limit price is recorded before submission.
- Actual fill price, timestamp, fees and resulting slippage are recorded after fill.
- Belgian tax/accounting treatment relevant to the instrument has been checked before net-expectancy claims are made.

## Fill calibration

The first five actual fills are calibration evidence only. For each record:

- intended price;
- displayed bid/ask and timestamp;
- order type and limit;
- achieved price;
- commissions/fees;
- latency if available;
- difference versus intended midpoint/limit;
- whether the order was partially filled or cancelled/replaced.

Do not infer edge from these five fills. Their purpose is to establish whether
Christiania's quote/fill assumptions are even harvestable at the account scale.
