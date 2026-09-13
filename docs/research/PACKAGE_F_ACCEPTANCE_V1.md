# Package F Acceptance Contract — Casino + 0DTE Lab V1

Package F may merge only when the full Christiania Quality Gate is green.

## Required acceptance points

- Casino evidence uses an explicit namespace separate from Main Engine evidence.
- Casino output cannot change Main Engine authority or activation state.
- `NO_TRADE` remains a first-class successful outcome.
- Casino candidates are shadow-only and have no broker execution authority.
- Every experiment has a hard maximum-loss budget.
- Unknown or unbounded maximum loss fails closed to `NO_TRADE`.
- A structure above the Casino risk budget fails closed regardless of win probability.
- Scenario EV includes transaction costs and slippage.
- Liquidity is an independent gate and cannot be overridden by attractive modeled EV.
- 0DTE implied-versus-forecast variance is measured over remaining time.
- Remaining jump variance can be represented explicitly.
- Skew and gamma/theta diagnostics remain descriptive.
- Dealer positioning is not inferred when no measured, sourced input exists.
- Spectacular returns / high win rate are not treated as evidence of edge.
- Runtime database access is read-only.
- No schema migration is required.
- No live database mutation is introduced.
- No edge family is activated.
- No automatic promotion is introduced.
- No broker/order execution path is introduced.
- Existing Main Engine decision governance from Package E is not imported into or weakened by Casino V1.

## Release boundary

A green Package F completes the A–F intelligence build as a research-only Casino laboratory. Deployment to production remains a separate reviewed operation.
