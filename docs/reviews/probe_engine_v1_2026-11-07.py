"""Reproductions for HOSTILE_REVIEW_ENGINE_V1_2026-11-07.md: hostile probes against src/engine.

Run from the repo root: .venv/bin/python docs/reviews/probe_engine_v1_2026-11-07.py
"""
from __future__ import annotations

import math
import os
import resource
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "tests"))

from src.database.migration_runner import apply_pending_migrations  # noqa: E402
from src.database.repository import get_connection  # noqa: E402
from src.engine.chains import Quote, black76_price, build_chain, calendar_years_to_expiry  # noqa: E402
from src.engine.ledger import picks_with_outcomes, record_scan  # noqa: E402
from src.engine.models import implied_event_variance  # noqa: E402
from src.engine.pipeline import EngineConfig, main_config, run_scan  # noqa: E402
from src.engine.structures import CostPolicy, liquid, pnl  # noqa: E402
from test_engine_v1 import ASOF, EXPIRIES, history  # noqa: E402

RNG = np.random.default_rng(42)


def skewed_quotes(asof=ASOF, spot=100.0, atm_iv=0.25, put_skew=0.0, call_skew=0.0,
                  expiries=EXPIRIES, spread_frac=0.04, min_spread=0.02, wing_quote=None,
                  noise_ticks=0.0, rng=None, strikes=None):
    """Chain priced by Black-76 with a linear skew in moneyness: iv = atm + skew*(ln(K/F))."""
    quotes = []
    stamp = asof.isoformat()
    rng = rng or RNG
    for exp in expiries:
        t = calendar_years_to_expiry(asof, exp)
        f = spot * math.exp(0.04 * t)
        for k in (strikes if strikes is not None else np.arange(70, 131, 1.0)):
            m = math.log(float(k) / f)
            iv = atm_iv + (put_skew * -m if m < 0 else call_skew * m)
            for right in "CP":
                p = black76_price(right, f, float(k), t, iv)
                if p < 0.03:
                    continue
                spread = max(min_spread, spread_frac * p)
                if wing_quote and p < wing_quote[0]:
                    bid, ask = wing_quote[1], wing_quote[2]
                else:
                    bid, ask = p - spread / 2, p + spread / 2
                if noise_ticks:
                    shift = rng.integers(-1, 2) * noise_ticks
                    bid, ask = bid + shift, ask + shift
                quotes.append(Quote(right, float(k), exp, round(max(bid, 0.01), 2),
                                    round(max(ask, 0.02), 2), stamp, None))
    return quotes


def chain_from(quotes, underlying="TEST", asof=ASOF, min_dte=7, max_dte=45):
    return build_chain(underlying, asof, quotes, snapshot_id=None, spot=100.0, source="T",
                       min_dte=min_dte, max_dte=max_dte)


def fresh_db(path: Path):
    path.unlink(missing_ok=True)
    c = get_connection(path)
    c.executescript((Path(__file__).resolve().parents[2] / "trade_log_schema.sql").read_text())
    apply_pending_migrations(c, Path(__file__).resolve().parents[2] / "migrations")
    c.commit()
    return c


def banner(n, title):
    print(f"\n=== P{n}: {title} ===")


# ---------------------------------------------------------------------------
banner(1, "Pick churn within one session as the forward drifts")
db = Path("/tmp/christiania_probe1.db")
conn = fresh_db(db)
hist = history(0.15)
keys_per_scan = []
for i, spot in enumerate(np.arange(100.0, 100.61, 0.1)):
    asof = ASOF + timedelta(minutes=15 * i)
    q = skewed_quotes(asof=asof, spot=float(spot))
    ch = build_chain("TEST", asof, q, snapshot_id=None, spot=float(spot), source="T",
                     min_dte=7, max_dte=45)
    res = run_scan([ch], {"TEST": hist}, main_config(), asof=asof)
    record_scan(conn, res, completed_at=asof)
    keys_per_scan.append([c.structure_key for c in res.picks])
picks = picks_with_outcomes(conn)
print(f"scans: {len(keys_per_scan)}  spot drift: 100.0 -> 100.6 (0.6%)")
print(f"distinct frozen picks in ONE session, ONE underlying: {len(picks)}")
print(f"expiries covered: {sorted({p['expiration'] for p in picks})}")
print(f"picks per scan: {[len(k) for k in keys_per_scan]} -> union {len({k for ks in keys_per_scan for k in ks})}")
conn.close()

# ---------------------------------------------------------------------------
banner(2, "Gate selectivity: pass rate as a function of the IV - forecast gap")
cfg = main_config()
print("history vol 15% (forecast ~17%).  implied IV -> passed / scored,  share short-vol among passed")
for iv in (0.14, 0.16, 0.18, 0.20, 0.22, 0.25, 0.30):
    ch = chain_from(skewed_quotes(atm_iv=iv))
    res = run_scan([ch], {"TEST": hist}, cfg, asof=ASOF)
    credit = sum(1 for c in res.passed if c.is_credit)
    print(f"  IV {iv:.0%}: {len(res.passed):4d} / {res.structures_scored:4d}"
          f"   short-vol share {credit / max(1, len(res.passed)):.0%}"
          f"   top EV/risk {res.passed[0].ev_per_risk:+.3f}" if res.passed else
          f"  IV {iv:.0%}: {len(res.passed):4d} / {res.structures_scored:4d}   (nothing passes)")

# ---------------------------------------------------------------------------
banner(3, "Skew: does the engine sell the skew, and what happens with a jump?")
ch = chain_from(skewed_quotes(atm_iv=0.22, put_skew=0.60, call_skew=-0.10))
e = ch.expiries[-1]
puts = {q.strike: q.iv for q in e.quotes if q.right == "P" and q.iv}
print(f"  chain: ATM IV {e.atm_iv:.1%}, 90-strike put IV {puts.get(90.0, float('nan')):.1%},"
      f" 110-strike call IV {next((q.iv for q in e.quotes if q.right == 'C' and q.strike == 110.0 and q.iv), float('nan')):.1%}")
res = run_scan([ch], {"TEST": hist}, cfg, asof=ASOF)
shapes = {}
for c in res.passed[:20]:
    shapes[c.shape] = shapes.get(c.shape, 0) + 1
print(f"  passed {len(res.passed)}; top-20 shapes: {shapes}")
top = res.passed[0]
print(f"  top pick: {top.shape} {top.description} exp {top.expiration}: engine EV {top.conservative_ev_usd:+.0f},"
      f" max loss {top.max_loss_usd:.0f}, POP {min(top.scores['VOL_FORECAST'].pop, top.scores['EMPIRICAL'].pop):.0%}")
# "true" world: same 17% diffusion but a 4% chance of a -12% jump before expiry
exp = next(x for x in ch.expiries if x.expiration == top.expiration)
from src.engine.structures import Leg, Structure  # noqa: E402

legs = tuple(Leg(next(q for q in exp.quotes if q.right == l["right"] and q.strike == l["strike"]), l["side"])
             for l in top.legs)
s = Structure(top.family, top.shape, "TEST", top.expiration, legs)
T = top.trading_days / 252.0
for p_jump, jump in ((0.0, 0.0), (0.02, -0.08), (0.04, -0.12), (0.04, -0.20)):
    z = RNG.standard_normal(200_000)
    r = -0.5 * 0.17 ** 2 * T + 0.17 * math.sqrt(T) * z
    j = RNG.random(200_000) < p_jump
    r = r + np.where(j, math.log(1 + jump), 0.0)
    r = r - math.log(np.mean(np.exp(r)))  # keep it a martingale
    v = pnl(s, exp.forward * np.exp(r), cfg.cost)
    print(f"  true world: 17% vol, P(jump {jump:+.0%})={p_jump:.0%} -> EV {v.mean():+.1f}, P(loss>100) {np.mean(v < -100):.1%}")

# ---------------------------------------------------------------------------
banner(4, "Execution assumptions: slippage and commission")
base = chain_from(skewed_quotes(atm_iv=0.25))
for slip, comm in ((0.5, 0.65), (1.0, 0.65), (0.5, 3.0), (1.0, 3.0)):
    c2 = EngineConfig(**{**cfg.__dict__, "cost": CostPolicy(slip, comm)})
    res = run_scan([base], {"TEST": hist}, c2, asof=ASOF)
    top5 = res.passed[:5]
    print(f"  slippage {slip:.1f} x half-spread, ${comm:.2f}/contract: passed {len(res.passed):4d},"
          f" top-5 mean EV {np.mean([c.conservative_ev_usd for c in top5]) if top5 else float('nan'):+.0f},"
          f" top-5 mean EV/risk {np.mean([c.ev_per_risk for c in top5]) if top5 else float('nan'):+.3f}")

# ---------------------------------------------------------------------------
banner(5, "Liquidity gate: 0.01 x 0.06 wings pass, and what mid-pricing them is worth")
q = skewed_quotes(atm_iv=0.25, wing_quote=(0.08, 0.01, 0.06))
ch = chain_from(q)
res = run_scan([ch], {"TEST": hist}, cfg, asof=ASOF)
wingy = [c for c in res.passed if any(l["ask"] == 0.06 and l["bid"] == 0.01 for l in c.legs)]
print(f"  passed {len(res.passed)}, of which {len(wingy)} contain a 0.01x0.06 leg (rel. spread 143%)")
if wingy:
    c = wingy[0]
    n_wings = sum(1 for l in c.legs if l["ask"] == 0.06 and l["side"] > 0)
    print(f"  example {c.shape} {c.description}: EV {c.conservative_ev_usd:+.0f}; modelled wing fill "
          f"{[l['fill'] for l in c.legs if l['ask'] == 0.06]}; paying the ask instead costs "
          f"{n_wings * (0.06 - 0.035) * 100:.0f} more per lot")
print(f"  liquid() verdict for a 0.01x0.06 leg: {liquid(Structure('X','X','T','2026-12-04',(Leg(Quote('P',80,'2026-12-04',0.01,0.06,ASOF.isoformat(),None),1),Leg(Quote('P',85,'2026-12-04',0.3,0.34,ASOF.isoformat(),None),-1))), max_relative_spread=0.2, max_abs_spread=0.05, min_open_interest=50)}")

# ---------------------------------------------------------------------------
banner(6, "Staleness gate silently off when a timestamp is unparseable or missing")
q = skewed_quotes(atm_iv=0.25)
q = [Quote(x.right, x.strike, x.expiration, x.bid, x.ask, "09:31:00 garbage", x.open_interest) for x in q]
res = run_scan([chain_from(q)], {"TEST": hist}, cfg, asof=ASOF)
print(f"  garbage quote_at on every leg -> passed {len(res.passed)}, STALE_QUOTE rejections "
      f"{res.rejections.get('STALE_QUOTE', 0)}, top quote_age_seconds = {res.passed[0].quote_age_seconds if res.passed else None}")
q = [Quote(x.right, x.strike, x.expiration, x.bid, x.ask, None, x.open_interest) for x in skewed_quotes(atm_iv=0.25)]
res = run_scan([chain_from(q)], {"TEST": hist}, cfg, asof=ASOF)
print(f"  NULL quote_at on every leg      -> passed {len(res.passed)}, STALE_QUOTE rejections {res.rejections.get('STALE_QUOTE', 0)}")

# ---------------------------------------------------------------------------
banner(7, "Breakeven realised volatility of the top pick (IV 25%, forecast ~17%)")
ch = chain_from(skewed_quotes(atm_iv=0.25))
res = run_scan([ch], {"TEST": hist}, cfg, asof=ASOF)
top = res.passed[0]
exp = next(x for x in ch.expiries if x.expiration == top.expiration)
legs = tuple(Leg(next(q for q in exp.quotes if q.right == l["right"] and q.strike == l["strike"]), l["side"])
             for l in top.legs)
s = Structure(top.family, top.shape, "TEST", top.expiration, legs)
T = top.trading_days / 252.0
z = RNG.standard_normal(400_000)
print(f"  {top.shape} {top.description}, {top.expiration}, engine EV {top.conservative_ev_usd:+.0f}, forecast vol {top.forecast_vol:.1%}")
rows = []
for vol in (0.15, 0.17, 0.19, 0.21, 0.23, 0.25, 0.28, 0.32):
    r = -0.5 * vol * vol * T + vol * math.sqrt(T) * z
    r -= math.log(np.mean(np.exp(r)))
    v = pnl(s, exp.forward * np.exp(r), cfg.cost)
    rows.append((vol, v.mean(), np.mean(v > 0)))
    print(f"    realised {vol:.0%}: EV {v.mean():+6.1f}   P(profit) {np.mean(v > 0):.0%}   P(max loss) {np.mean(v < -0.95 * top.max_loss_usd):.0%}")

# ---------------------------------------------------------------------------
banner(8, "Winner's curse: ranking selects quote noise")
clean = chain_from(skewed_quotes(atm_iv=0.25))
clean_res = run_scan([clean], {"TEST": hist}, cfg, asof=ASOF)
clean_ev = {c.structure_key: c.conservative_ev_usd for c in clean_res.passed}
clean_ev.update({c.structure_key: c.conservative_ev_usd for c in clean_res.near_misses})
gaps = []
for trial in range(30):
    noisy = chain_from(skewed_quotes(atm_iv=0.25, noise_ticks=0.01, rng=np.random.default_rng(trial)))
    res = run_scan([noisy], {"TEST": hist}, cfg, asof=ASOF)
    for c in res.passed[:5]:
        if c.structure_key in clean_ev:
            gaps.append(c.conservative_ev_usd - clean_ev[c.structure_key])
print(f"  +/-1 tick random noise on every quote, 30 trials: top-5 EV minus clean-quote EV of the same structure:"
      f" mean {np.mean(gaps):+.1f} $, median {np.median(gaps):+.1f} $, n={len(gaps)}")
print(f"  (clean-chain top-5 EV mean for scale: {np.mean([c.conservative_ev_usd for c in clean_res.passed[:5]]):+.1f} $)")

# ---------------------------------------------------------------------------
banner(9, "Event detection blind spot with <= 2 expiries")
term2 = [(0.03, 0.20), (0.06, 0.45)]  # earnings inside the second expiry
print(f"  2 expiries, huge forward variance in the 2nd: event variance = {implied_event_variance(term2)}")
term3 = [(0.03, 0.20), (0.06, 0.45), (0.09, 0.38)]
print(f"  3 expiries, same event:                        event variance = {[round(x, 4) for x in implied_event_variance(term3)]}")

# ---------------------------------------------------------------------------
banner(10, "Track-record verdict: how often does 'making money with 95% confidence' fire when the edge is zero or negative?")
# Per-trade P&L model from the engine's own top pick: win +W with prob p, lose -L otherwise, plus a
# common daily shock (within-day correlation rho) and a rare tail day that hits every open trade.
W, L = top.max_gain_usd, top.max_loss_usd
from scipy.stats import norm as _norm  # noqa: E402


def simulate(n_days, per_day, p_win, rho, p_tail, trials=4000, seed=1):
    rng = np.random.default_rng(seed)
    thr = _norm.ppf(p_win)
    day_f = rng.standard_normal((trials, n_days, 1))
    idio = rng.standard_normal((trials, n_days, per_day))
    z = math.sqrt(rho) * day_f + math.sqrt(1 - rho) * idio
    x = np.where(z < thr, W, -L)
    tail = rng.random((trials, n_days, 1)) < p_tail
    x = np.where(tail, -L, x).reshape(trials, n_days * per_day)
    first30 = x[:, :30]
    se = first30.std(axis=1, ddof=1) / math.sqrt(30)
    fired = first30.mean(axis=1) - 1.96 * se > 0
    after = x[:, 30:].sum(axis=1)
    return fired.mean(), (after[fired].mean() if fired.any() else float("nan"))

p_be = L / (W + L)  # break-even win probability
print(f"  top pick payoff: +{W:.0f} / -{L:.0f}; break-even win rate {p_be:.0%}; engine says {min(top.scores['VOL_FORECAST'].pop, top.scores['EMPIRICAL'].pop):.0%}")
for p_win, rho, p_tail in ((p_be, 0.0, 0.0), (p_be, 0.6, 0.0), (p_be - 0.03, 0.6, 0.0), (p_be + 0.05, 0.6, 0.02)):
    rate, after = simulate(n_days=24, per_day=5, p_win=p_win, rho=rho, p_tail=p_tail)
    print(f"    true win rate {p_win:.0%}, within-day corr {rho:.1f}, tail-day prob {p_tail:.0%}/day:"
          f" verdict fires after 30 trades in {rate:.0%} of worlds; mean P&L of the next 90 trades {after:+.0f}")

# ---------------------------------------------------------------------------
banner(11, "Engine step cost at production scale (48 chains)")
chains = []
for i in range(48):
    chains.append(build_chain(f"S{i:02d}", ASOF, skewed_quotes(atm_iv=0.18 + 0.002 * i, rng=np.random.default_rng(i)),
                              snapshot_id=i, spot=100.0, source="T", min_dte=7, max_dte=45))
closes = {f"S{i:02d}": history(0.12 + 0.004 * i, seed=i) for i in range(48)}
t0 = time.time()
res = run_scan(chains, closes, cfg, asof=ASOF)
dt = time.time() - t0
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
print(f"  48 chains x {sum(len(e.quotes) for c in chains for e in c.expiries) // 48} quotes: {dt:.1f} s,"
      f" structures scored {res.structures_scored:,}, passed {len(res.passed):,}, peak RSS {rss:.0f} MiB")
print(f"  top-5 underlyings: {[c.underlying for c in res.picks]}  (IV ladder: higher index = richer IV)")
