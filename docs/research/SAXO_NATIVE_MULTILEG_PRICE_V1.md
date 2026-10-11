# Saxo native multi-leg package pricing — isolated price-only research adapter

**Gate:** #98 (validated shadow outcomes), with #96/#97 dependencies.
**Status:** unmerged research-only draft; no live provider request executed.

## Why this endpoint matters

Saxo's official developer portal documents a distinct **price snapshot**
endpoint:
  POST /trade/v1/prices/multileg
  https://www.developer.saxo/openapi/referencedocs/trade/v1/prices/post__trade__multileg

This requires Personal: Read (depending on authorized account) and returns
a BROKER-PRODUCED aggregate strategy quote with its component legs, provider
LastUpdated, price type, delay, price source, and optionally depth and
commissions. It is distinct from the order-placement endpoint:
  POST /trade/v2/orders/multileg
  https://developer.saxobank.com/openapi/referencedocs/trade/v2/orders/post__trade__multileg

NO code in this adapter calls the order endpoint. The read-only price
request is a POST because that is Saxo's documented pricing contract.
No subscription or broker session mutation is implemented here.

## Implemented V1: src/research/saxo_native_multileg_price_v1.py

- Off by default. No transport call or token retrieval until the
  caller explicitly sets allow_price_only_post=True.
- One price-only POST per experiment; URL strictly allowlisted to
  Saxo's existing live or SIM API base URL PLUS the exact
  /trade/v1/prices/multileg path. No caller-defined endpoint.
- 2–4 unique positive Saxo UICs, fixed option contract size per leg
  not assumed, 1–10 units per leg, exact entry BUY/SELL intent.
  Request body contains account key and Quote/InstrumentPriceDetails
  field groups, but the key and bearer token are NEVER returned,
  hashed, logged or included in exception messages.
- XNYS-only allowed session sampling window; Sunday and off-hours
  return immediately without token or HTTP requests.
- 8-second per-POST transport timeout; total request <=10s (fail
  closed otherwise); JSON response <=128 KiB; no retries.
- Validate response exact UIC/amount/side/asset-type set, avoid
  duplicate legs, market open and short-trade enabled. Require
  actual Saxo quote source, as-of timestamp within 15 seconds,
  realtime delay=0, Firm source type and Tradable bid/ask type.
- Price may legitimately be *signed* for net-credit strategies.
  Do not reject negative package values; require finite bid<=ask.
- Require package bid and ask size >=1 to mark the reference
  as independently depth-qualified. Saxo may omit these fields
  for multi-leg packages: in that case the status is explicitly
  UNVERIFIED_OR_UNAVAILABLE_PACKAGE_PRICE.
- Even the strongest valid output is BROKER_PACKAGE_PRICE_REFERENCE_ONLY.
  All outputs hard-code broker_package_fill_verified=false,
  outcome_eligible=false and trading_enabled=false. A price is
  not a fill; no P&L generated, no history rewritten.

## Verified by the current tests, not by a live broker response

The 13 new deterministic synthetic tests assert price endpoint-only URL
and body, exact leg matching, default-off behavior, Sunday/weekend guard,
missing size, delayed/stale/future quote, closed market, no account or
token leakage, signed credit spread quotes, no outcome eligibility,
and provider transport failure sanitization.

Documentation sample quotes may be old/indicative; existence of the
API is **not** evidence that Christiania's user account has OPRA live
prices, Saxo strategy trading rights, or package quoted depth.
Market entitlements and price semantics MUST be independently checked
against real data before any authorized live sampling.

## Remaining hard requirements to finish Gate C

- Verify CanParticipateInMultiLegOrder of the *actual* candidate
  OPRA option root, actual linked Saxo account and permissions.
  Official reference data exposes the flag, but it is not yet
  connected to this price-only adapter.
- Normalize and independently reconcile combination BUY/SELL and
  signed quote currency conventions, associated fee and margin data,
  quoted bid/ask size or request-for-quote conditions.
- Obtain a broker-confirmed *paper execution* or a separately
  defensible firm package quote at entry AND exit for matched,
  prospectively fixed instruments and quantity; do not invent a fill.
- Version and persist immutable source observations, all failed
  price requests and NO TRADE opportunities; source-side entry/exit
  quote quality, dates and user-imposed risk rules must be checked.
- True net EUR P&L and forward independent sample require full
  commissions, FX, applicable taxes, assignment/exercise, slippage
  and expiry settlement with independently validated source/time.
- PR #102 is a separate fail-closed entry gate, PR #103 provides
  offline paper-leg economics, PR #104 offers bounded Saxo leg
  lookup/depth with one shared option-space resolution. These are
  separate, unmerged drafts, with no production activation here.

**Do not merge, deploy, call this against a broker account, place an
order or score a trade without authorization and full gates.**
