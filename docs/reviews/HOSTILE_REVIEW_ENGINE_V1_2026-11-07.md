# Hostile review: Christiania trade engine v1 (PR #184)

> **Status 2026-11-08.** V1 was falsified by its first full backtest (see "The breakdown that
> retired V1") and replaced by V2 in the same PR (see "V2 (2026-11-08)"). The findings,
> fixes and probe scripts below describe V1 at commits `e835c11`–`c8ee9a1`; the probes do not
> run against V2's code.

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

**Second attempt (commit `2814e23`, same evening):** reached 19 December 2024 before the
terminal returned HTTP 478 "invalid session" repeatedly and the harness stopped as designed.
2,228 chains cached, 640 settled picks (first possible pick now June 2024 because of the
250-return minimum), provisional P&L **−$26,579**, hit rate 26.4 % vs 35.1 % predicted,
max drawdown −$32,482. Two things to settle before reading that number:

* **Splits.** ThetaData closes are unadjusted; NVDA split 10:1 on 2024‑06‑10, at the very
  start of this window. A −90 % "return" in the history inflates a year of NVDA volatility
  forecasts, and a pick with pre-split strikes settled against a post-split close books a
  bogus max loss. Split detection, adjusted close series for the models and split-aware
  settlement are now in `history.py` (used by the live engine and the backtest); the
  cached chains re-score without refetching.
* **The 478s.** The account's Theta Terminal also runs on the production server; ThetaData
  permits one terminal session per account, so two terminals log each other out. Run the
  backtest on the server next to the existing terminal (separate checkout of the branch),
  or stop the server's `christiania-theta` service while the PC runs.

Next: rerun from cache, then the full universe; decide with the curve from June 2024
through April 2025 in hand.

## The breakdown that retired V1 (2026-11-07, late evening)

`picks.csv` of the `2814e23` run (640 settled picks, −$26,579), sliced before any code was
changed. The loss is one bucket:

| Picks | n | P&L | Return on risk | Hit rate | Predicted hit |
|---|---|---|---|---|---|
| Index debit spreads (SPY/QQQ/IWM) | 206 | **−$28,700** | −70 % | 9.7 % | 31.8 % |
| Stock debit spreads (AAPL/MSFT/NVDA) | 321 | −$2,326 | −4 % | 30.8 % | 32.8 % |
| Index short premium (condors, flies, credit spreads) | 68 | −$3,414 | −25 % | 30.9 % | 48.2 % |
| Stock short premium | 45 | +$7,862 | +77 % | 64.4 % | 46.1 % |

Everything except index debit spreads nets to +$2,121. SPY put debit spreads: 86 picks,
9.3 % hit, 89.5 % at max loss against 69 % predicted. Picks where the smile-implied EV was
≤ 0 lost 40 % of their risk; where it was > 0, 7 %: the market model was the informative
one, the forecast models subtracted value wherever they disagreed with it.

Why the engine bought those trades:

1. The forecast distribution is symmetric; the index smile is not. Against a skewed market
   a symmetric model always says the far OTM put is overpriced and the near put fair-to-cheap,
   so a put debit spread (buy near, sell far) looks like edge twice. The engine was fading
   index put skew with bearish spreads (310 bearish vs 232 bullish picks in a +14 % market),
   buying the same strikes day after day (41 picks identical to the previous day's).
2. EWMA/GARCH stayed elevated for months after 5 August 2024 while implied vol mean-reverted
   in days (SPY 22 Nov: forecast 12.2 % vs ATM IV 8.5 %), so "vol is cheap" → buy spreads →
   decay. Implied vol beats GARCH as a forecast of realised; the literature said so first.
3. EV/CVaR ranking rewards structures with a small max loss, i.e. cheap OTM spreads.

NVDA: the unadjusted 10:1 split sat in the 250-day return window for the rest of the run,
so NVDA's forecast vol was 3–21× implied from June onward (median 12.9× in June, 3.6× in
December). All 121 NVDA picks were scored on garbage; they netted +$1,198 because the stock
doubled. The settlement artefact itself was one pick (+$500 swing).

Verdict on V1: falsified on this window (bootstrap 95 % −$70 to −$14 per pick), and the
reason is the thesis, not a parameter. The review's own framing was half wrong: I wrote
that the engine measured the variance risk premium and called it mispricing, expecting
it to end up selling premium. The fixed 50/50 mixture and the symmetric forecast made it a
net *buyer* of tails — the losing side of that premium.

## V2 (2026-11-08): sell the premium, measure it, pre-register the test

Decision taken with the operator: rebuild around the only part of the result with evidence
behind it (short premium) and the only model that was right (the market's smile), and test
it out of sample before any money moves. Changes, all in `src/engine`:

* **Distributions.** IMPLIED is unchanged (smile-implied, Breeden–Litzenberger). The
  forecast models are deleted. REAL_WORLD = IMPLIED with its log-return spread scaled by
  √λ and re-centred on the forward, where λ = Σ realised variance / Σ implied variance over
  the trailing 504 sessions of matched windows: the 30-calendar-day constant-maturity ATM
  implied vol at a session's close (interpolated in total variance between the bracketing
  expiries; the single expiry within 10 days when not bracketed) against the realised variance
  of the following 21 sessions (sum of squared log returns of split-adjusted closes, × 252/21).
  A name needs 250 matched sessions (one year) before it can pass; below that,
  `MODEL_UNAVAILABLE`. The smile's skew and tails are kept; the engine's only claim is the
  width.
* **Structures.** Credit spreads, iron condors, iron flies. No debit spreads; `NOT_A_CREDIT`
  rejects anything that is not a net credit.
* **Gates**, in order: suspect quotes → not a credit → max loss > per-lot cap → quote age
  unknown → stale → model unavailable → real-world EV < $5 → **stress EV < 0** (new as a gate:
  the trade must still pay if a −10 % jump has a 3 % chance before expiry) → EV/CVaR95 < 3 %.
  `MODELS_DISAGREE` and `EVENT_UNDETECTABLE` are gone (one model; the smile already contains
  the event). Event variance is still computed for the card.
* **Slots.** One open pick per underlying at a time, in the daemon (`open_pick_underlyings`)
  and the backtest (`OPEN_POSITION`). The same view is never stacked.
* **Data.** `engine_iv_history` (30-day IV per symbol per session from the ThetaData EOD
  chain; NULL when the chain cannot yield a point) replaces `engine_intraday_sessions`;
  backfilled `CHRISTIANIA_IV_BACKFILL_PER_STEP` (120) chains per engine step, newest first,
  round-robin across names. The 0DTE lane uses the same λ (untested at that horizon; the lane
  stays parked). Migration 039 edited in place: it has not been applied anywhere but test
  databases (PR unmerged; if you ran the app locally on this branch, delete that dev DB).
* **Backtest.** Warm-up phase fetches the 400 calendar days before `--start` as IV history
  (tolerant of sessions the subscription does not serve; a dead terminal still aborts);
  scoring phase as before with slots. `summary.json` reports the whole run, the calibration
  window (before `--oos-start`, default 2025-01-01), the out-of-sample window, a single-slot
  account path, the λ path (`risk_premium.csv`), and the mechanical verdict below.

### Pre-registered pass criteria (written 2026-11-08, before any out-of-sample result)

Evaluated by `evaluate_criteria` on the out-of-sample block (sessions ≥ 2025-01-01), all
three must hold over at least 60 expiry days:

1. the cluster-bootstrap (by expiry day) 95 % range of the average pick has its lower bound
   above zero;
2. |realised hit rate − predicted hit rate| ≤ 5 points;
3. realised full-loss rate ≤ predicted full-loss rate + 5 points.

Anything else is FAIL (or INSUFFICIENT below 60 expiry days). The 2024 window is now
in-sample for V2 and proves nothing on its own. If V2 fails out of sample, the next version
needs new out-of-sample data, which means waiting, not re-cutting 2025–26.

### Parameters introduced or kept, none grounded in data

| Parameter | Value | Why this value |
|---|---|---|
| IV target maturity | 30 calendar days | VIX convention |
| Nearest-expiry fallback | ±10 days | data availability on monthly-only names |
| Realised horizon | 21 sessions | matches 30 calendar days |
| Minimum matched sessions | 250 | one year; ~12 independent months |
| Estimation window | 504 sessions | two years; all the FREE stock tier serves |
| Stress shock | −10 % with probability 3 % | V1 value; ≈ the frequency of −10 % months in SPX since 2000 |
| Min EV, min score, max loss per lot | $5, 3 %, $500 | V1 values |
| Backfill budget | 120 chains per step | ~2 minutes of requests per 15-minute cycle |
| Pass criteria | lower CI > 0, 5-point gaps, 60 expiry days | the live verdict's rules, fixed before the test |

### What the operator still owns

Unchanged from "Still open": Saxo Advanced profile and short-writing permission (not
verified), the appropriateness test (not taken), and the capital. At €500 the first full loss
on a $500-max-loss pick ends the account; the per-lot cap has to be set so that a full loss
is a fraction of the capital, which on these names means more capital, not a smaller cap.

### First V2 run, six names (2026-11-08 00:52): FAIL, and most of it was not real

`e94fbcf`, SPY/QQQ/IWM/AAPL/MSFT/NVDA, 583 sessions from 2024-07-15, entirely from the cache
(the V1 full run had fetched every chain through 2026-11-06 the hour before).

| | Calibration (2024) | Out of sample (2025–26) |
|---|---|---|
| Settled picks / expiry days | 34 / 27 | 72 / 60 |
| P&L on risk | +$110 on $7,015 | **+$1,896 on $13,677 (+13.9 %)** |
| Average pick, bootstrap 95 % | +$3 (−103 to +116) | +$26 (**−$35** to +$91) |
| Hit rate vs predicted | 41 % vs 46 % | 49 % vs 50 % |
| Full-loss rate vs predicted | 56 % vs 44 % | 44 % vs 44 % |
| Verdict | — | **FAIL** (lower bound below zero; the other checks pass) |

The FAIL is the smaller problem. Sliced by the sign of the market's own (smile-implied) EV:

| Out of sample | n | P&L | Risk |
|---|---|---|---|
| Implied EV ≤ 0 — the edge comes from λ alone | 9 | +$696 | $1,914 |
| Implied EV > 0 — the quotes beat the smile | 63 | +$1,200 | $11,763 |

76 % of the claimed real-world EV out of sample was already present under the market's own
smile, i.e. it came from quotes, not from λ. Under the smile every structure is worth its
fitted price minus costs; a positive EV there means a leg's EOD NBBO was far from the smile:
1-wide QQQ spreads quoted at 0.53–0.81 of width 18 % out of the money, iron flies with a
credit of 95–100 % of the wing width (max loss $7 on a 4-wide QQQ fly), the +$1,110 SPY fly
whose quotes beat the smile by $61. Those fills do not exist. 65 of the 106 picks kept 60 % or
more of their width as credit. The engine was a stale-quote picker with a λ label on it.

Why λ left nothing else: the trailing ratio was 0.72–0.95 across the six names in 2024 and
jumped to 1.15–1.31 for SPY, QQQ and AAPL in 2025Q2 (the April 2025 crash month dominates
a two-year sum of realised variance) and stayed above 1 through 2026; only MSFT (0.72→0.9) and
later IWM (0.85) stayed below. Under the model there was no premium to sell on four of six
names for the whole out-of-sample window, which is what the model should say about a window
containing a crash, and also exactly when selling premium has historically paid best. That is
a known limit of a trailing estimator; it is noted, not changed.

**Amendment 1 to the pre-registration (2026-11-08 01:20, after the result above).** A
validity gate is added: `QUOTE_INCONSISTENT` rejects any structure whose EV under the
market's own smile is positive after costs. It is defined by principle (the whole edge must
come from λ), not by outcome: on the six-name run it removes 82 of 106 picks including the
largest winner, and the surviving 24 net −$677 in 2024 and +$696 out of sample. The criteria
themselves are unchanged. Because the out-of-sample window has now been seen once, the
rerun's result is a second look, not a first; it is reported as such.

What a clean run will show is already visible: about one legitimate trade a month across six
names, netting roughly zero. The remaining test with any power is the full 48-name universe
under the same gate and criteria; if that fails, V2 is done and the honest conclusion is that
no edge is demonstrable for a retail premium seller on liquid US names with a two-year
lookback at these costs.

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

## Closing record (2026-11-08): stop decision

**Universe run, 48 names, 2024-07-15 to 2026-11-06, commit `ee4bcfb`.** 226 picks (224 settled): -$13,817 on $63,517 at risk (-21.8%). Out of sample (127 picks, 70 expiry days): -$8,114; bootstrap 95% interval -$110 to -$22 per pick. Pre-registered verdict: **FAIL** on all three checks (lower bound above zero; hit-rate gap 9.2 pts against a limit of 5; full-loss excess 11.6 pts against a limit of 5). Predicted hit rate 54.8% against 45.7% realised; predicted full-loss rate 34.1% against 45.7%. Max implied EV across picks was -$0.04, so the QUOTE_INCONSISTENT gate held and the loss is not a quote artefact. The risk-premium ratio (lambda) did not order outcomes: no monotone relation across quartiles, every quartile lost.

**Cost diagnostic (`scripts/cost_diagnostic.py`, commit `fb72f2e`).** The same 224 trades re-priced, reproducing the run to $0.00:

| Fill assumption | All | Out of sample |
|---|---|---|
| As run (0.5 slippage, $2/leg) | -$13,817 | -$8,114 |
| Zero commission | -$12,140 | -$7,182 |
| Zero slippage | -$5,766 | -$3,572 |
| Mid fill, zero commission | -$4,090 | -$2,640 |
| 0.25 slippage, $0.65/leg | -$8,660 | -$5,214 |

Costs were about $9,700 (about $43 per trade: roughly $8,050 spread slippage, $1,680 commission). Before any cost the picks lost about $18 per trade, within about one standard error of zero. The model predicted about +$13,000 before costs; the shortfall is model error (tail risk understated), not execution.

**Decision.** No demonstrated edge before costs, and a cost wall of about $43 per trade (about 15% of risk) that a four-leg structure cannot clear. Two engine versions failed their own pre-registered tests; the second on the largest sample this data supports. Christiania is retained as a tracker and screen, not a source of trades. The planned earnings-event and fewer-leg tests were not run. Any future signal idea needs a new pre-registration written before its data is examined. Nothing was traded; the cost was time, not money.
