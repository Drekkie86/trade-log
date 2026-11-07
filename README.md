# Christiania

Finds defined-risk US option trades whose expected profit survives the market's
own pricing, costs and a stress shock, and proves — or disproves — that they
make money by settling every recommendation at expiry.

Christiania never places orders. You re-price, trade and record fills yourself.

## The app

| Screen | What it answers |
|---|---|
| **Today's trades** | Which 7–45 day trades are worth taking right now, ranked by expected profit per dollar of tail risk |
| **0DTE** | Same for same-day / next-day SPY and QQQ expiries, kept separate |
| **Track record** | What every frozen pick earned versus what the engine predicted; your own recorded trades; the backtest |
| **System** | Is data collection, the Theta terminal, the engine, price history and the backtest in place |

## The pipeline (`src/engine`)

1. **Chain** – newest ThetaData snapshot per underlying (main lane) or a live
   0–1 DTE fetch (0DTE lane). Forward from put-call parity, implied vol and
   delta solved per contract (Black-76).
2. **Structures** – every credit spread, debit spread, iron condor and iron fly
   on a delta/width grid. All have bounded loss. A leg must have a bid of at
   least 0.05 and a spread no wider than 50 % of its mid; a leg whose quote age
   is unknown rejects the structure.
3. **Models** – per expiry:
   - *Market*: the risk-neutral distribution from the whole smile
     (Breeden–Litzenberger on a fitted smile). Under it every structure is worth
     about its market price, skew included.
   - *Vol forecast*: lognormal at an EWMA + GARCH(1,1) forecast of realised vol.
   - *Price history*: resampled historical returns (fat tails, skew).
   The two forecasts share the price history, so the lower of them is used.
   Events priced in the term structure (earnings) widen both forecasts; a single
   name with fewer than three expiries in the window is skipped because the
   event cannot be detected, and `CHRISTIANIA_EVENT_BLACKOUT` blocks named dates.
   For 0DTE the forecasts are built from remaining-session intraday returns.
4. **Score** – P&L at expiry after slippage and commission under a blend of
   forecast (`CHRISTIANIA_FORECAST_WEIGHT`, default 50 %) and market views.
   A trade passes when both forecasts and the blend are positive, the blend is
   at least $5 and at least 3 % of the expected loss in the worst 5 % of
   outcomes (CVaR95). Ranking is blend EV / CVaR95. Each card also shows the
   EV under each view, under a stress shock (3 % chance of −10 %), the chance
   of the full loss and the chance of any profit.
5. **Freeze** – the first scan at or after 10:00 New York each session freezes
   one pick per underlying (at most 5; 0DTE 3). Later scans refresh the screen,
   not the ledger.
6. **Settle** – at expiry, at the ThetaData EOD close. Settlements within 0.1 %
   of a short strike or on an after-hours print are flagged.
7. **Track record** – scored by expiry day with a cluster bootstrap; no verdict
   before 60 expiry days and a backtest through a volatility shock. Your
   recorded trades (real fills) sit next to the modelled ones, with open risk.

The engine runs inside the daemon after every collection cycle
(`src/engine/worker.py`); a failure there never stops data collection.

## Backtest

```powershell
python run_engine_backtest.py --start 2023-07-03 --symbols SPY,QQQ,IWM,AAPL,MSFT,NVDA
```

Runs the same scan on each session's end-of-day option chain, freezes one pick
per underlying, settles at expiry, and writes `summary.json`, `picks.csv`,
`daily_pnl.csv`. Payloads are cached, so re-scoring with other settings does
not refetch. Point `CHRISTIANIA_BACKTEST_SUMMARY` at the summary to show it in
the app. Do this before trusting the live record.

## Settings

See `deploy/christiania.env.example`: commission per contract (default the
Saxo Classic USD 2.00), slippage, forecast weight, earnings blackout, 0DTE
symbols and on/off switch, open-risk cap, backtest summary path,
`CHRISTIANIA_ENGINE_DISABLED`, and `CHRISTIANIA_COLLECTOR_ONLY` (daemon persists
snapshots only, skipping the retired research stages).

## Known limits

- The edge is a volatility forecast against the market's pricing. Blending with
  the market view and the stress column make that explicit; the backtest and the
  track record are the only judges.
- American early assignment is not modelled. Follow the expiry-day rule on the
  card (close any spread whose short strike is within 1 % of the price by
  15:30 New York) or trade cash-settled index options.
- Main-lane quotes can be up to ~60 minutes old (12 of 48 symbols refreshed per
  15-minute cycle). Use "Re-price on live quotes" before you place the order.
- The intraday bars for the 0DTE lane need the ThetaData stock OHLC endpoint
  (Value tier and up); without them the lane says NO TRADE.
- Settlement uses the ThetaData EOD report close; compare it with the official
  close for a week before trusting pin-adjacent outcomes.

## Local operation

```powershell
python run_theta_probe.py
python run_christiania_app.py
python run_christiania_daemon.py
python christiania_health.py
python christiania_ops.py status
```

Operations, release and backup tooling are unchanged; see `docs/V1_ARCHITECTURE.md`
and `docs/operations/`. The hostile review of the engine and its fixes:
`docs/reviews/HOSTILE_REVIEW_ENGINE_V1_2026-11-07.md`.

## Archive

Research tooling that the app no longer uses lives in `archive/` with its
history intact (see `archive/README.md`).
