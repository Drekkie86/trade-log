# Research Cycle v1

`run_christiania_cycle.py` is Christiania's first single-command research
orchestrator.

It executes:

1. independent market-evidence acquisition and persistence;
2. deterministic structural/tradability filtering from the persisted run;
3. deterministic local-IV hypothesis evaluation and persistence.

Default:

```powershell
python .\run_christiania_cycle.py
```

Default universe:

- AAPL
- JPM
- XOM
- 7–45 DTE

## Why this matters

The individual stages remain separate and testable, but Christiania can now be
run as one research process instead of a sequence of manual commands.

This is the form that can later be scheduled.

## Safety boundary

The cycle performs no:

- shadow-candidate admission;
- Saxo activity;
- order creation;
- live trading;
- ML prediction;
- edge declaration.

A surfaced local-IV observation remains empirical research evidence.

The next layer is the explicit bridge from a surfaced empirical anomaly to a
defined-risk shadow candidate. That bridge must not guess a trade structure:
the current `LOCAL_IV_RESIDUAL_V1` finding says only that local implied
volatility differs from neighboring contracts.

This distinction prevents Christiania from silently turning a descriptive
surface anomaly into a directional or volatility trade thesis.
