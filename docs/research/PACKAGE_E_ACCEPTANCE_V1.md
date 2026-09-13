# Package E Acceptance Contract — Decision Engine + Discipline Leakage V1

Package E may merge only when the full Christiania Quality Gate is green.

## Required acceptance points

- `NO_TRADE` remains a first-class successful decision state.
- The only decision states are `NO_TRADE`, `CONTINUE_SHADOW`, and `ELIGIBLE_FOR_MANUAL_REVIEW`.
- `ELIGIBLE_FOR_MANUAL_REVIEW` has no broker execution authority.
- Undefined or unbounded downside fails closed to `NO_TRADE`.
- An edge family that is not explicitly activated for manual review fails closed to `NO_TRADE`.
- Calibration, robustness, sample sufficiency and risk compensation are separate gates.
- Probability of profit / win rate cannot override inadequate tail compensation.
- Opportunity ranking uses evidence quality, calibration, robustness and risk compensation rather than win rate alone.
- Model-approved and discretionary/unapproved observations are scored separately.
- Approved and discretionary P&L/expectancy are not mixed.
- Post-win discipline leakage is measured explicitly.
- Strategy/model failure is distinguished from operator-discipline failure without claiming causal proof.
- Missing execution provenance is reported as missing; it is never reconstructed from ambiguous historical fields.
- Runtime database access is read-only.
- No schema migration is required by Package E.
- No live database mutation is introduced.
- No broker/order execution path is introduced.
- No edge family is activated by Package E.
- Existing Package D prospective/shadow evidence is reused rather than duplicated.
- Decision authority remains manual-review-only with no automatic execution.

## Release boundary

A green Package E is decision-governance and operator-behaviour research infrastructure. It does not make any candidate executable. Package F remains a separate Casino research module and may not weaken Main Engine governance.
