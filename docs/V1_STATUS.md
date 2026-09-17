# Christiania V1.0 Status

## Product construction

Christiania has completed the core collection, persistence, shadow, quantitative-model, decision-read-model and appliance-style deployment foundations needed to continue scientific development without treating the production VM as a development workstation.

Historical V1 package continuity remains explicit: **Package 7: advanced quantitative model library/research bench** is complete and supplies the pricing, volatility, simulation, scenario and model-disagreement foundations used by the current roadmap. Its non-primary models remain **research-only challengers/diagnostics** unless prospective governance explicitly grants a later role. The newer A–F intelligence sequence is now complete in GitHub.

Package A — Research Command Deck + programme-family governance — is deployed in production at `afc87be0d09202ba09f8c644c5942e5cfdd7850a`. Packages B through F are merged and await a reviewed batch deployment. Package F culminates the current intelligence sequence at `a0839f04119c42436f9f77d1c54c6cca2a39924f`.

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

The latest verified operator status after Package A deployment is `READY`: deployed commit `afc87be0d09202ba09f8c644c5942e5cfdd7850a`, release identity PASS, supervisor HEALTHY/fresh, research progress PASS, resource policy PASS 14/14, and Theta/daemon/app active.

Production is intentionally behind GitHub `main` until the merged B–F intelligence packages are reviewed and deployed through the existing artifact release path.

## Quantitative state

The repository contains substantial quantitative infrastructure rather than a greenfield model stack: Black-Scholes/implied-volatility/Greeks foundations, trees, Monte Carlo, Heston, Merton jump diffusion, SVI, SABR, local-volatility extraction, realized-volatility estimators, volatility forecasts, event/tail diagnostics, scenario analysis, structure risk/EV and model-disagreement tooling.

Package B added common out-of-sample variance-forecast scoring, rolling-origin historical/EWMA/GARCH tournaments, bootstrap forecast-loss uncertainty, regime-conditioned comparisons and a read-only surface challenger tournament.

Package C added the governed Edge Library, IV-versus-forecast-RV diagnostics, contract-multiplier-aware structure P&L distributions, jump scenarios, VaR/CVaR, bankroll impairment and hard risk-budget sizing.

Package D added calibration and prospective model-tournament machinery, with Brier/log-loss scoring, reliability diagnostics, paired incumbent/challenger comparison and explicit sufficiency/robustness gates.

Package E added the fail-closed decision layer and operator-discipline diagnostics. Main Engine outcomes are `NO_TRADE`, `CONTINUE_SHADOW` and `ELIGIBLE_FOR_MANUAL_REVIEW`; manual-review eligibility is not execution authority.

Package F added the separately namespaced Casino/0DTE research wing with hard experiment loss budgets, remaining-time variance diagnostics, liquidity gates, explicit friction, scenario EV and no execution authority.

## Scientific state

Scientific maturity remains deliberately independent from product maturity.

The frozen local-surface programme continues collecting prospective evidence. The persisted calibration-validity layer keeps p-values, FDR and decision use disabled unless its own evidence explicitly permits a later state transition.

The programme-family budget remains deliberately `UNFROZEN`. Existing prospective research may continue. A new edge family may not be preregistered or activated until a programme allocation is deliberately frozen and the family is within that allocation.

Packages B–F do not by themselves prove repeatable positive expectancy. Their role is to improve measurement, comparison, risk quantification, calibration, decision discipline and experimental separation.

Academic or historical evidence is treated as a source of hypotheses, not proof of current tradability.

## Current risk doctrine

Christiania is a risk-selection machine, not a risk-avoidance machine.

The Main Engine may accept meaningful loss probability only when:

- loss is bounded;
- payoff distribution is quantified;
- expected compensation remains positive after costs and uncertainty;
- bankroll impact is acceptable;
- evidence, calibration and robustness meet the applicable promotion gate.

Undefined downside is not acceptable for the current experimental account. Variance-risk-premium work, for example, is admissible only through defined-risk structures.

The Casino is not a relaxation of this doctrine. It is a separately governed research namespace for deliberately higher-variance experiments with tiny, hard-capped loss budgets and `RESEARCH_SHADOW_ONLY_NO_EXECUTION` authority.

## Decision and discipline state

Christiania now distinguishes model quality from operator behaviour in the decision layer.

- Main Engine decision outputs fail closed.
- Eligibility for manual review requires evidence and governance gates rather than a high win rate.
- Approved and discretionary/unapproved behaviour are analysed separately when explicit provenance exists.
- Missing historical approval provenance is reported as missing rather than inferred from ambiguous fields.
- Discipline leakage after winning periods can be measured without relabelling discretionary outcomes as strategy failure.

## Open infrastructure backlog

These remain intentionally separate from the intelligence roadmap and should not block normal research development unless evidence makes them urgent:

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
- edge-family activation without programme-family allocation;
- scientific claims of repeatable positive expectancy before prospective evidence supports them;
- treating Main Engine and Casino evidence as one statistical population;
- inferring dealer positioning without explicit measured source data;
- reconstructing missing decision-time probabilities or approval provenance with hindsight.

## Next controlled step

Review the merged B–F package set, deploy it through the existing commit-addressed artifact path, verify Christiania health independently of process liveness, and then continue collecting prospective evidence before any further promotion decision.