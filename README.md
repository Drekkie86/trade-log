# Christiania

Finds defined-risk US option trades that pay the seller after the market's own
pricing, costs and a stress shock, and proves — or disproves — that they make
money by settling every recommendation at expiry.

Christiania never places orders. You re-price, trade and record fills yourself.

## The app

| Screen | What it answers |
|---|---|
| **Today's trades** | Which 7–45 day credit trades are worth taking right now, ranked by expected profit per dollar of tail risk |
| **0DTE** | Same for same-day / next-day SPY and QQQ expiries, kept separate (parked by default; no backtest covers it) |
| **Track record** | What every frozen pick earned versus what the engine predicted; your own recorded trades; the backtest and its out-of-sample verdict |
| **System** | Is data collection, the Theta terminal, the engine, price history and the implied-vol history in place |

## The pipeline (`src/engine`)

1. **Chain** – newest ThetaData snapshot per underlying (main lane) or a live
   0–1 DTE fetch (0DTE lane). Forward from put-call parity, implied vol and
   delta solved per contract (Black-76).
2. **Structures** – every put/call credit spread, iron condor and iron fly on a
   delta/width grid. All are net credits with bounded loss. A leg must have a
   bid of at least 0.05 and a spread no wider than 50 % of its mid; a leg whose
   quote age is unknown rejects the structure. The engine does not buy premium.
3. **Distributions** – per expiry:
   - *Market*: the risk-neutral distribution from the whole smile
     (Breeden–Litzenberger on a fitted smile). Under it every structure is worth
     about its market price, skew included.
   - *Real world*: the same distribution with its width scaled by √λ, where
     λ = realised variance / implied variance for this underlying over the
     trailing two years of matched 30-day windows (`engine_iv_history` against
     `engine_daily_closes`). λ < 1 is the variance risk premium a seller
     collects; at λ ≥ 1 nothing passes. A name needs 250 matched sessions
     before it can pass. The smile's shape is the market's; only its width is
     the engine's claim.
   Events priced in the term structure (earnings) are shown on the card;
   `CHRISTIANIA_EVENT_BLACKOUT` blocks named dates.
4. **Score** – P&L at expiry after slippage and commission under the real-world
   distribution. A trade passes when that expected profit is at least $5, is
   still positive with a stress shock (3 % chance of −10 %), and is at least 3 %
   of the expected loss in the worst 5 % of outcomes (CVaR95). Ranking is
   EV / CVaR95. Each card also shows the EV under the market's own smile (about
   minus costs), the stress EV, the chance of the full loss and the chance of
   any profit.
5. **Freeze** – the first scan at or after 10:00 New York each session freezes
   one pick per underlying (at most 5; 0DTE 3). A name with an unexpired pick
   is not scanned again until it settles: one open pick per name, never the
   same view stacked day after day. Later scans refresh the screen, not the
   ledger.
6. **Settle** – at expiry, at the ThetaData EOD close, in the strike units of
   the pick (splits handled). Settlements within 0.1 % of a short strike are
   flagged.
7. **Track record** – scored by expiry day with a cluster bootstrap, with the
   realised hit rate and full-loss rate against the predicted ones; no verdict
   before 60 expiry days. Your recorded trades (real fills) sit next to the
   modelled ones, with open risk.

The engine runs inside the daemon after every collection cycle
(`src/engine/worker.py`); a failure there never stops data collection. The
implied-vol history is backfilled a bounded number of EOD chains per step
(`CHRISTIANIA_IV_BACKFILL_PER_STEP`, default 120) and kept current afterwards.

## Backtest

```powershell
python run_engine_backtest.py --start 2024-07-15 --symbols SPY,QQQ,IWM,AAPL,MSFT,NVDA
```

Fetches the 400 calendar days before `--start` as implied-vol history (free
when the cache already holds them), then runs the same scan on each session's
end-of-day option chain with that session's λ, freezes one pick per underlying
(one open at a time), settles at expiry, and writes `summary.json`,
`picks.csv`, `daily_pnl.csv`, `scan_stats.csv`, `risk_premium.csv`. The summary
splits the picks at `--oos-start` (default 2025-01-01): the calibration window
the engine was designed against, and the out-of-sample window judged by the
pre-registered criteria (bootstrap lower bound > 0, hit-rate gap ≤ 5 points,
full-loss rate at most 5 points above predicted, ≥ 60 expiry days). A
single-slot account path (one position at a time) is reported alongside.
Payloads are cached, so re-scoring with other settings does not refetch. Point
`CHRISTIANIA_BACKTEST_SUMMARY` at the summary to show it in the app. Do this
before trusting the live record.

## Settings

See `deploy/christiania.env.example`: commission per contract (default the
Saxo Bronze USD 2.00), slippage, per-lot max loss, earnings blackout, 0DTE
symbols and on/off switch, implied-vol backfill budget, open-risk cap, backtest
summary path, `CHRISTIANIA_ENGINE_DISABLED`, and `CHRISTIANIA_COLLECTOR_ONLY`
(daemon persists snapshots only, skipping the retired research stages).

## Known limits

- The edge is the variance risk premium, measured per name as the trailing
  ratio of delivered to priced variance. It is a well-documented premium with
  a fat left tail: the stress column, the per-lot loss cap and the backtest
  through a volatility shock are what stand between you and that tail, and
  the out-of-sample window is the only judge.
- λ is one number per name, applied to the whole smile and to every horizon
  from 7 to 45 days (and to 0DTE, where it has not been tested). Earnings
  windows are inside it; they are not modelled separately.
- American early assignment is not modelled. Follow the expiry-day rule on the
  card (close any spread whose short strike is within 1 % of the price by
  15:30 New York) or trade cash-settled index options.
- Main-lane quotes can be up to ~60 minutes old (12 of 48 symbols refreshed per
  15-minute cycle). Use "Re-price on live quotes" before you place the order.
- Backtest decisions are taken at the close on EOD NBBO; live picks are frozen
  at 10:00 on snapshot quotes. The track record is the check on that gap.
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
and `docs/operations/`. The hostile review of the engine, the first backtest
that retired V1, and the V2 pre-registration:
`docs/reviews/HOSTILE_REVIEW_ENGINE_V1_2026-11-07.md`.

## Archive

Research tooling that the app no longer uses lives in `archive/` with its
history intact (see `archive/README.md`).
