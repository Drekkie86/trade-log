# Christiania V1.0 Status

## Product construction

Christiania has completed the core collection, persistence, shadow, quantitative-model, decision-read-model and appliance-style deployment foundations needed to continue scientific development without treating the production VM as a development workstation.

Historical V1 package continuity remains explicit: **Package 7: advanced quantitative model library/research bench** is complete and supplies the pricing, volatility, simulation, scenario and model-disagreement foundations used by the current roadmap. The newer A–F package sequence describes the next intelligence-development pipeline rather than replacing completed package history.

The Control Plane Reset is complete in production at commit `fa5a3c645c6e752d8bfb354959fc1442e5ad6cd0`.

Current product-development sequence is maintained in `docs/ROADMAP.md`. The active next layer is the Research Command Deck + programme-family governance package, followed by forecasting/surface intelligence, Edge Library/risk mathematics, calibration/model tournament/shadow promotion, decision/discipline and the separate Casino/0DTE Lab.

## Operational state

- Windows/GitHub is the source-of-truth workshop.
- Hetzner is an artifact deployment target using commit-addressed releases.
- The production development checkout has been removed.
- Release identity is checked explicitly.
- Supervisor evidence has a freshness budget; stale evidence cannot keep status `READY`.
- Research progress is checked separately from process liveness.
- Canonical resource policy covers all 14 services.
- Theta, research daemon and Streamlit app are the core active runtime.
- Frequent deep-health/burn-in/readiness timers remain intentionally disabled until redesigned.
- oauth2-proxy is deliberately disabled. It is resource-governed for future use but is not currently treated as an exposed production edge.

The last verified operator status after the control-plane cleanup was `READY`, with release identity, supervisor freshness, research progress and 14/14 resource-policy checks passing.

## Quantitative state

The repository already contains substantial quantitative infrastructure rather than a greenfield model stack: Black-Scholes/implied-volatility/Greeks foundations, trees, Monte Carlo, Heston, Merton jump diffusion, SVI, SABR, local-volatility extraction, realized-volatility estimators, volatility forecasts, event/tail diagnostics, scenario analysis, structure risk/EV and model-disagreement tooling.

New development should extend and prospectively test these components rather than re-create them.

## Scientific state

Scientific maturity remains deliberately independent from product maturity.

The frozen local-surface programme continues collecting prospective evidence. The persisted calibration-validity layer keeps p-values, FDR and decision use disabled unless its own evidence explicitly permits a later state transition.

The programme-family budget currently remains deliberately `UNFROZEN`. Existing prospective research may continue. A new edge family may not be preregistered or activated until a programme allocation is deliberately frozen and the family is within that allocation.

Academic or historical evidence is treated as a source of hypotheses, not proof of current tradability.

## Current risk doctrine

Christiania is a risk-selection machine, not a risk-avoidance machine.

The Main Engine may accept meaningful loss probability when:

- loss is bounded;
- payoff distribution is quantified;
- expected compensation remains positive after costs and uncertainty;
- bankroll impact is acceptable;
- evidence and calibration meet the applicable promotion gate.

Undefined downside is not acceptable for the current experimental account. Variance-risk-premium work, for example, is admissible only through defined-risk structures.

## Open infrastructure backlog

These are intentionally separate from the intelligence roadmap and should not block normal research development unless evidence makes them urgent:

- redesigned burn-in;
- redesigned strict/deep backup verification;
- external observability;
- offsite encrypted backup/restore maturation;
- optional secure browser edge;
- host swap-policy tuning only if measurement justifies it.

## Explicitly outside current automatic authority

- automatic broker-order execution;
- naked/undefined-loss option exposure for the experimental bankroll;
- challenger-model admission/decision authority without prospective governance;
- scientific claims of repeatable positive expectancy before evidence supports them;
- treating Main Engine and Casino evidence as one statistical population.
