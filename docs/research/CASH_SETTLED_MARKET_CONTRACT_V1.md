# Christiania Cash-Settled Market Contract V1

Package 12 introduces a fail-closed provider-capability contract for the V1 cash-settled research universe.

## Scope

- XSP is the primary V1 live-contract target.
- SPX remains a research target, but SPX product-family identity alone is insufficient because standard SPX and SPXW use different settlement conventions.
- No broker-order path is introduced.
- Provider capability evidence does not enable scientific decision governance.

## Product semantics

Cboe product specifications are the authoritative source for the static product contract. Christiania records: cash settlement, European exercise, $100 multiplier, and settlement convention. XSP is PM-settled. Standard SPX is AM-settled; SPXW is PM-settled. Christiania fails closed when the exact SPX series root is unavailable.

## ThetaData proof ladder

1. `NOT_LIVE_PROBED` — no evidence file exists.
2. `REFERENCE_PROVEN` — ThetaData lists expirations for the requested product, but fresh live NBBO/timestamp semantics are not proven.
3. `LIVE_VALIDATED_XSP_ONLY` — XSP has a fresh, parseable NBBO quote and exact product semantics; other requested symbols remain blocked.
4. `LIVE_VALIDATED` — every requested product passes the live contract probe.

Reference proof is not sufficient for daemon collection.

## Operator commands

Reference probe (safe on non-session days):

```powershell
python probe_cash_settled_market_contract_v1.py --mode reference
```

Live proof (run during an active U.S. options session):

```powershell
python probe_cash_settled_market_contract_v1.py --mode live
```

Only after a live proof may the operator explicitly configure XSP/SPX research collection. The daemon also requires `CHRISTIANIA_ENABLE_CASH_SETTLED_RESEARCH=1`. Nothing is added silently.

## Evidence

Default path: `runtime_evidence/cash_settled_market_contract_v1.json`. This directory is ignored by Git. The evidence is operational capability evidence, not scientific observation data.
