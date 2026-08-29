# Christiania Detectability / Power Study v0.1

Status: DESIGN ONLY — NOT AN EDGE TEST  
Date: 2026-08-28

## 1. Purpose

Before Christiania builds a serious model engine or scanner framework, determine
whether an economically meaningful trading edge could be distinguished from
noise at the scale we can realistically collect.

This study does **not** assume an edge exists.

Primary question:

> Given realistic dependence, heavy tails, transaction costs and achievable
> sample cadence, what minimum net economic effect could Christiania detect
> with useful statistical power?

If the answer is "only implausibly large effects", Christiania should not spend
months building models that cannot be validated.

---

## 2. Primary estimand

For defined-risk option trades, use a paired candidate-versus-control estimand:

    paired_edge_ru =
        candidate_net_pnl / candidate_max_risk
        -
        control_net_pnl / control_max_risk

where:

- `net_pnl` includes commissions, fees and a slippage assumption;
- `max_risk` is the maximum contractual loss for a defined-risk structure;
- candidate and control are selected from the same market snapshot whenever
  possible.

Primary estimand:

    E[paired_edge_ru]

This is measured in **risk units**.

Example:
0.03 RU means an average 3% of max-risk advantage versus matched control.

Why risk units rather than "% of premium"?

- option buying and option selling have different premium economics;
- defined-risk credit spreads have a max loss different from credit received;
- risk units provide one denominator across debit and credit structures;
- the EUR 500 bankroll makes capital-at-risk the economically relevant scale.

Undefined-risk positions are out of scope for the primary study.

---

## 3. Secondary estimands

Secondary only:

- unpaired mean net return in risk units;
- probability of positive net P&L;
- median paired edge;
- downside-tail difference;
- calibration error if a probabilistic model exists;
- drawdown and loss concentration.

Win rate is descriptive, not the optimization target.

---

## 4. Unit of independence

The default independent unit is **market session-day**, not option contract.

Multiple contracts from:

- the same underlying,
- the same session,
- neighboring strikes,
- neighboring expiries,

are strongly dependent.

Nominal contract count must never be reported as if it were independent N.

Christiania should report:

- nominal observations;
- number of session-day clusters;
- number of underlying-day clusters;
- estimated effective N.

Until multiple underlyings are introduced, the conservative approximation is:

    effective N ≈ number of independent session-days

not number of contracts.

---

## 5. Dependence model for simulation

Before sufficient empirical data exist, simulate stress cases rather than
pretending one correlation estimate is known.

Synthetic scenarios should vary:

### Within-session dependence

- 0.50
- 0.80
- 0.95

### Day-to-day regime persistence

Approximate with AR(1) / block dependence:

- weak persistence: 0.0
- moderate: 0.4
- strong: 0.8

### Tail behavior

Use Student-t innovations with degrees of freedom:

- 3
- 5
- 10

Gaussian assumptions are deliberately not the default.

---

## 6. Effect sizes to inject

The simulation should test paired net effects in risk units:

- 0.00 RU
- 0.01 RU
- 0.02 RU
- 0.03 RU
- 0.05 RU
- 0.10 RU

Interpretation for a trade with EUR 50 max risk:

- 0.01 RU = EUR 0.50 average advantage
- 0.03 RU = EUR 1.50
- 0.05 RU = EUR 2.50
- 0.10 RU = EUR 5.00

These are **net** effects after assumed costs.

---

## 7. Sample horizons

Evaluate realistic collection horizons:

- 20 session-days
- 40 session-days
- 60 session-days
- 120 session-days
- 250 session-days
- 500 session-days

This roughly spans one month to two years of trading days.

Do not count multiple contracts on one day as additional independent days.

---

## 8. Statistical decision rule

Preferred first implementation:

1. reduce observations to one paired mean per session-day;
2. estimate the overall mean paired edge;
3. construct a moving-block bootstrap confidence interval over session-days;
4. claim "detectable positive effect" only when the 95% CI lower bound is > 0.

Estimated power at a given true effect is:

    fraction of Monte Carlo experiments
    whose 95% CI lower bound is > 0

Target power:

- 80% minimum for planning;
- 90% desirable before treating a family as well established.

The study should also verify false-positive behavior at injected effect = 0.

If the nominal 5% test rejects far more than ~5% under the null, the inference
procedure is not trustworthy.

---

## 9. Multiple testing

The power study must model the search process, not only a single blessed rule.

For discovery involving `k` candidate-rule families:

- persist every tested family;
- use family-level false-discovery-rate control in discovery;
- confirmation is evaluated on later, untouched time periods;
- a rule that has seen confirmation data cannot return to discovery unchanged.

Preferred temporal split:

- discovery window first;
- freeze rule definition and hash;
- confirmation window later.

No random train/test split across the same market regime is considered a strong
confirmation design.

---

## 10. Costs and slippage

The study should separate:

1. gross statistical edge;
2. estimated transaction costs;
3. estimated slippage;
4. net economic edge.

Costs must be scenario parameters until we have sufficient empirical execution
evidence.

At minimum run:

- optimistic costs;
- central costs;
- pessimistic costs.

A "detectable" gross effect that disappears under central costs is not a
harvestable edge.

Saxo delayed / indicative quotes are not execution evidence.

---

## 11. Matched controls

Matched controls are central to Christiania's future experimental design.

For each candidate, select control(s) from the same snapshot before outcomes are
known, matching as closely as practical on:

- underlying;
- session date;
- DTE;
- absolute delta;
- option right;
- liquidity / spread regime where available.

The purpose is not to create a perfect counterfactual. It is to remove as much
shared market movement as possible so the estimand targets the candidate rule
rather than "AAPL went up that day."

Control-selection rules must be frozen and versioned.

---

## 12. Decision thresholds

These are planning thresholds, not declarations of truth.

### Proceed toward a serious edge model

If an economically relevant effect around 0.02–0.03 RU can reach ~80% power
within a realistically collectable horizon and central costs do not erase it.

### Proceed only with execution / data-quality infrastructure

If effects below ~0.05–0.10 RU are effectively undetectable at reachable N.

In that case Christiania may still be useful for:

- execution-cost measurement;
- data-quality monitoring;
- calibration research;
- learning.

But claims about small trading edges would be statistically out of reach.

### Abandon an edge family

A specific family should be abandoned or materially redesigned when:

- predeclared confirmation fails;
- central/pessimistic cost scenarios eliminate the effect;
- the required effective N is unrealistic;
- performance is concentrated in one regime or a tiny number of days;
- the apparent effect disappears after matched controls;
- the effect exists only after multiple unregistered rule changes.

---

## 13. What Cohort 001 contributes

Cohort 001 does not estimate edge.

It contributes:

- provider/data-quality reliability;
- actual chain sizes;
- missing-Greeks patterns;
- Saxo resolution behavior;
- spread / quote-quality observations;
- operational collection timing.

Those parameters inform later detectability simulations.

Cohort 001 must not be used as an outcome sample in an edge test merely because
it exists.

---

## 14. What data are still missing before empirical power estimation

We still need repeated outcome-bearing observations across session-days.

At minimum:

- frozen market snapshot at candidate/control selection time;
- future option/underlying observations at predeclared horizons;
- terminal or horizon P&L construction;
- costs/slippage assumptions;
- defined max risk;
- regime/date clustering metadata.

Until then, v0.1 simulation results are stress tests, not empirical power
estimates.

---

## 15. Implementation sequence

### Phase A — now

Build a synthetic simulator to test the framework itself.

It should:

- use heavy-tailed shocks;
- model session-level dependence;
- inject known effects;
- aggregate by day;
- estimate power;
- verify null false-positive rate.

### Phase B — after repeated snapshots exist

Replace synthetic distribution assumptions with block bootstrap/resampling from
Christiania's actual data.

### Phase C — before model engine

Freeze:

- primary estimand;
- cost scenarios;
- candidate/control matching;
- discovery/confirmation split;
- minimum effect worth detecting.

Only then build the first candidate rule.

---

## 16. Current conclusion

No conclusion about detectability is justified yet.

The correct output of v0.1 is a planning surface:

    effect size × session-days × dependence × tail severity -> estimated power

The most important quantity is not nominal N.

It is:

> How many genuinely independent market days are required to detect an effect
> large enough to matter after costs?
