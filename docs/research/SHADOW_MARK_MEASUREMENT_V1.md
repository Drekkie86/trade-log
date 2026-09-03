# Shadow Mark Measurement V1

## Status

Research measurement rule. No live orders.

## Current mark meaning

`shadow_mark_observations` produced by the current collector are **independent-leg liquidation stress marks**:

- existing long option legs are valued at their bid;
- existing short option legs are valued at their ask;
- each leg is valued independently;
- the calculation does not represent an executable package/complex-order quote.

This convention is deliberately conservative and preserves useful microstructure stress evidence. It can produce a liquidation loss larger than the structure's theoretical expiry max loss because bid/ask crossing and legging costs are outside the terminal payoff bound.

Therefore these marks are **not valid primary edge outcomes**.

Migration 017 makes that explicit with:

- `measurement_role = INDEPENDENT_LEG_LIQUIDATION_STRESS`
- `outcome_eligible = 0`

Historical mark values are preserved unchanged.

## Future outcome eligibility

A future mark may only be made outcome-eligible under a separately frozen measurement rule that defines, at minimum:

1. entry convention;
2. exit horizon;
3. quote synchronization/freshness;
4. package or otherwise defensible executable exit pricing;
5. transaction costs;
6. candidate closure/scoring semantics.

Do not infer strategy expectancy from current shadow-mark P&L fields.
