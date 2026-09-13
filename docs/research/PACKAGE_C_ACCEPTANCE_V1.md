# Package C Acceptance Contract — Edge Library + Risk Mathematics V1

Package C may merge only when the full Christiania Quality Gate is green.

## Required acceptance points

- Edge Library entries remain research-governed and `NOT_ACTIVATED`.
- Variance risk premium remains defined-risk only.
- 0DTE remains Casino-only and unverified until proven.
- Correlation/dispersion remains capital-incompatible with the current bankroll.
- IV versus forecast-RV output is labelled diagnostic, not edge proof.
- Runtime database access is read-only.
- No schema migration is required.
- No broker/order execution path is introduced.
- No p-value/FDR path is enabled.
- No hypothesis-family allocation is silently frozen or consumed.
- Structure mathematics distinguishes bounded from unbounded loss.
- Risk-budget rejection does not masquerade as a statement about trade expectancy.
- Expected P&L is explicitly conditional on supplied distribution assumptions.
- Costs and slippage are included before risk-compensation ratios are reported.
- VaR/CVaR and bankroll-impairment outputs are tested.
- Existing Package B forecast machinery is reused rather than duplicated conceptually.
- Decision authority remains `NONE_RESEARCH_ONLY`.

## Release boundary

A green Package C is mathematical/research infrastructure. It does not make a trade eligible for manual review. Promotion remains the responsibility of later prospective calibration, shadow evidence and decision-governance packages.
