# P0: repair missing independently timestamped stock prices

## Production evidence as of October 24, 2026

A read-only production SQLite check of captured ThetaData market
snapshots from September 1 to October 23 established:
- SPY: 364 snapshots, 29 market sessions, **0** independently sourced
  stock prices (`underlying_source=UNKNOWN`).
- IWM: 366 snapshots, 29 market sessions, **0** independently sourced
  stock prices.

The existing Massive OPTIONS chain source permits a direct stock-price
receipt only when the chain includes `underlying_asset.price` AND a
nanosecond `last_updated` timestamp. Market data entitlements may omit
those fields. The production underlying read model cannot create
forecasts or validated expiry evidence from missing receipts.

Massive documents a separate Stocks API:
`GET /v2/snapshot/locale/us/markets/stocks/tickers/{symbol}`.
A qualifying `ticker.lastTrade` with `p` and `t` is an observable
trade, not a Greek-model spot. Its presence, recency and plan access
must be checked; delayed/free plans are not live evidence. See:
https://massive.com/docs/rest/stocks/snapshots/single-ticker-snapshot

ThetaData separately documents real-time stock snapshot trades,
but the locally running terminal returned HTTP **403** for a
single-symbol stock snapshot probe during this review. This is a
diagnostic observation, not a proven subscription determination.
See: https://thetadata.net/docs/operations/stock_snapshot_trade.html

## Implemented safe fallback

`MassiveClient.get_stock_ticker_snapshot` requests precisely one
valid stock symbol from Massive Stocks API. The parser
`massive_direct_stock_v1.py` requires:
- exact requested ticker identity;
- actual `lastTrade.p` finite positive price;
- `lastTrade.t` integer Unix **nanoseconds**;
- trade timestamp no later than the frozen Theta option-price cut;
- <=15 seconds difference to that cut;
- no missing-entitlement, missing-trade or delayed-only fallback.

`CHRISTIANIA_DIRECT_STOCK_SNAPSHOT_ENABLED=1` is the only switch that
permits the collector to issue this extra request, and only when the
original options-chain underlying reference did not qualify. **The
switch defaults OFF**. It must not be enabled in production before
provider entitlement, request quota and exact recent timestamps have
been independently verified.

The accepted source is `MASSIVE_STOCK_SNAPSHOT_LAST_TRADE`, explicitly
different from `MASSIVE_OPTION_CHAIN_UNDERLYING_ASSET_LAST`.
Both are direct stock-trade references and never ThetaData's
model-derived Greek underlying. Across the same common source
contract, this tag is recognized by:
- independent stock 15-second verification;
- seven-family strategy discovery;
- read-only chain and Trade Desk source coverage;
- prospective immutable candidate ledger;
- near-close sampled expiry reference evaluation.

A missed or unavailable response records a concrete source failure
and preserves the NO TRADE result. It does not alter a past snapshot,
create an inferred stock trade, backfill an earlier decision, or
change the automatic collector's normal behavior when disabled.

## Economics and forecasting implications

**No profitable trade has been established.** Getting a stock-price
receipt repairs prerequisite data provenance; it does not demonstrate
directional skill, volatility mispricing, edge over option market
pricing, executable spreads/depth or realized profits.

Before ranking live ideas, the system still needs:
1. enough independent **prior-only** market history to train and
   prospectively assess price and volatility forecast distributions;
2. independently evaluated forecasts with matched controls and
   calibration / economic significance testing (not three
   correlated option-surface fits counted as independent);
3. realistic Saxo package quote and depth, commissions, slippage,
   FX and taxes; 500 EUR bounded loss;
4. reproducible entry, management and exit plan with treatment of
   early closes and assignment;
5. prospective outcomes versus NO TRADE and alternative strategies.

The present model selection authority stays NONE and the front-door
dashboard stays NO TRADE when any of these controls fails.

## Release

No changes deployed. The live service is on schema v37, while the
trade-decision work is stacked behind draft schema-v38 PR #171.
Backup-recovery-point remains a blocker. Exact-main CI, a verified
schema-aware rollback copy, production-scale performance/locking
and guarded atomic deployment are required before activation.
