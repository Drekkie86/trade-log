# Christiania Roadmap — authoritative current plan

Status baseline: the Control Plane Reset is complete in production at commit `fa5a3c645c6e752d8bfb354959fc1442e5ad6cd0`. Windows/GitHub is the source-of-truth workshop; Hetzner is an appliance-style artifact deployment target. The production status surface reports release identity, supervisor freshness, research progress, resource policy and core-service state together.

This document supersedes earlier package numbering where it conflicts with the current plan. Historical package documents remain evidence of what was built, not instructions for what comes next.

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

## Package A — Research Command Deck + Programme Family Governance

Goal: make the existing research programme legible and prevent multiplicity from outrunning the science.

- compose the existing runtime/read model into a dedicated Research Command Deck;
- expose daemon heartbeat, prospective accumulation, model freeze, hypothesis state, research funnel and shadow evidence;
- turn `PROGRAMME_FAMILY_BUDGET_V1.json` into a runtime-visible fail-closed gate;
- derive family usage from the append-only hypothesis log and observed runtime scanner families;
- keep p-values, FDR and decision use disabled unless persisted calibration evidence explicitly enables them;
- allow existing prospective research to continue while blocking unallocated new families.

## Package B — Forecasting + Surface Intelligence

Goal: strengthen the actual forecasting substrate before opening new edge families.

Build on the quant library already present in the repository rather than reimplementing it:

- realized-volatility forecast evaluation and uncertainty;
- forecast-vs-realized scoring by horizon/regime;
- surface-residual challenger diagnostics;
- incumbent/challenger prospective comparison;
- timing/data-quality conditioning;
- explicit forecast error bars for later edge ranking.

`LOCAL_SURFACE_QUADRATIC_V2` remains frozen unless prospective evidence supports promotion of a challenger.

## Package C — Edge Library V1 + Risk Mathematics

Goal: encode credible edge hypotheses while measuring the actual risk being purchased or sold.

Initial library:

- variance risk premium — **defined-risk structures only**;
- normalized IV versus forecast realized-volatility gap;
- demand pressure / intermediary constraints;
- idiosyncratic-volatility effect;
- option momentum;
- quarterly variance seasonality;
- earnings/event volatility premium.

Dispersion remains research-only and capital-incompatible with the current experimental bankroll. Internet strategies enter as `UNVERIFIED CLAIM` until independently reproduced.

The risk engine should quantify, where applicable:

- full payoff distribution;
- net expected value after costs/slippage;
- maximum defined loss;
- probability and magnitude of loss;
- expected shortfall / tail loss;
- Greeks and scenario sensitivities;
- jump/event exposure;
- model/parameter uncertainty;
- historical replay and Monte Carlo distributions;
- bankroll impairment / ruin metrics;
- conservative sizing candidates.

A high win rate is not an edge if the tail dominates. A trade with meaningful loss probability may still be rational when the loss is bounded and the compensation is adequate.

## Package D — Calibration + Model Tournament + Prospective Shadow

Goal: make models earn trust prospectively.

- track `P(thesis correct)` separately from `P(trade profitable)`;
- calibration curves and proper scoring rules;
- prospective incumbent/challenger tournament;
- robustness to worse assumptions and poorer fills;
- explicit sample/date sufficiency gates;
- immutable shadow decision-time records;
- outcome collection without hindsight contamination;
- formal promotion/demotion states.

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

**Research Command Deck / family governance → Forecasting / surface intelligence → Edge Library / risk mathematics → Calibration / model tournament / shadow → Decision / discipline → Casino / 0DTE.**

The target is to deploy these as large coherent packages over days while prospective calibration continues in parallel.
