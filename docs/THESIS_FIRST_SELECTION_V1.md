# Christiania: thesis-first multi-family selection — first implementation slice

**Status:** isolated research-only architecture, **not** production authority.
**Branch:** `feature/p0-independent-multifamily-discovery-20261024`
**Related:** P0 #167; draft #166 must not be merged as a separate competing gate.

## Why the original pipeline was incomplete

Current automatic production sequence is still:
Massive reference / ThetaData quotes+Greeks → structural screener →
local implied-volatility residual → **one long/reverse butterfly**
→ intrinsic shadow admission → opportunity score → shadow marks.
This is a model-discrepancy detector, not a multi-strategy forecast/decision
system. Repricing an anomalous strike with three correlated smile fits does
not establish independently predictable returns. A butterfly is a payoff
expression, not a market thesis.

The seven existing as-of family comparisons in `strategy_competition_v1.py`
are linked to the original butterfly. They are not independent discoveries
and have no approved predictive signals.

## Replacement direction

1. **Freeze a market thesis independently of the structure.**
   Supported *hypothesis categories* in the new contract:
   `DIRECTIONAL_UP`, `DIRECTIONAL_DOWN`, `LONG_VOLATILITY`,
   `SHORT_VOLATILITY`, `LOCAL_IV_CONVERGENCE`. These are categories,
   **not** automatically trusted forecasts.
2. Require source evidence, identity and timestamps, a strictly prior-only
   model and frozen forecast distribution, a predeclared exit, independent
   prospective outcomes and matched placebo calibration. Do not infer a
   probability distribution from a theoretical option price.
3. **Construct competing candidate structures directly from the frozen
   option chain**, without requiring a butterfly proposal:
   bull call spread, bear put spread, long straddle, long strangle,
   butterfly, iron condor, iron butterfly. Strike selection is
   deterministic adjacent-at-the-money geometry, **not** a claimed optimum.
4. Apply the **same** quote synchrony, multipliers, cost, capital and evidence
   gates for every structure. The hypothesis must be compatible with the
   structure. No unrelated thesis may lend a strategy its authority.
5. Compute an illustrative net expiry expectancy **only** when a frozen
   valid terminal distribution and enough cost evidence are supplied.
   Expiry intrinsic cannot substitute for a predeclared volatility-convergence
   early exit. Real broker execution remains distinct and unapproved.
6. Fail closed: `NO_TRADE` is not failure. At most the model returns
   `SHADOW_RESEARCH_ONLY_NOT_TRADING_AUTHORITY` when prospective,
   independently evaluated inputs qualify. There is **no** order pathway.

## What this slice really delivers

- `src/decision/thesis_first_selection_v1.py` — reusable selection
  contract with common evidence/reason codes; prospective placebo/exit,
  model-training, fee and payoff checks. No claim of edge.
- `src/research/independent_family_discovery_v1.py` — independently
  constructs up to seven option families from one immutable chain.
  Requires independently timestamped Massive stock reference (15s),
  valid per-leg timestamps and recorded contract multipliers.
- `src/research/independent_family_read_model_v1.py` — bounded read-only
  adapter to the latest completed research run. No full historical scans,
  no schema changes, no writes.
- `tests/test_*thesis*selection*v1.py` and
  `tests/test_independent_family*py` — source failure, identity, leakage,
  payoff and family comparisons.

**Not yet delivered:** independent calibrated directional/volatility
forecasters; empirical model promotion; persisted immutable multi-family
prospective experiment ledger; exit-path valuation for early close; shared
authoritative candidate lineage across Trade Ideas / Shadow / Casino / Results;
live daemon switchover; broker fills or execution authority.

The read model intentionally is **not** invoked in the 15-minute daemon or
the Streamlit render path, to avoid unmeasured production load.

## Known production evidence constraints

Production audit of 19 October found 172 expired admitted butterfly candidates
without qualifying underlying snapshots, and independently priced stock
references absent from sampled research-run snapshots. The more recent UI
shows 169 model-only proxy outcomes (2 positive, 167 negative), which are
**not** validated performance. Do not bootstrap proof or forecasts from
these outcomes, and do not rewrite legacy candidates to manufacture wins.

Until a genuinely sourced, timely stock reference and prospectively frozen
strategy-specific forecasts exist, the new pipeline correctly emits no
authorized candidates. This is a dependency to repair, not a reason to
weaken the source clock or silently fall back to Theta's Greek-model spot.

## Sequencing after this slice

1. Hostile-review shared evidence invariants, complete production-scale
   read-model probes, and preserve the old candidate ledger unchanged.
2. Repair independent stock capture, with rejected-source reason counts.
3. Add genuinely independent prospective thesis generators and falsifiable
   model/control baselines. No fitting on the outcomes being scored.
4. Persist candidate/strategy/control decisions **before** the market outcome,
   including source quote IDs, exit rule, costs, symbol/expiry and study cohort.
5. Reuse one authoritative decision and outcome read model for all four pages.
6. Only then replace the automatic butterfly pipeline with a gated,
   reversible, auditable switchover. Require a valid backup, exact-main
   green quality gate, production-scale performance, and rollback proof.

## Test of success

The same market evidence yields the same gate and missing-source reasons
across Main Engine and Casino (even if loss caps differ). A model-only quote
cannot enter a validated outcome ledger on any page. A strategy with zero
measured predictive edge is explicitly labelled **unproven**, even when a
theoretical payoff profile is profitable. The system may reject every trade.
