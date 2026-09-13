# Christiania Roadmap — authoritative current plan

Status baseline: the Control Plane Reset is complete in production. Windows/GitHub is the source-of-truth workshop; Hetzner is an appliance-style artifact deployment target. Package A is deployed at `afc87be0d09202ba09f8c644c5942e5cfdd7850a`, with control-plane status `READY`, release identity PASS, research progress PASS and resource policy PASS 14/14. Packages B and C are merged to `main`; Package C merged at `3ffd7b09d59625dda7581f85cf963043af98c927`. The newer merged code awaits the next deployment cycle.

This document supersedes earlier package numbering where it conflicts with the current plan. Historical package documents remain evidence of what was built, not instructions for what comes next.

## Completed foundation and historical numbering

The earlier V1 sequence remains part of Christiania's implementation history. In particular, **Package 7 — Advanced Quantitative Model Library & Research Bench** delivered the serious pricing, volatility, scenario and model-disagreement foundations that the current intelligence roadmap now extends.

**Package 8 — clean-VM Release Candidate / Copenhagen acceptance** delivered the clean-host acceptance, deployment, reboot/recovery and burn-in framework that preceded the later Control Plane Reset. The current A–F package names below describe the next development pipeline; they do not erase or renumber completed historical work.

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

- a governed Edge Library with explicit scientific, capital and activation states;
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

Initial library:

- variance risk premium — `RESEARCHABLE_DEFINED_RISK_ONLY`;
- normalized IV versus forecast realized-volatility gap — `CORE_CANDIDATE_REQUIRES_FORECAST_MODEL`;
- demand pressure / intermediary constraints — `CANDIDATE_REQUIRES_DATA_BASELINES`;
- idiosyncratic-volatility effect — `CANDIDATE_REQUIRES_FACTOR_MODEL`;
- option momentum — `SHADOW_ONLY`;
- quarterly variance seasonality — `SHADOW_ONLY`;
- earnings/event volatility premium — `EVENT_RESEARCH`;
- dispersion — `RESEARCH_ONLY_CAPITAL_INCOMPATIBLE`;
- 0DTE — `CASINO_UNVERIFIED_UNTIL_PROVEN`.

Internet strategies enter as `UNVERIFIED CLAIM` until independently reproduced.

A high win rate is not an edge if the tail dominates. A trade with meaningful loss probability may still be rational when the loss is bounded and the compensation is adequate.

Package C's expected-P&L outputs are explicitly assumption-conditioned. They are not labelled alpha, forecast truth or trade recommendations.

## Package D — Calibration + Model Tournament + Prospective Shadow — ACTIVE BUILD

Goal: make models earn trust prospectively.

Package D builds on the existing prospective-freeze and shadow infrastructure and adds:

- strict separation of `P(thesis correct)` from `P(trade profitable)`;
- Brier score, log loss and reliability/calibration bins;
- calibration-in-the-large and expected calibration error;
- paired incumbent/challenger tournaments on common immutable observation keys;
- bootstrap uncertainty around paired Brier-loss differences;
- explicit observation-count and independent-date sufficiency;
- robustness as a mandatory promotion-review input;
- `CONTINUE_SHADOW` versus `ELIGIBLE_FOR_PROMOTION_REVIEW` states;
- read-only prospective/shadow runtime over the existing database;
- visibility of prospective dates, frozen hypotheses, shadow lifecycle and outcome marks;
- explicit reporting when decision-time probabilities were not immutably captured, rather than hindsight reconstruction;
- dedicated Calibration & Prospective Shadow browser page;
- no automatic model promotion or trading authority.

Existing p-value/FDR/admission/decision firewalls remain off unless separately governed.

## Package E — Decision Engine + Discipline Leakage

Goal: distinguish model quality from operator behaviour.

- `NO TRADE`;
- `CONTINUE SHADOW`;
- `ELIGIBLE FOR MANUAL REVIEW`;
- separate model-approved and discretionary trades;
- separate expectancy/P&L for approved versus unapproved behaviour;
- identify strategy failure versus operator failure;
- track discipline leakage after winning periods;
- rank opportunities by risk compensation, evidence quality, robustness and calibration rather than win rate alone.

## Package F — Casino + 0DTE Lab V1

Goal: permit deliberately high-variance research without contaminating Main Engine standards.

Charter: **Casino in spirit, quant in discipline.**

- tiny/capped risk allocation;
- hard maximum loss;
- separate statistics/evidence namespace;
- intraday implied versus realized volatility;
- gamma/theta interaction;
- skew and jump/event structure;
- liquidity/microstructure and transaction costs;
- scenario EV;
- dealer-positioning inputs only where measurable and appropriately sourced;
- `NO TRADE` remains valid.

Spectacular historical returns are not evidence of edge.

## Parallel infrastructure backlog

Keep this lane separate from intelligence work unless operational evidence makes it urgent:

- redesign burn-in so it cannot recreate the resource incident;
- redesign strict/deep backup verification independently from frequent health checks;
- external observability;
- offsite encrypted backup and restore maturation;
- optional secure browser edge;
- measure swap behaviour before changing host `vm.swappiness`.

## Near-term execution order

**Package A deployed → Package B merged → Package C merged → Package D Calibration / Model Tournament / Shadow → Package E Decision / Discipline → Package F Casino / 0DTE.**

The target is to deploy these as large coherent packages over days while prospective calibration continues in parallel.
