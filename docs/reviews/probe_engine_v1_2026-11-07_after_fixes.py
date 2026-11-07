"""The hostile probes of HOSTILE_REVIEW_ENGINE_V1_2026-11-07.md, re-run after the fixes.

Same synthetic scenarios as probe_engine_v1_2026-11-07.py; the numbers here are the
"after" column of the review's fix table.
Run from the repo root: .venv/bin/python docs/reviews/probe_engine_v1_2026-11-07_after_fixes.py
"""
from __future__ import annotations

import math
import resource
import sys
import time
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from src.database.migration_runner import apply_pending_migrations  # noqa: E402
from src.database.repository import get_connection  # noqa: E402
from src.engine.chains import Quote, black76_price, build_chain, calendar_years_to_expiry  # noqa: E402
from src.engine.ledger import (  # noqa: E402
    Scorecard, cluster_bootstrap_ci, picks_with_outcomes, record_scan, verdict,
)
from src.engine.pipeline import EngineConfig, main_config, run_scan  # noqa: E402
from src.engine.structures import CostPolicy, Leg, Quote as _Q, Structure, liquid, pnl  # noqa: E402
from test_engine_v1 import ASOF, EXPIRIES, history  # noqa: E402

RNG = np.random.default_rng(42)
SYMBOL = "TEST"   # a single name: earnings detection required


def skewed_quotes(asof=ASOF, spot=100.0, atm_iv=0.25, put_skew=0.0, call_skew=0.0,
                  expiries=EXPIRIES, spread_frac=0.04, min_spread=0.02, wing_quote=None,
                  strikes=None):
    quotes = []
    stamp = asof.isoformat()
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
                quotes.append(Quote(right, float(k), exp, round(max(bid, 0.01), 2),
                                    round(max(ask, 0.02), 2), stamp, None))
    return quotes


def chain_from(quotes, underlying=SYMBOL, asof=ASOF, min_dte=7, max_dte=45):
    return build_chain(underlying, asof, quotes, snapshot_id=None, spot=100.0, source="T",
                       min_dte=min_dte, max_dte=max_dte)


def fresh_db(path: Path):
    path.unlink(missing_ok=True)
    c = get_connection(path)
    c.executescript((ROOT / "trade_log_schema.sql").read_text())
    apply_pending_migrations(c, ROOT / "migrations")
    c.commit()
    return c


def banner(n, title):
    print(f"\n=== P{n} after: {title} ===")


cfg = main_config()
hist = history(0.15)
print(f"config: commission {cfg.cost.commission_per_contract}/contract, forecast weight "
      f"{cfg.forecast_weight}, min bid {cfg.min_bid}, max relative spread {cfg.max_relative_spread}, "
      f"stress {cfg.stress_jump_prob:.0%} x {cfg.stress_jump:+.0%}, decision {cfg.decision_time}")

# ---------------------------------------------------------------------------
banner(1, "Pick churn within one session as the forward drifts")
conn = fresh_db(Path("/tmp/christiania_probe_after.db"))
per_scan = []
for i, spot in enumerate(np.arange(100.0, 100.61, 0.1)):
    asof = ASOF + timedelta(minutes=15 * i)
    ch = build_chain(SYMBOL, asof, skewed_quotes(asof=asof, spot=float(spot)), snapshot_id=None,
                     spot=float(spot), source="T", min_dte=7, max_dte=45)
    res = run_scan([ch], {SYMBOL: hist}, cfg, asof=asof)
    record_scan(conn, res, completed_at=asof)
    per_scan.append(len(res.picks))
picks = picks_with_outcomes(conn)
print(f"scans: {len(per_scan)}, best-per-underlying per scan {per_scan}")
print(f"distinct frozen picks in ONE session, ONE underlying: {len(picks)} (was 12)")
conn.close()

# ---------------------------------------------------------------------------
banner(2, "Gate selectivity: pass rate as a function of the IV - forecast gap")
for iv in (0.14, 0.16, 0.18, 0.20, 0.22, 0.25, 0.30):
    res = run_scan([chain_from(skewed_quotes(atm_iv=iv))], {SYMBOL: hist}, cfg, asof=ASOF)
    credit = sum(1 for c in res.passed if c.is_credit)
    top = res.passed[0] if res.passed else None
    print(f"  IV {iv:.0%}: {len(res.passed):4d} / {res.structures_scored:4d}"
          + (f"   short-vol share {credit / len(res.passed):.0%}   top: mixture EV {top.conservative_ev_usd:+.0f},"
             f" forecast {top.forecast_ev_usd:+.0f}, implied {top.implied_ev_usd:+.0f}, score {top.score:+.3f}"
             if top else "   (nothing passes)"))

# ---------------------------------------------------------------------------
banner(3, "Skew: what the engine sells, and the stress column it now shows")
ch = chain_from(skewed_quotes(atm_iv=0.22, put_skew=0.60, call_skew=-0.10))
res = run_scan([ch], {SYMBOL: hist}, cfg, asof=ASOF)
shapes = {}
for c in res.passed[:20]:
    shapes[c.shape] = shapes.get(c.shape, 0) + 1
print(f"  passed {len(res.passed)} (was 194); top-20 shapes: {shapes}")
if res.passed:
    top = res.passed[0]
    print(f"  top pick: {top.shape} {top.description} exp {top.expiration}: mixture EV {top.conservative_ev_usd:+.0f}"
          f" (was +77 forecast-only), forecast {top.forecast_ev_usd:+.0f}, implied {top.implied_ev_usd:+.0f},"
          f" stress {top.stress_ev_usd:+.0f}, P(max loss) {top.p_max_loss:.0%}, CVaR95 {top.cvar95_usd:.0f}")

# ---------------------------------------------------------------------------
banner(4, "Execution assumptions: slippage and commission")
base = chain_from(skewed_quotes(atm_iv=0.25))
for slip, comm in ((0.5, 2.00), (1.0, 2.00), (0.5, 0.65)):
    c2 = EngineConfig(**{**cfg.__dict__, "cost": CostPolicy(slip, comm)})
    res = run_scan([base], {SYMBOL: hist}, c2, asof=ASOF)
    top5 = res.passed[:5]
    print(f"  slippage {slip:.1f} x half-spread, ${comm:.2f}/contract: passed {len(res.passed):4d},"
          f" top-5 mean mixture EV {np.mean([c.conservative_ev_usd for c in top5]) if top5 else float('nan'):+.0f},"
          f" top-5 mean score {np.mean([c.score for c in top5]) if top5 else float('nan'):+.3f}")

# ---------------------------------------------------------------------------
banner(5, "Liquidity gate: 0.01 x 0.06 wings")
res = run_scan([chain_from(skewed_quotes(atm_iv=0.25, wing_quote=(0.08, 0.01, 0.06)))],
               {SYMBOL: hist}, cfg, asof=ASOF)
wingy = [c for c in res.passed if any(l["ask"] == 0.06 and l["bid"] == 0.01 for l in c.legs)]
print(f"  passed {len(res.passed)}, of which {len(wingy)} contain a 0.01x0.06 leg (was 23);"
      f" NO_REAL_MARKET rejections {res.rejections.get('NO_REAL_MARKET', 0)}")
s = Structure("X", "X", "T", "2026-12-04", (Leg(_Q("P", 80, "2026-12-04", 0.01, 0.06, ASOF.isoformat(), None), 1),
                                            Leg(_Q("P", 85, "2026-12-04", 0.3, 0.34, ASOF.isoformat(), None), -1)))
print(f"  liquid() verdict for a 0.01x0.06 leg: {liquid(s, max_relative_spread=cfg.max_relative_spread, min_bid=cfg.min_bid)}")

# ---------------------------------------------------------------------------
banner(6, "Staleness gate with unparseable or missing timestamps")
for label, stamp in (("garbage", "09:31:00 garbage"), ("NULL", None)):
    q = [Quote(x.right, x.strike, x.expiration, x.bid, x.ask, stamp, None) for x in skewed_quotes(atm_iv=0.25)]
    res = run_scan([chain_from(q)], {SYMBOL: hist}, cfg, asof=ASOF)
    print(f"  {label:8s} quote_at on every leg -> passed {len(res.passed)} (was 224), "
          f"QUOTE_AGE_UNKNOWN rejections {res.rejections.get('QUOTE_AGE_UNKNOWN', 0)}")

# ---------------------------------------------------------------------------
banner(7, "Break-even realised volatility of the top pick, and what the card now says")
ch = chain_from(skewed_quotes(atm_iv=0.25))
res = run_scan([ch], {SYMBOL: hist}, cfg, asof=ASOF)
top = res.passed[0]
exp = next(x for x in ch.expiries if x.expiration == top.expiration)
legs = tuple(Leg(next(q for q in exp.quotes if q.right == l["right"] and q.strike == l["strike"]), l["side"])
             for l in top.legs)
s = Structure(top.family, top.shape, SYMBOL, top.expiration, legs)
T = top.trading_days / 252.0
z = RNG.standard_normal(400_000)
print(f"  {top.shape} {top.description}, {top.expiration}: card shows forecast {top.forecast_ev_usd:+.0f}, "
      f"market {top.implied_ev_usd:+.0f}, blend {top.conservative_ev_usd:+.0f}, stress {top.stress_ev_usd:+.0f}, "
      f"P(max loss) {top.p_max_loss:.0%}, win {top.pop:.0%}")
for vol in (0.15, 0.19, 0.23, 0.25, 0.28):
    r = -0.5 * vol * vol * T + vol * math.sqrt(T) * z
    r -= math.log(np.mean(np.exp(r)))
    v = pnl(s, exp.forward * np.exp(r), cfg.cost)
    print(f"    realised {vol:.0%}: EV {v.mean():+6.1f}   P(profit) {np.mean(v > 0):.0%}   P(max loss) {np.mean(v < -0.95 * top.max_loss_usd):.0%}")

# ---------------------------------------------------------------------------
banner(9, "Event detection with <= 2 expiries")
two = chain_from(skewed_quotes(atm_iv=0.25, expiries=EXPIRIES[:2]))
res = run_scan([two], {SYMBOL: hist}, cfg, asof=ASOF)
print(f"  single name, 2 expiries: passed {len(res.passed)}, blocked {dict(res.chains_blocked)}")
etf = chain_from(skewed_quotes(atm_iv=0.25, expiries=EXPIRIES[:2]), underlying="SPY")
res = run_scan([etf], {"SPY": hist}, cfg, asof=ASOF)
print(f"  ETF (no earnings), 2 expiries: passed {len(res.passed)}, blocked {dict(res.chains_blocked)}")

# ---------------------------------------------------------------------------
banner(10, "Track-record verdict: clustered by expiry day, 60-day minimum")
# 30 settled picks over 6 expiry days, strongly positive in-sample.
rng = np.random.default_rng(1)
by_day = {f"d{i}": [float(x) for x in rng.choice([400.0, -200.0], size=5, p=[0.7, 0.3])] for i in range(6)}
pnls = [x for v in by_day.values() for x in v]
card = Scorecard(picks=30, settled=30, open=0, wins=sum(x > 0 for x in pnls), expiry_days=6,
                 total_pnl_usd=sum(pnls), total_risk_usd=6000, predicted_ev_usd=900,
                 avg_pnl_usd=float(np.mean(pnls)), pnl_ci95_usd=cluster_bootstrap_ci(by_day),
                 hit_rate=0.7, predicted_hit_rate=0.66, max_drawdown_usd=-400, worst_day_usd=-400,
                 near_strike_settlements=0)
print(f"  30 settled trades, 6 expiry days, mean {card.avg_pnl_usd:+.0f}: verdict -> {verdict(card)[1]!r}")
print(f"  naive per-trade 95% CI would be {np.mean(pnls) - 1.96 * np.std(pnls, ddof=1) / math.sqrt(30):+.0f} to "
      f"{np.mean(pnls) + 1.96 * np.std(pnls, ddof=1) / math.sqrt(30):+.0f}; cluster bootstrap by day: "
      f"{card.pnl_ci95_usd[0]:+.0f} to {card.pnl_ci95_usd[1]:+.0f}")

# ---------------------------------------------------------------------------
banner(11, "Engine step cost at production scale (48 chains)")
chains = [build_chain(f"S{i:02d}", ASOF, skewed_quotes(atm_iv=0.18 + 0.002 * i), snapshot_id=i, spot=100.0,
                      source="T", min_dte=7, max_dte=45) for i in range(48)]
closes = {f"S{i:02d}": history(0.12 + 0.004 * i, seed=i) for i in range(48)}
t0 = time.time()
res = run_scan(chains, closes, cfg, asof=ASOF)
dt = time.time() - t0
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
print(f"  48 chains: {dt:.1f} s, structures scored {res.structures_scored:,}, passed {len(res.passed):,}, "
      f"picks {len(res.picks)}, peak RSS {rss:.0f} MiB")
print(f"  top-5: {[(c.underlying, c.shape, round(c.score, 3), round(c.p_max_loss, 2)) for c in res.picks]}")
