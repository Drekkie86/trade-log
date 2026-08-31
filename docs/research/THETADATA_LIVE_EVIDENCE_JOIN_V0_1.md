# ThetaData live evidence join v0.1

Status: IMPLEMENTED SCAFFOLD — NOT LIVE-ADMISSION AUTHORITATIVE

This increment joins ThetaData quote and Greek evidence onto the
reference-first contract frame.

## Rules implemented

- canonical identity join across C/CALL and P/PUT
- duplicate ThetaData identities fail closed
- quote freshness is derived only from explicit `quote_age_seconds`
- Greek response timestamps do not certify quote freshness
- missing quote => quote freshness UNKNOWN
- `iv_error` is classified through the existing draft Greek-quality policy
- quote and Greek PRESENT/ABSENT states are persisted separately

## Deliberate boundary

The module does not calculate `quote_age_seconds` from raw timestamps.

ThetaData naive timestamp timezone semantics remain formally unverified,
so a caller must supply quote age only after that calculation is trusted.

The module also does not treat a GOOD iv_error as proof that a wing Greek
is economically reliable. Further quote/liquidity/parity checks remain
future admission criteria.

No live API call is made in this increment.
