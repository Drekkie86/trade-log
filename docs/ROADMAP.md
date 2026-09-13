# Christiania Roadmap — authoritative current plan

Status baseline: the Control Plane Reset is complete in production. Windows/GitHub is the source-of-truth workshop; Hetzner is an appliance-style artifact deployment target. Package A is deployed at `afc87be0d09202ba09f8c644c5942e5cfdd7850a`, with control-plane status `READY`, release identity PASS, research progress PASS and resource policy PASS 14/14. Packages B through F are merged to `main` and await the next reviewed deployment cycle. The current intelligence stack on `main` culminates in Package F at `a0839f04119c42436f9f77d1c54c6cca2a39924f`.

This document supersedes earlier package numbering where it conflicts with the current plan. Historical package documents remain evidence of what was built, not instructions for what comes next.

## Completed foundation and historical numbering

The earlier V1 sequence remains part of Christiania's implementation history. In particular, **Package 7 — Advanced Quantitative Model Library & Research Bench** delivered the serious pricing, volatility, scenario and model-disagreement foundations that the current intelligence roadmap extends.

**Package 8 — clean-VM Release Candidate / Copenhagen acceptance** delivered the clean-host acceptance, deployment, reboot/recovery and burn-in framework that preceded the later Control Plane Reset. The A–F package sequence below describes the completed intelligence-development pipeline; it does not erase or renumber completed historical work.

## Product goal

Christiania is a quantitative options-research workstation that runs unattended, collects prospective evidence, scrutinises option risk mathematically, and may surface bounded-risk opportunities for manual review.

Christiania is a **risk-selection machine, not a risk-avoidance machine**. Risk is acceptable when downside is bounded, the payoff distribution is quantified, and the estimated compensation is adequate after costs and uncertainty.

Christiania does **not** claim a proven trading edge merely because an anomaly is published, backtested or statistically interesting. `NO TRADE` remains a first-class successful outcome. V1 contains no automatic broker-order path.

## Current operational baseline

- artifact-based, commit-addressed production releases;
- `/opt/christiania` points to the active immutable release;
- no production Git checkout or GitHub credentials are required;
- centralized resource policy covers all 14 Christiania services;
- `christiania-status` fails on stale supervisor evidence;
- Theta, daemon and app are the core active runtime;
- research progress is monitored separately from process liveness;
- burn-in, legacy health and V1-readiness timers remain intentionally disabled until redesigned;
- oauth2-proxy is resource-governed but deliberately disabled; a secure public browser edge is not currently an active dependency of the research programme;
- prospective calibration continues while product development proceeds.

## Scientific doctrine

The promotion ladder is:

1. literature claim or research idea;
2. Christiania reproduction;
3. realistic costs/slippage;
4. out-of-sample evidence;
5. prospective shadow evidence;
6. calibration and robustness;
7. eligibility for manual review.

Academic evidence means that an effect existed in the studied sample, not that it remains tradable now. Published anomalies may decay.

Multiplicity is first-class evidence. A new hypothesis family may not quietly enter the programme simply because the implementation exists.

Main Engine and Casino evidence remain architecturally separate.

## Package A — Research Command Deck + Programme Family Governance — COMPLETE / DEPLOYED

Package A is live in production at `afc87be0d09202ba09f8c644c5942e5cfdd7850a`.

Delivered:

- dedicated Research Command Deck over the existing runtime/read model;
- daemon heartbeat, prospective accumulation, model freeze, hypothesis state, research funnel and shadow evidence visibility;
- runtime-visible programme-family governance;
- family usage derived from append-only hypothesis evidence and observed runtime scanner families;
- fail-closed calibration/inference flags;
- no activation of new edge families while the programme budget remains `UNFROZEN`.

## Package B — Forecasting + Surface Intelligence — COMPLETE / MERGED

Package B is merged to `main` at `41dd5377cacbdae634164c1f95e945d30562f1d1`.

Delivered:

- common realized-variance forecast scoring with bias, MAE, RMSE and QLIKE;
- bootstrap uncertainty around forecast loss;
- interval coverage/calibration diagnostics;
- rolling-origin historical variance, EWMA and GARCH(1,1) tournaments;
- trailing-only regime classification to avoid look-ahead contamination;
- frozen `LOCAL_SURFACE_QUADRATIC_V2` versus research-only `NEAREST_BRACKET_LINEAR_V1` leave-one-out comparison;
- read-only runtime evaluation over existing session-level underlying prices and Theta IV surfaces;
- Forecasting & Surface Intelligence browser page;
- explicit `NONE_RESEARCH_ONLY` decision authority.

`LOCAL_SURFACE_QUADRATIC_V2` remains frozen unless prospective evidence supports promotion of a challenger.

## Package C — Edge Library V1 + Risk Mathematics — COMPLETE / MERGED

Package C is merged to `main` at `3ffd7b09d59625dda7581f85cf963043af98c927`.

Delivered:

- governed Edge Library with explicit scientific, capital and activation states;
- variance risk premium marked **defined-risk only**;
- normalized IV versus forecast-RV diagnostics in variance units;
- read-only live diagnostics using Package B forecast tournaments plus approximately horizon-matched near-spot Theta IV;
- assumption-conditioned terminal P&L simulation for multi-leg option structures;
- optional jump-mixture scenarios;
- exact bounded/unbounded expiry loss detection;
- contract-multiplier-aware cash P&L/risk accounting;
- net expected P&L after costs/slippage under explicit assumptions;
- P&L percentiles, probability of profit/loss, VaR and CVaR;
- bankroll impairment and hard maximum-loss budget checks;
- conservative whole-structure sizing from maximum-loss budget;
- expected-P&L-to-max-loss and expected-P&L-to-CVaR compensation ratios;
- dedicated Edge Library & Risk Lab browser page;
- explicit `NONE_RESEARCH_ONLY` decision authority and no family activation.

Initial library includes VRP, IV-versus-forecast-RV, demand pressure, idiosyncratic volatility, momentum, variance seasonality, earnings/event volatility, dispersion and a separately governed 0DTE research concept. Internet strategies enter as `UNVERIFIED CLAIM` until independently reproduced.

## Package D — Calibration + Model Tournament + Prospective Shadow — COMPLETE / MERGED

Package D is merged to `main` at `2a8c7b3d06923a71078734e8986b4bae65b76773`.

Delivered:

- strict separation of `P(thesis correct)` from `P(trade profitable)`;
- Brier score, log loss, calibration-in-the-large, reliability bins and expected calibration error;
- paired incumbent/challenger Brier tournaments over common prospective observations;
- bootstrap uncertainty around paired score differences;
- explicit observation-count and independent-date sufficiency gates;
- robustness as a mandatory promotion-review input;
- `CONTINUE_SHADOW` versus `ELIGIBLE_FOR_PROMOTION_REVIEW` review states;
- read-only prospective/shadow runtime over the existing database;
- explicit visibility when immutable decision-time probabilities are missing rather than reconstructing them with hindsight;
- dedicated Calibration & Prospective Shadow browser page;
- no automatic promotion or broker authority.

## Package E — Decision Engine + Discipline Leakage — COMPLETE / MERGED

Package E is merged to `main` in PR #5 after a successful full Christiania Quality Gate.

Delivered:

- fail-closed `NO_TRADE`, `CONTINUE_SHADOW` and `ELIGIBLE_FOR_MANUAL_REVIEW` states;
- manual-review gates for defined risk, explicit family activation, calibration, robustness, sample sufficiency and tail compensation;
- ranking by evidence quality, calibration, robustness and risk compensation rather than win rate;
- explicit separation of model-approved versus discretionary/unapproved execution evidence;
- separate P&L and expectancy diagnostics for approved and discretionary behaviour;
- post-win discipline-leakage detection;
- strategy/model-failure versus operator-discipline-failure attribution;
- read-only runtime that refuses to infer missing approval provenance from ambiguous historical fields;
- dedicated Decision & Discipline browser page;
- no automatic execution authority.

## Package F — Casino + 0DTE Lab V1 — COMPLETE / MERGED

Package F is merged to `main` at `a0839f04119c42436f9f77d1c54c6cca2a39924f` after a successful full Christiania Quality Gate.

Charter: **Casino in spirit, quant in discipline.**

Delivered:

- explicit `CASINO_V1` namespace separate from the Main Engine;
- authority fixed at `RESEARCH_SHADOW_ONLY_NO_EXECUTION`;
- hard experiment loss budget using bankroll fraction and Casino capital cap;
- friction-adjusted effective maximum loss including transaction costs and slippage;
- 0DTE implied-versus-forecast variance comparison over remaining time;
- explicit jump variance, IV-skew and gamma/theta diagnostics;
- liquidity as an independent fail-closed gate;
- dealer-positioning inputs only when explicitly measured and sourced; otherwise `NOT_MEASURED_DO_NOT_INFER`;
- probability-weighted scenario EV after transaction costs/slippage;
- discrete loss CVaR and expected-P&L-to-max-loss diagnostics;
- read-only runtime counting existing same-session-expiration evidence;
- separate Casino 0DTE browser page;
- no edge-family activation, automatic promotion, live DB mutation or broker execution.

Spectacular historical returns and high win rate are not evidence of edge.

## Parallel infrastructure backlog

Keep this lane separate from intelligence work unless operational evidence makes it urgent:

- redesign burn-in so it cannot recreate the resource incident;
- redesign strict/deep backup verification independently from frequent health checks;
- external observability;
- offsite encrypted backup and restore maturation;
- optional secure browser edge;
- measure swap behaviour before changing host `vm.swappiness`.

## Near-term execution order

The A–F intelligence build is complete in GitHub. The next controlled step is:

**review merged B–F → one reviewed batch deployment to Hetzner → verify `christiania-status`/research health → continue prospective evidence accumulation → only then consider further promotion or new research packages.**

Production remains deliberately behind `main` until that deployment review occurs.