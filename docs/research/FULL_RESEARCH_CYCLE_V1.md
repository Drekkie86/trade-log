# Full Research Cycle v1

This is Christiania's first single-command **end-to-end research-only**
orchestrator.

Command:

```powershell
python .\run_christiania_full_cycle.py
```

Default universe:

- AAPL
- JPM
- XOM
- 7–45 DTE

## Sequence

One invocation runs:

1. reference-first market evidence acquisition;
2. persistence of Massive/ThetaData evidence;
3. deterministic structural/tradability filter;
4. deterministic local-IV hypothesis scanner;
5. defined-risk structure proposal bridge;
6. ECB EUR/USD acquisition **only if a structure was proposed**;
7. EUR sizing and shadow-cost reserve;
8. deterministic shadow admission;
9. lifecycle transition to `SHADOW_TRACKED` for admitted research candidates.

## Important optimization

ECB FX is not fetched when there are no `PROPOSED` structures.

This avoids creating irrelevant FX observations and avoids turning an external
network dependency into a failure mode for otherwise empty research cycles.

## Safety boundary

Even when the full cycle admits a candidate:

`CANDIDATE — NOT VALIDATED FOR LIVE EDGE TRADING`

remains the exact label.

The full cycle does not:

- place a Saxo order;
- authorize live trading;
- claim validated edge;
- use ML;
- replenish the EUR 500 bankroll.

## Why this is a separate command

`run_christiania_cycle.py` remains the narrower evidence/hypothesis cycle.

`run_christiania_full_cycle.py` explicitly opts into the structure-proposal and
shadow-admission layers.

Keeping both commands makes the research boundary inspectable while providing
the one-command workflow needed for repeated autonomous database building.

## Next research-engine gap

Once this full cycle is proven during regular US market hours, the next major
missing component is **outcome collection** for `SHADOW_TRACKED` candidates:

- later quote snapshots;
- MFE / MAE;
- expiry/close result;
- realized payoff after the frozen cost model;
- score/calibration fields.

That is what turns repeated scanner outputs into evidence about predictive
quality rather than merely a collection of surfaced anomalies.
