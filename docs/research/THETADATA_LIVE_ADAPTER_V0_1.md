# ThetaData live adapter v0.1

This increment wires the existing ThetaData client to the live Standard
snapshot endpoints used in the 2026-08-31 market-hours validation.

Endpoints:
- `/option/snapshot/quote`
- `/option/snapshot/greeks/first_order`

The adapter normalizes identities and supports exact DTE filtering.

A read-only live probe compares:
Massive reference listing frame ↔ ThetaData quote rows ↔ ThetaData Greek rows.

The probe intentionally does not convert raw ThetaData timestamps into
quote age because the timezone semantics of naive provider timestamps
have not yet been formally verified.
