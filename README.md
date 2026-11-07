# Christiania

Finds defined-risk US option trades with positive expected value after costs,
and proves — or disproves — that they make money by settling every
recommendation at expiry.

Christiania never places orders. You re-quote and trade in your broker.

## The app

| Screen | What it answers |
|---|---|
| **Today's trades** | Which 7–45 day trades are worth taking right now, ranked by expected profit per dollar at risk |
| **0DTE** | Same as above for same-day / next-day SPY and QQQ expiries, kept separate |
| **Track record** | What every recommended trade actually earned, versus what the engine predicted |
| **System** | Is data collection, the Theta terminal and the engine running |

## The pipeline (`src/engine`)

1. **Chain** – newest ThetaData snapshot per underlying (main lane) or a live
   0–1 DTE fetch (0DTE lane). Forward from put-call parity, implied vol and
   delta solved per contract (Black-76).
2. **Structures** – every credit spread, debit spread, iron condor and iron fly
   on a delta/width grid. All have bounded loss.
3. **Models** – three terminal-price distributions per expiry:
   - *Implied*: lognormal at the expiry's ATM IV. The market's view — every
     trade is worth about minus its costs here. Benchmark, not a vote.
   - *Vol forecast*: lognormal at an EWMA + GARCH(1,1) forecast of realised vol.
   - *Empirical*: resampled historical h-day returns (fat tails, skew).
   Vol forecast and empirical share the price history, so they count as **one**
   evidence family. Events priced in the term structure (earnings) are added
   to both.
4. **Score** – hold-to-expiry P&L after slippage (half the half-spread per leg
   by default) and commission. **Conservative EV = the worse of the two
   forecast models.** A trade passes only when both are positive, the EV is at
   least $5 and at least 3% of max loss.
5. **Rank & freeze** – best per underlying first; the top 5 (0DTE: top 3) are
   frozen as picks the first time they appear in a session.
6. **Settle** – at expiry, at the ThetaData EOD close (intrinsic value). The
   track record is built only from these frozen picks.

The engine runs inside the daemon after every collection cycle
(`src/engine/worker.py`); a failure there never stops data collection.

Configuration (environment): `CHRISTIANIA_ZERO_DTE_SYMBOLS`,
`CHRISTIANIA_SLIPPAGE_FRACTION`, `CHRISTIANIA_COMMISSION_PER_CONTRACT`,
`CHRISTIANIA_ENGINE_DISABLED`.

## Known limits

- The edge is a volatility forecast. If realised volatility beats the forecast,
  the trades lose; the track record is the only judge.
- American early assignment on single-stock options is not modelled.
- Main-lane quotes can be up to ~60 minutes old (12 of 48 symbols are
  refreshed per 15-minute cycle). Always re-quote before trading.
- Settlement uses the ThetaData EOD report close, which can include an
  after-hours last trade.

## Local operation

```powershell
python run_theta_probe.py
python run_christiania_app.py
python run_christiania_daemon.py
python christiania_health.py
python christiania_ops.py status
```

Operations, release and backup tooling are unchanged; see `docs/V1_ARCHITECTURE.md`
and `docs/operations/`.

## Archive

Research tooling that the app no longer uses lives in `archive/` with its
history intact (see `archive/README.md`).
