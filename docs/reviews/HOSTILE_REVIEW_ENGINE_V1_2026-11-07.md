# Hostile review: Christiania trade engine v1 (PR #184)

Date: 2026-11-07. Scope: everything between a scan and a real trade — the engine
(`src/engine`), the data that feeds it, the daemon and VM it runs in, the four
screens, and the economics of the bet itself. Reviewer: Claude, which also wrote
the code under review; every finding below is backed by a reproduction
(`probe_engine_v1_2026-11-07.py` in this folder, output in the `.out` file next
to it) or a cited source, not by opinion.

Severity: **BLOCKER** = betting money on the output would be wrong or unverifiable;
**MAJOR** = materially wrong or risky, output still partly informative;
**MINOR** = robustness or cosmetics.

## Verdict

Do not bet money on the engine's output as it stands.

The engine is a clean harness. The signal inside it is the generic short-volatility
premium (implied volatility above a realised-volatility forecast), scored without
the crash risk that premium pays for. Nothing in the repository has ever run on a
real chain, the track record overstates its own evidence by construction, two
gates fail open, and the broker's actual costs and mechanics are not in the model.
The good news: every blocker below has a concrete fix and the most important one
(a backtest) is feasible with the data subscription you already have.

## Fixes applied (same day, same PR)

Every finding below was addressed in code on 2026-11-07; the "after" numbers come
from `probe_engine_v1_2026-11-07_after_fixes.py` (output in the `.out` file next
to it), the same synthetic scenarios as the original probes.

| ID | Fix | Before → after |
|---|---|---|
| B1 | Score = blend of forecast and **smile-implied** market view (`CHRISTIANIA_FORECAST_WEIGHT`, 0.5); market view built from the whole smile (Breeden–Litzenberger), so skew is priced; stress column (3 % × −10 %); rank by EV / CVaR95; card shows every view | IV 18 %: 86/273 pass → 2/252; skewed chain top pick +$77 forecast-only → blend +$28 with market view −$16 shown; a skewed put spread's market-view EV +$4.9 (ATM lognormal) → −$4.8 (smile) |
| B2 | One frozen pick per underlying per session at the first scan ≥ 10:00 NY; cluster bootstrap by expiry day; verdict needs 60 expiry days; max drawdown and worst day shown; "95 % confidence" wording gone | 12 picks per session per underlying → 1; 30 trades over 6 days → "Too early to judge" |
| B3 | EOD history chunked ≤ 360 days; `history_status` on the System page; settlement records after-hours and near-strike flags; backtest harness `run_engine_backtest.py` + `src/engine/backtest.py` (cached, resumable, writes summary/picks/daily P&L; shown on Track record and System) | fetch of 760 days → 3 requests; backtest exists, not yet run (needs your Theta Terminal) |
| B4 | Commission default USD 2.00 (Saxo Classic); expiry-day exit rule on every card; "I took this trade" records real fills; trades settle or close by hand; exposure shown | modelled 0.65 → 2.00; assignment risk stated where the order is placed |
| M1 | Liquidity gate: bid ≥ 0.05 and relative spread ≤ 50 % per leg; OI gate off (feed carries none) | 23 passers with 0.01 × 0.06 wings → 0; `liquid()` → `NO_REAL_MARKET` |
| M2 | Unknown quote age rejects (`QUOTE_AGE_UNKNOWN`); card says "quote age unknown" | garbage/NULL timestamps: 224 pass → 0 |
| M3 | Card shows EV under forecast, price history, market, blend and stress; break-even realised vol unchanged (the maths was right; the display was not) | P7 fly: card now shows +$83 / −$16 / blend +$33 / stress +$75, P(max loss) 29 %, win 54 % |
| M4 | Rank by blend EV / CVaR95 (tail floor 10 % of max loss); P(max loss) shown | top-5 now carries P(max loss) 17–68 % explicitly |
| M5 | `engine_trades` with real fills; open risk by name group (index/sector ETFs count as one); `CHRISTIANIA_MAX_OPEN_RISK_USD` cap warns on the card; sidebar shows open risk | none → exposure accounting |
| M6 | `CHRISTIANIA_COLLECTOR_ONLY=1`: daemon persists snapshots and quotes only (`src/research/collector_cycle.py`), same tables, same iteration bookkeeping; default off until one session in shadow | optional decoupling, tested |
| M7 | Single names with < 3 expiries in the window are skipped (`EVENT_UNDETECTABLE`); `CHRISTIANIA_EVENT_BLACKOUT=SYM:date` blocks named dates; ETFs exempt | 2-expiry single name: 0 pass, blocked |
| M8 | Real-trade recording and manual close; fill vs modelled fill on the Track record | none → recorded |
| M9 | 0DTE forecasts from remaining-session intraday returns (5-minute bars, `engine_intraday_sessions`), fail-closed when fewer than 40 sessions; `CHRISTIANIA_ZERO_DTE_ENABLED=0` parks the lane | close-to-close scaling → intraday returns |
| m1 | "Re-price on live quotes" on every card: same structure, live chain, same models and gates | none → live re-score |
| m2 | `after_hours` and `near_strike` recorded per settlement and flagged on the Track record | — |
| m3 | Gap-fill from intraday snapshot prices removed; candidates of non-decision scans pruned after 30 days; "Show all N" label fixed; reason text rewritten; V1 docs marked superseded | — |

### Still open, because the facts are yours

Confirmed 2026-11-07 (Step 4 of the handover): Saxo Bronze, USD 2.00 per contract (matches
the default), real-time OPRA Level 1 active (the delayed-quote concern in B4 is closed);
ThetaData options Standard, stock FREE.

* **Saxo Advanced profile — hard prerequisite.** Options appropriateness test not taken,
  Advanced margin profile and short-option writing permission not verified, published minimum
  capital USD 5,000 (Belgian applicability unverified). Every structure the engine surfaces
  contains a short leg; on the basic profile none of them can be placed. Nothing goes live
  before this is done, and the exposure cap should be set against that capital.
* **ThetaData stock FREE** means EOD closes from 2023-06-01 (settlement and the main-lane models
  work; the backtest's models become available about three months after that date) but no
  intraday bars: the 0DTE lane is parked (`CHRISTIANIA_ZERO_DTE_ENABLED=0`) until the stock
  subscription is Value or higher. The FREE tier's one-day delay is harmless for the models;
  settlement of a Friday expiry may land on Tuesday instead of Monday.
* **First live run (2026-11-07, commit 7168d89) found one more bug.** The terminal probes
  confirmed the 365-day cap (HTTP 400) and that stock OHLC needs the Value tier (HTTP 403);
  the stock EOD report fields are `close`, `created` (17:15 NY), `last_trade`, bid/ask, OHLC,
  and `close` matched neither the 17:15 bid nor ask, consistent with an official close. The
  backtest skipped every symbol: the history window reached back to 2021, before the FREE tier's
  first served date, and one rejected chunk failed the whole fetch. Fixed in `fcf5b6c`+:
  the window is clamped at `CHRISTIANIA_STOCK_HISTORY_FIRST_DATE` (2023-06-01), a rejected
  chunk no longer discards the others, 429s are retried with backoff, stock requests are paced
  at 2.1 s for the 30/min limit, and the skip line now prints the terminal's message.
* **Run the backtest** (`run_engine_backtest.py`, needs the Theta Terminal). Until the curve
  through August 2024 and April 2025 exists, nothing above changes the verdict. If the options
  Standard history reaches back before 2023, a later version can derive the stock series from
  the chains' parity forward and extend the test through 2020 and 2022.
* **Confirm on day one**: closes arrive (System → Price history), the first expiry settles,
  `close` matches the official close for a week.
* The pass rate is still a function of IV − forecast (P2 after): that is the strategy, now
  priced honestly, not a bug the code can remove.

## First backtest: partial window, negative (2026-11-07 evening)

Six symbols (SPY, QQQ, IWM, AAPL, MSFT, NVDA), commit `7a9b7d6`, one lot per pick.
The run only covered **September 2023 to February 2024**: the Theta Terminal's session
expired part-way (HTTP 478) and the harness treated every later request as "chain
unavailable" and raced through 4,264 empty sessions; the stock history also stopped at
2026‑05‑15 because the last chunk asked for dates in the future. Within the window that ran:

| | |
|---|---|
| Settled picks | 406 (debit spreads 319, iron flies 55, condors 28, credit spreads 4) |
| Realised P&L | **−$7,376** on $79,127 at risk (−9.3 % return on risk) |
| Model predicted | **+$7,898** |
| Hit rate | 26.6 % observed vs 36.3 % predicted |
| Max drawdown | −$18,997; worst day −$5,199; worst month Dec 2023 −$10,913 |
| Bootstrap 95 % (by expiry day) | −$60 to +$33 per trade |

Reading it honestly:

* The predictions were biased upward by about $15,000 over 406 trades, in the
  direction the review warned about. The forecast models at that point had 3–8 months of
  closes (the FREE tier starts 2023‑06‑01) and the minimum was 60 returns: GARCH on 60
  points is noise. The minimum is now 250 returns (a year) and 200 empirical windows,
  which moves the first possible pick to about June 2024.
* Debit spreads dominated because the short-history models called realised volatility
  high relative to the market; those trades netted −$939, i.e. costs, with a few very large
  NVDA winners and losers. Iron flies lost −$4,289 on 55 trades. Nothing in the window
  showed an edge in either direction.
* Ten picks had a max loss above $500 (largest $772): strike steps on high-priced names
  produce wide spreads in dollars. A per-lot gate (`CHRISTIANIA_MAX_LOSS_PER_LOT_USD`,
  default 500, rejection `MAX_LOSS_TOO_LARGE`) now applies in the engine and the backtest.
  Against a €500 bankroll that gate belongs at $100–150, which excludes most single names.
* The window is five months of a strong rally with falling volatility and the statistics
  are not distinguishable from zero. It is one failed sample, not a verdict on the full
  period — but it is the only sample, and it points the wrong way.

Harness fixes in the same commit: a dead terminal (478, connection errors) now pauses
and retries three times, then aborts with a clear message and keeps the cache; 25
consecutive chain failures abort too; the stock-history window is clamped at today and
skipped chunks are printed; `summary.json` carries a `coverage` block (sessions with chains,
failures, first/last pick, abort reason) and predicted EV and return on risk per family.

Next: rerun the six-symbol backtest from cache (the 788 chains are kept), then the full
universe; decide with the curve from June 2024 through April 2025 in hand.

## Findings

| ID | Severity | Finding |
|---|---|---|
| B1 | BLOCKER | The score is the variance risk premium measured as mispricing: 100 % of passing trades are short volatility; pass/fail reduces to "IV > forecast"; the only distribution with a crash in it (implied) is excluded from the score |
| B2 | BLOCKER | The track record cannot validate the engine: pick churn (12 picks from one underlying in one session), correlated picks (30 trades ≈ 9 independent), normal CI on bimodal P&L (false "95 % confidence" 10 % of the time at zero edge), and by construction no tail until the tail happens |
| B3 | BLOCKER | Never backtested; settlement and model history depend on an endpoint never exercised on this account; the first history backfill asks for 760 days where ThetaData documents a 365-day cap per request, so history may never arrive and nothing will ever pass |
| B4 | BLOCKER | Broker reality absent: Saxo Classic charges USD 2.00 per contract (modelled 0.65); writing options needs the Advanced margin profile; US equity options are physically delivered, so "hold to expiry" can assign the short leg while the long leg expires worthless; Saxo quotes are 15-minute delayed without a real-time OPRA subscription |
| M1 | MAJOR | No working liquidity screen: open interest is stored as NULL for every quote (gate is a no-op) and the spread gate passes 0.01 × 0.06 wings (143 % relative spread) |
| M2 | MAJOR | Staleness gate fails open: unparseable or NULL quote timestamps make every structure pass with no warning |
| M3 | MAJOR | EV is a near-linear function of (IV − forecast vol); 2 vol points of forecast error erase the edge (break-even realised vol 23 % against 25 % implied); the forecast has no jump component and the price history available starts June 2023 |
| M4 | MAJOR | Ranking by EV / max loss ignores loss probability; iron flies with a 24–38 % chance of max loss rank first |
| M5 | MAJOR | No portfolio exposure accounting; "lots in limit" encourages per-trade sizing into 50+ overlapping short-vol positions |
| M6 | MAJOR | The engine's data supply sits at the end of the legacy research cycle (hypothesis scanner, structure bridge, shadow admission, unified capture); any failure there starves the engine and ~140 unmaintained modules stay on the critical path |
| M7 | MAJOR | Earnings detection is blind for chains with ≤ 2 expiries in the 7–45 day window |
| M8 | MAJOR | No way to record a real trade (trade service archived); modelled fills can never be compared with real fills |
| M9 | MAJOR | 0DTE lane models intraday moves with close-to-close returns (overnight gap included, intraday vol shape ignored); its numbers are not trustworthy in either direction |
| m1 | MINOR | No re-score at execution time; an hour-old quote moves the edge by ~$6–10 per lot per vol point (about 10 % of the stated EV) |
| m2 | MINOR | Settlement `close` may be an after-hours print; pin-adjacent picks can settle on the wrong side of a strike |
| m3 | MINOR | Close history gap-filled with intraday snapshot prices; scan tables grow ~3 MB/day with no retention; "Show all 20" label while 665 passed; tautological reason text; hard-coded 4 % rate; 24 unvalidated constants |
| — | tested, not a finding | Winner's curse from quote noise: ±1 tick noise biases the top-5 EV by +$1 on $62. Negligible at that noise level |

---

### B1 — The score is the risk premium, measured as mispricing

**Evidence** (`probe.py` P2, synthetic chain, price history with 15 % realised vol, forecast ≈ 14–17 %):

```
IV 14%:    0 / 221   (nothing passes)
IV 16%:    4 / 244   short-vol share 100%
IV 18%:   86 / 273   short-vol share 100%
IV 20%:  140 / 282   short-vol share 100%
IV 25%:  224 / 328   short-vol share 100%
IV 30%:  238 / 337   short-vol share 100%
```

Pass rate is a step function of the IV − forecast gap and every passer sells
premium. The question you asked ("can the four families reinforce each other?")
has an empirical answer: in practice the engine finds one trade, short vol, and
picks whichever family packages it with the smallest max loss (M4).

With skew (P3: 25-delta put IV 28.6 %, ATM 22.3 %, calls 21 %) the top 20 are 18
iron condors and 2 flies: the engine sells the put skew. Under a world with the
same diffusion plus a 4 % chance of a −12 % move before expiry, the engine's +$77
becomes +$27, and P(loss > $100) is 26 %.

The literature says the gap is real and is compensation. Carr and Wu find
variance risk premia "strongly negative for the S&P 500 and 100 indexes" and for
individual stocks "also negative, but with a smaller absolute magnitude"; they
conclude the variance market is either inefficient or "the majority of the
variance risk is generated by an independent risk factor, which the market prices
heavily" ([Carr & Wu, Variance Risk Premia](https://econwpa.ub.uni-muenchen.de/econ-wp/fin/papers/0409/0409015.pdf)).
Bollerslev and Todorov attribute on average more than half of the observed
variance risk premium to disaster risk ([Tails, Fears and Risk Premia](https://typeset.io/pdf/tails-fears-and-risk-premia-5bj5imi8tx.pdf)).
A practitioner summary puts the SPX 30-day gap at roughly 2–4 vol points and
calls it compensation for variance-shock tail risk, not free money
([optionsanalysissuite](https://www.optionsanalysissuite.com/documentation/variance-risk-premium)).

The engine's "conservative EV" is the worse of two forecast models that share the
same price history and the same blind spot (no jumps). The minimum of two
optimistic numbers is optimistic.

**Smallest fix.** Score under a mixture: P&L distribution = w · forecast + (1 − w) ·
implied, start w = 0.5, require EV > 0 under the mixture. On P7's top fly that
turns +$57 (17 % realised) and −$14 (25 % implied) into about +$21: the trade still
passes, most marginal ones stop passing. Add a stress column: EV with a 3 %
probability of a −10 % jump. Let the track record calibrate w.

**Regression test.** At IV − forecast = +2 vol points and a flat skew, fewer than
10 % of structures may pass; at +0 none.

### B2 — The track record cannot validate the engine

**Pick churn** (P1): one underlying, seven scans fifteen minutes apart, spot
drifting 100.0 → 100.6, IV constant: **12 distinct frozen picks** in one session
(each scan froze 5; the union is 12). Picks are keyed on exact strikes, so every
small move in the forward creates "new" trades. Production has 48 underlyings and
~25 scans per session; the daily pick count will be tens of near-duplicates of
the same bet. `Recommended: 5` on the Track record screen is a per-session
artefact of the seed, not what production will show.

**Correlation** (P10): 5 picks per day with within-day correlation 0.6 have a
design effect of 1 + 4 · 0.6 = 3.4, so "30 settled trades" is about 9 independent
observations. Monte Carlo with the engine's own top-pick payoff (+$400 / −$200,
break-even win rate 33 %):

```
true win rate 33%, corr 0.0: verdict fires after 30 trades in  2% of worlds
true win rate 33%, corr 0.6: verdict fires after 30 trades in 10% of worlds
true win rate 30%, corr 0.6: verdict fires in 7% of worlds; next 90 trades -1472
```

The "making money with 95 % confidence" line is a 90 % statement at best, on a
bimodal distribution where a normal CI is wrong anyway.

**The tail** cannot be in the sample until it happens. Thirty settled trades in a
calm quarter will read "profitable with 95 % confidence" right up to the first
−8 % day, which hits every open position at once (P3, M5).

**Smallest fix.**
1. Freeze one pick per `(lane, session_date, underlying)` at the first scan after
   10:00 NY; later scans update the display, not the ledger.
2. Scorecard by expiry date: cluster bootstrap CI over expiry days, not trades.
3. Verdict requires ≥ 60 independent expiry days **and** a historical backtest
   spanning at least one volatility shock; show max drawdown and worst day, never
   a confidence statement from the in-sample mean alone.

**Regression test.** Seven scans with drifting spot produce exactly one pick per
underlying per session.

### B3 — Never backtested, and the data it depends on has never been fetched

* No part of the pipeline has run on a real chain. All numbers in this PR come from
  Black-76 synthetic quotes.
* Settlement and the two forecast models depend on `/v3/stock/history/eod`. The
  previous settlement path (`shadow_expiry_outcome_v1`) needed a FETCHED stock
  price between 15:45 and 16:00 NY; the daemon's sample window ends at close − 15
  min (`SESSION_EDGE_EXCLUSION`), so that path starved — the same starvation hits
  the engine's `SNAPSHOT_NEAR_CLOSE` fallback. Settlement therefore rests entirely
  on the EOD endpoint, which this account has never called.
* `HISTORY_DAYS = 760`: the first backfill asks for 760 calendar days in one
  request. ThetaData's documentation says "stock_history_eod caps a single request
  at 365 days" ([ThetaData Excel examples](https://docs.thetadata.us/Excel/Examples.html)).
  If the terminal rejects the request, `refresh_closes` records `FAILED`, retries
  every step, and never succeeds: the models never get history, nothing passes,
  and the only symptom is a quiet "no price history yet" line.
* Good news on entitlement: the stock EOD endpoint is listed for every tier
  including FREE ([ThetaData subscriptions](https://docs.thetadata.us/Articles/Getting-Started/Subscriptions.html)),
  and the national EOD report is generated at 17:15 ET with `created` and
  `last_trade` timestamps ([stock_history_eod](https://docs.thetadata.us/operations_excel/stock_history_eod.html)).
  The FREE tier's first access date is listed as 2023-06-01, so the empirical
  model's window is at most ~2.4 years of a mostly calm market.

**Smallest fix.** Chunk EOD requests to ≤ 365 days; add a System check "closes
current for N of M symbols, oldest gap X days"; settle nothing until `close` has
been compared with the official close for a week of real data.

**Then the backtest**, which is the single highest-value piece of work left: daily
option EOD chains are available from 2023-06 on the options subscription; run the
engine on each day's chain, freeze picks, settle at expiry, and report the P&L
curve through August 2024 and April 2025, max drawdown, per-family calibration
of predicted vs realised. If that curve is not survivable at your intended size,
nothing else in this document matters.

### B4 — The broker is not in the model

* **Commission.** Saxo's 2023 repricing made stock options "33 % cheaper for
  Classic accounts" (from USD 3, so USD 2.00 per contract), "50 % less for
  Platinum", and VIP "from 85 cents to 75 cents"; Saxo's own iron-condor example
  costs USD 4 to enter and USD 4 to exit per lot on the new Classic tariff ([Saxo pricing article](https://www.home.saxo/en-ch/content/articles/pricing/trading-evolved-unveiling-new-opportunities-with-our-updated-pricing-structure-28122023)).
  The engine assumes 0.65. P4: at USD 3.00 the pass count drops from 224 to 183
  and the top-5 EV/risk from 0.41 to 0.33; set `CHRISTIANIA_COMMISSION_PER_CONTRACT`
  to your actual tier before reading any number.
* **Margin profile.** Clients are on the basic profile by default and "not able to
  sell (write) listed options"; writing requires the advanced profile, which gives
  margin benefit on strategies ([Saxo trading conditions](https://www.home.saxo/rates-and-conditions/equity-options/trading-conditions)).
  Confirm the profile and the margin Saxo actually charges on a defined-risk spread.
* **Assignment.** US equity and ETF options are American and physically settled. The
  engine's "hold to expiry" settles at intrinsic value. In the real account a short
  put one cent in the money at the close is assigned, the long put expires
  worthless, and you own 100 shares per lot over the weekend with no hedge. The
  expiry-day rule has to be "close any spread whose short strike is within ~1 % of
  spot before 15:30", or use cash-settled XSP/SPX for the 0DTE lane.
* **Quotes.** Saxo's LIVE `infoprices` returned 15-minute delayed OPRA in the
  project's own probes. Re-quoting in a delayed platform re-quotes the past.

### M1 — No working liquidity screen

`_theta_option_quote_records` stores `open_interest: None` for every ThetaData
row, so `min_open_interest = 50` never rejects anything. The spread gate rejects a
leg only when relative spread > 20 % **and** absolute spread > 0.05, so a 0.01 ×
0.06 wing (143 %) passes (P5: `liquid()` returns `None`; 23 of 224 passers contain
such a leg). A 0.01-bid option often has no real market; the modelled wing fill of
0.0475 is a number nobody will trade at.

**Fix.** Require bid ≥ 0.05 and relative spread ≤ 50 % on every leg; drop the OI
gate or fetch open interest from ThetaData's OI endpoint (Standard tier).

### M2 — Staleness gate fails open

P6: with quote timestamps set to garbage or NULL, 224 structures pass and
`STALE_QUOTE` rejections are 0; `quote_age_seconds` is None, so the card simply
omits the age line. Any upstream change in the timestamp field silently disables
the gate. **Fix:** treat unknown age as stale; show "quote age unknown" in red.

### M3 — Forecast fragility

P7, top pick (iron fly 94/100/106, IV 25 %, engine EV +$88 at its 14.3 % forecast):

```
realised 15%: EV +84   realised 21%: EV +16   realised 25%: EV -14
realised 17%: EV +58   realised 23%: EV  +0   realised 28%: EV -32
```

Break-even realised volatility is 23 % against 25 % implied: the trade needs the
market to over-price volatility by 2 points, which is inside the forecast's own
error. P(max loss) runs from 18 % at 15 % realised to 42 % at 25 %. Displayed "win
chance 58–66 %" is the forecast's number; at realised 21–25 % it is 41–48 %.

**Fix.** Show EV at forecast, at IV − 2 and at IV on the card; adopt B1's mixture.

### M4 — Ranking ignores loss probability

`ev_per_risk = EV / max loss` ranks a +400/−200 fly with a 30 % chance of the full
loss above a condor with the same EV and a 10 % chance. **Fix:** rank by
EV / CVaR95 (or expected log growth at the chosen lot size) and show P(max loss).

### M5 — No exposure accounting

Five picks a day, two lots each, 27–45 days to expiry: after a month you hold 50+
short-vol positions on correlated names, and one −5 % day touches all of them.
The sidebar's "risk limit per trade" sizes each trade in isolation. **Fix:** show
open risk (sum of max loss of picks you took), cap it, cap new trades per day,
and count SPY/QQQ/sector ETFs as one name for the cap.

### M6 — Coupled to the legacy research cycle

Snapshots are created inside `full_research_cycle` → `independent_runner` after
the hypothesis scanner, structure bridge, shadow admission and unified capture
have run. The engine only runs when that iteration completes. Those modules were
kept because the daemon imports them, not because anyone will maintain them.
**Fix (separate PR):** a minimal collector — reference universe → ThetaData quote
cut → `market_snapshots`/`option_quotes` — as the daemon's only job, same schema,
then retire the rest.

### M7 — Earnings blind spot

P9: `implied_event_variance` returns zeros for chains with two expiries in the
window and detects the event with three. Monthly-only names get no protection.
**Fix:** an earnings calendar, or skip single names with < 3 expiries, or a manual
exclusion list until a source exists. There is no earnings feed in the stack.

### M8 — No record of real trades

`src/services/trade_service.py` and the `trades` table workflow were archived. The
scorecard therefore measures the engine's paper record, never your fills, and the
slippage/commission assumptions can never be checked. **Fix:** a "took it" action
on the card storing the real fill, or read positions from the existing read-only
Saxo client.

### M9 — 0DTE lane is modelled with the wrong returns

For horizons under a day the models scale close-to-close returns by the remaining
session fraction. Close-to-close variance includes the overnight gap (often the
larger part for single names) and intraday volatility is U-shaped. Direction:
variance overstated, so the lane mostly says NO TRADE — safe, but its numbers are
not meaningful. **Fix:** estimate intraday realised vol from ThetaData intraday
OHLC (Standard tier), or park the lane.

### m1 — No re-score at execution time

Sensitivity of the top structures (Black-76, one lot): iron fly −$6.5 per +1 IV
point, −$0.7 per +0.5 % spot; condor −$10 per IV point, −$18 per −3 % spot. An
hour-old quote moves the edge by roughly 10 %; not fatal, but the card should
offer "re-price now" against live ThetaData quotes before you place the order.

### m2 — Settlement price semantics

ThetaData's EOD report is generated at 17:15 ET; `last_trade` can be after 16:00.
Whether `close` is the official close was never verified on this account. A pick
with a strike within a few cents of the close can settle on the wrong side.
**Fix:** compare `close` with the official close for a week; prefer the 16:00
print; flag outcomes where |close − nearest short strike| < 0.1 %.

### m3 — Smaller items

* `load_closes` fills missing EOD days with the last intraday snapshot price:
  returns across such days mix 15:40 prices with closes. Drop the gap-fill.
* `engine_scans` + `engine_candidates`: ~25 steps × 2 lanes × 25 JSON records per
  day ≈ 3 MB/day with no retention; add a 30-day prune for candidates.
* UI: "Show all 20 passing trades" when 665 passed (`STORED_PASSED = 20`).
* `why_text`: "options look expensive" is true of every passer by construction.
* `RISK_FREE_RATE = 0.04` hard-coded; affects IV/delta slightly, not P&L.
* Engine step at production scale (P11): 48 synthetic chains, 14,820 structures,
  6.0 s, peak RSS 222 MiB in isolation; real chains are 2–3× larger. The daemon's
  policy is MemoryHigh 768 MiB / MemoryMax 1280 MiB; not measured inside the real
  daemon process.
* Docs: `docs/V1_ARCHITECTURE.md` and `docs/V1_STATUS.md` still describe the
  retired deck.

### Unvalidated constants (none is grounded in data)

slippage 0.5 × half-spread · commission 0.65 · min EV $5 · min EV/risk 3 % ·
max quote age 90 min (main) / 5 min (0DTE) · stale-scan 30 min · EWMA decay 0.94 ·
504-return window · event threshold 1.8× median forward variance · delta grid
(0.10–0.30 short, 0.35–0.55 long) · width steps 1/2/3/5 · fly wings 2/4/6 ·
MIN_RETURNS 60 · MIN_WINDOWS 60 · top_n 5/3 · max relative spread 0.20 ·
max absolute spread 0.05 · min OI 50 · verdict threshold n = 30 · 0DTE window
09:45–15:45 · HISTORY_DAYS 760 · risk-free 4 %.

---

## Architecture

**What is sound.** Additive migrations with a delta check; immutable picks and
outcomes; a read-only UI that never computes a recommendation; the engine
isolated so it cannot stop collection; WAL SQLite with verified backups; one VM
with commit-addressed releases and systemd resource policy.

**What is not.**
* The data cadence (12 of 48 symbols per 15 minutes) was designed for research
  sampling, not for pricing 4-leg combos; each symbol is refreshed about hourly.
* The engine is the last stage of a pipeline whose first five stages are retired
  research (M6).
* No alerting: an engine or collector failure is visible only on the System page.
* No real-time data anywhere: ThetaData snapshots in the daemon, delayed quotes at
  the broker (B4).
* No position state: the system knows what it recommended, not what you own (M8,
  M5).

## What I would do before betting, in order

1. Deploy as is, money off. Fix B3 first (chunked history, closes health check);
   watch the first Friday expiry settle correctly.
2. Build and run the EOD backtest (2023-06 → now). Deliverable: P&L curve, max
   drawdown, worst day, per-family calibration. Decide sizing from the April 2025
   drawdown, not from the EV column.
3. Fail-closed gates (M1, M2), one pick per underlying-day and cluster CI (B2),
   mixture scoring and EV/CVaR ranking (B1, M4), exposure cap (M5).
4. Broker realism: real commission tier, Advanced profile, expiry-day close rule or
   cash-settled index options, real-time quotes, real-fill recording (B4, M8).
5. Three months paper in parallel with the backtest; then money at a size where
   the backtest's worst month costs less than a number you choose in advance.

## Coverage ledger

**REVIEWED, with evidence**
* `src/engine/{models,chains,structures,pipeline,ledger,history,worker}.py`: read
  line by line; 11 probes (`probe.py`); 20 unit tests.
* `src/ui/{design,engine_pages}.py`, `app.py`: rendered with AppTest and
  screenshots on a seeded DB; HTML escaping of every provider-originated string
  checked.
* `migrations/039_engine_v1.sql` against `migration_delta_checks` (additive only).
* `src/research/research_daemon.py` engine hook: read; isolation reasoned, not
  executed in production.
* `src/research/independent_runner.py` quote persistence (OI, `quote_at`,
  `captured_at` format): read.
* `src/operations/market_calendar.py` edge exclusion and
  `shadow_expiry_outcome_v1` settlement starvation: read.
* `deploy/systemd/christiania-daemon.service`, `service_resources.py`: read; engine
  memory measured in isolation only.
* Deploy scripts scanned for references to archived files: none.
* ThetaData entitlements and EOD semantics, Saxo tariff and margin profiles:
  vendor documentation, cited above.

**NOT REVIEWED**
* Backup, restore, release and audit-export tooling (unchanged by the PR; 44 tests
  need 40 GB free disk locally and pass in CI).
* Saxo modules (`saxo.py`, `saxo_auth`, session keeper, quote monitor).
* Legacy research cycle internals beyond their role as data supplier.
* Massive provider, reference universe builder, Theta terminal control/watchdog.
* Host security (Caddy, oauth2-proxy disabled, secret handling).

**COULD NOT VERIFY FROM HERE**
* Production database: real quote-staleness distribution, zero-bid share in the
  7–45 day window, snapshot cadence as deployed.
* Real responses of `/v3/stock/history/eod` on this account (365-day cap, `close`
  semantics).
* Saxo account tier, margin profile, real-time OPRA entitlement, exercise and
  assignment fees (Saxo does not publish them).
* Engine step runtime and memory inside the real daemon process.
