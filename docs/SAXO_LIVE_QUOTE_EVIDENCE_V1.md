# Saxo LIVE quote entitlement probe — P0 (2026-10-25)

## Why

Christiania already authenticates to Saxo LIVE and holds its rotating
OAuth credentials securely. This does **not** establish that the Saxo
LIVE account can retrieve **non-delayed US stock and OPRA options prices**.

Saxo documents:
- `GET /ref/v1/instruments` option-root discovery and
  `GET /ref/v1/instruments/contractoptionspaces/{OptionRootId}` contract UIC;
- `GET /trade/v1/infoprices` read-only stock and option InfoPrices;
- `Quote.DelayedByMinutes=0` is live-feed metadata;
- InfoPrices **are not executable prices**. Actual multi-leg package
  prices (including commissions/margin) are in the separate read
  `POST /trade/v1/prices/multileg` API. This feature does NOT invoke
  that API and cannot submit a trade.

References:
- https://developer.saxobank.com/openapi/learn/pricing
- https://developer.saxobank.com/openapi/referencedocs/ref/v1/instruments
- https://developer.saxobank.com/openapi/referencedocs/trading/v1/infoprices
- https://developer.saxobank.com/openapi/referencedocs/trade/v1/prices

## Exact live probe

`src/operations/saxo_live_quote_evidence_v1.py` samples the
predeclared `AAPL` OPRA option root (SPY/IWM may be passed explicitly).
It picks at most two deterministic monthly listed expiries 14–100 days
ahead and one near-stock-mid call; it does NOT optimize with historical
outcomes or select trading structures. Maximum provider requests are
one option root, two expiry spaces, one stock InfoPrice and one option
InfoPrice per sampled underlying. No account positions, orders,
balance, or personal identifiers are fetched.

**Outside the US regular 09:30–16:00 ET window, zero provider calls
are made** and the outcome is `MARKET_CLOSED_UNVERIFIED`.
Within session, both stock and option must independently show:

- Delay precisely 0 minutes (null and negative are UNKNOWN);
- a valid provider `LastUpdated` less than 15 seconds before decision
  time, no future material timestamps;
- `MarketState=Open` and continuous US session active;
- positive non-crossed bid/ask and bid/ask sizes;
- no `NoAccess`, `NoMarket`, `Pending` or other quote-level
  `ErrorCode`, no `OldIndicative` or expired/indicative-side claims;
- declared firm quote source for the strongest reference state;
- one sourced, positive option contract multiplier.

Failure states are retained rather than inventing prices:
`NO_OPTION_ROOT`, `NO_LISTED_SAMPLE`,
`PARTIAL_OR_UNVERIFIED`, `LOGIN_OR_PERMISSION_REQUIRED`,
`RATE_LIMITED`, `UNREACHABLE`, `DATA_SOURCE_FAILED`.

Even `LIVE_TWO_SIDED_REFERENCE` is **one reference sample**. It does
not authorize orders and cannot justify positive expectancy.

## Operational monitoring

The opt-in systemd service and timer:
- `christiania-saxo-market-data.service`
- `christiania-saxo-market-data.timer`

run once per hour. The service writes a small sanitized JSON record at
`/var/lib/christiania/data/saxo_feed_status_v1.json` with atomic
replacement and 0600 ownership. The System page reads only this local
report, never connects to Saxo while rendering. The report expires
after 85 minutes. Historical old reports never support a current
live market-data claim.

The System page shows a **separate** `Saxo stock/OPRA sample` status:
market closed, unknown, delayed, denied, or live sample. The separate
`Saxo market data` account-level row remains informational until
actual executable package pricing and entitlements are established.
The "Refresh deck" button clears the local reader cache.

This file is a **health diagnostic only**: it is not the immutable
prospective quote/signal ledger, does not contain the original option
quote IDs, is not historical return data, and must NEVER be accepted
by the unified decision engine as proof of executable bid/ask.

## Next necessary economic work

1. Confirm real-time stock and OPRA quote entitlements in a live
   US session, following a successful HTTP source sample.
2. Obtain and verify the broker's actual `POST /trade/v1/prices/multileg`
   read-only package prices, marginal credit/debit, commissions,
   margin, account currency, Fx impact, contract multiplier and any
   execution restrictions.
3. Compare **all** seven candidate payoff families using independent
   prior-only calibrated spot/volatility forecasts, a freeze-first
   ledger, Saxo package liquidity/costs, cash-at-risk capped
   to €500, and explicit NO TRADE. Do not count correlated implied
   volatility fits as independent predictive models.
4. Prospectively settle shadow selections and placebo/NO TRADE
   controls; track verified net economic P&L separately from
   theoretical Greeks and modeled terminal-price outcomes.

This release contains **no orders, no schema change, no unattended
trading permission and no claimed edge**.

## Release gates

Exact-main green GitHub CI, production-scale performance/preflight,
verified backup, no concurrent deployment, guarded atomically
activated no-schema release with automatic rollback. The timer is
enabled only after verifying production configuration and service
sandbox. It must not restart the research daemon if entitlement is
missing, and must never downgrade core supervisor health simply
because the US market is closed.
