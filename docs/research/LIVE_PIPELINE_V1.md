# Live Pipeline v1 — structural admission

This increment begins the production live pipeline without yet surfacing
trade candidates.

Pipeline:

`Massive reference frame`
→ `ThetaData live quote rows`
→ `ThetaData live first-order Greek rows`
→ `per-contract quote age`
→ `quote/Greek identity join`
→ `structural admission diagnostics`

## ThetaData timestamp interpretation

ThetaData's current documentation describes option snapshot cache behavior
and time-of-day semantics in Eastern Time. Christiania therefore interprets
naive ThetaData option market timestamps as `America/New_York` for quote-age
calculation.

Raw provider timestamps remain preserved separately. Future provider changes
can therefore be reinterpreted without losing source evidence.

The conversion fails closed if a quote appears materially in the future.

## Structural admission

`STRUCTURALLY READY` currently means only:

- reference identity exists;
- quote observation exists;
- quote freshness is FRESH under the existing draft threshold;
- Greek observation exists;
- Greek quality is not BAD/UNKNOWN under the existing draft `iv_error` policy.

This does **not** mean:
- candidate;
- edge;
- executable;
- liquid;
- economically attractive.

Spread/liquidity/parity/solver sanity and scanner-family rules remain separate
future gates.

The included live probe is read-only and does not persist data or create
shadow candidates.
