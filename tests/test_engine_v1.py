"""Christiania trade engine: models, chains, structures, gates, pipeline, ledger, worker."""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from src.database.repository import get_connection
from src.engine.chains import (
    NY, Quote, black76_price, build_chain, calendar_years_to_expiry, implied_vol,
    parity_forward,
)
from src.engine.history import (
    fetch_eod_closes, history_status, last_completed_session, parse_eod_rows, settlement_price,
)
from src.engine.intraday import (
    IntradayHistory, IntradaySession, parse_ohlc_sessions, refresh_intraday,
    zero_dte_distributions,
)
from src.engine.ledger import (
    close_trade, cluster_bootstrap_ci, drawdown, exposure, latest_scan, pick_pnl_at,
    picks_with_outcomes, prune_candidates, record_scan, record_trade, scorecard,
    session_picks, settle_due_picks, settle_due_trades, trades_with_closes, verdict,
)
from src.engine.models import (
    EMPIRICAL, IMPLIED, VOL_FORECAST, ModelUnavailable, empirical_distribution,
    implied_event_variance, lognormal,
)
from src.engine.pipeline import (
    LANE_MAIN, EngineConfig, event_blackout_from_env, main_config, run_scan,
    trading_days_to_expiry, zero_dte_config,
)
from src.engine.structures import CostPolicy, Leg, Structure, liquid, pnl

ASOF = datetime(2026, 11, 4, 16, 0, tzinfo=UTC)  # Wednesday 11:00 New York
EXPIRIES = ("2026-11-13", "2026-11-20", "2026-12-04", "2026-12-18")


def synthetic_quotes(asof=ASOF, spot=100.0, iv=0.25, expiries=EXPIRIES, quote_at=None,
                     strikes=None, oi=None, wing_quote=None):
    quotes = []
    stamp = (quote_at or asof).isoformat() if quote_at is not False else None
    for exp in expiries:
        t = calendar_years_to_expiry(asof, exp)
        f = spot * math.exp(0.04 * t)
        for k in (strikes if strikes is not None else np.arange(70, 131, 1.0)):
            for right in "CP":
                p = black76_price(right, f, float(k), t, iv)
                if p < 0.03:
                    continue
                spread = max(0.02, 0.04 * p)
                bid, ask = round(p - spread / 2, 2), round(p + spread / 2, 2)
                if wing_quote and p < wing_quote[0]:
                    bid, ask = wing_quote[1], wing_quote[2]
                quotes.append(Quote(right, float(k), exp, bid, ask, stamp, oi))
    return quotes


def history(vol: float, n: int = 400, seed: int = 7) -> list[float]:
    rng = np.random.default_rng(seed)
    return list(100 * np.exp(np.cumsum(rng.normal(0, vol / math.sqrt(252), n))))


def chain(iv=0.25, underlying="SPY", **kw):
    return build_chain(underlying, ASOF, synthetic_quotes(iv=iv, **kw), snapshot_id=None,
                       spot=100.0, source="TEST", min_dte=7, max_dte=45)


def cfg(**overrides) -> EngineConfig:
    base = main_config()
    return EngineConfig(**{**base.__dict__, **overrides})


# --------------------------------------------------------------------- models
def test_lognormal_is_a_martingale_around_the_forward():
    d = lognormal(VOL_FORECAST, "X", 0.04)
    assert np.mean(np.exp(d.log_returns)) == pytest.approx(1.0, abs=1e-12)
    assert np.var(d.log_returns) == pytest.approx(0.04, rel=0.01)


def test_empirical_distribution_is_demeaned_and_needs_history():
    trending = list(100 * np.exp(np.linspace(0, 1, 300)))
    d = empirical_distribution(trending, 10)
    assert np.mean(np.exp(d.log_returns)) == pytest.approx(1.0, abs=1e-12)
    with pytest.raises(ModelUnavailable):
        empirical_distribution(trending[:40], 10)


def test_event_variance_detected_only_in_the_jump_interval_and_carried_forward():
    flat = [(0.02, 0.20), (0.04, 0.20), (0.06, 0.20), (0.08, 0.20)]
    assert implied_event_variance(flat) == [0, 0, 0, 0]
    w = [0.20 ** 2 * 0.02, 0.20 ** 2 * 0.04, 0.20 ** 2 * 0.06 + 0.004, 0.20 ** 2 * 0.08 + 0.004]
    term = [(t, math.sqrt(v / t)) for t, v in zip((0.02, 0.04, 0.06, 0.08), w)]
    ev = implied_event_variance(term)
    assert ev[0] == ev[1] == 0
    assert ev[2] == pytest.approx(0.004, rel=0.05)
    assert ev[3] == pytest.approx(ev[2])


# --------------------------------------------------------------------- chains
def test_parity_forward_and_implied_vol_recover_inputs():
    c = chain(iv=0.31)
    e = c.expiries[-1]
    t = calendar_years_to_expiry(ASOF, e.expiration)
    assert e.forward == pytest.approx(100 * math.exp(0.04 * t), abs=0.05)
    assert e.atm_iv == pytest.approx(0.31, abs=0.01)
    assert implied_vol("C", 0.0, 100, 100, 0.1) is None


def test_parity_forward_none_without_two_sided_pairs():
    assert parity_forward([Quote("C", 100, EXPIRIES[0], None, 1.0)], 0.05) is None


# ----------------------------------------------------------------- structures
def _q(right, k, bid, ask, oi=None):
    return Quote(right, k, "2026-12-18", bid, ask, ASOF.isoformat(), oi)


def test_put_credit_spread_fill_payoff_and_max_loss():
    s = Structure("CREDIT_SPREAD", "PUT_CREDIT_SPREAD", "TEST", "2026-12-18",
                  (Leg(_q("P", 95, 1.00, 1.10), -1), Leg(_q("P", 90, 0.40, 0.50), +1)))
    cost = CostPolicy(slippage_fraction=0.5, commission_per_contract=0.65)
    assert s.entry_cash_per_share(0.5) == pytest.approx(0.55)
    out = pnl(s, np.array([50.0, 92.5, 120.0]), cost)
    assert out[0] == pytest.approx(-500 + 55 - 1.30)
    assert out[1] == pytest.approx(-250 + 55 - 1.30)
    assert out[2] == pytest.approx(55 - 1.30)


def test_frozen_pick_pnl_matches_structure_pnl():
    s = Structure("IRON_FLY", "IRON_FLY", "TEST", "2026-12-18",
                  (Leg(_q("P", 90, 0.4, 0.5), +1), Leg(_q("P", 100, 3.0, 3.2), -1),
                   Leg(_q("C", 100, 3.1, 3.3), -1), Leg(_q("C", 110, 0.5, 0.6), +1)))
    cost = CostPolicy()
    record = {"legs": [{"right": l.right, "strike": l.strike, "side": l.side} for l in s.legs],
              "entry_cash_usd": s.entry_cash_per_share(cost.slippage_fraction) * 100,
              "commission_usd": cost.commission(s)}
    for px in (80.0, 96.0, 100.0, 104.0, 130.0):
        assert pick_pnl_at(record, px) == pytest.approx(float(pnl(s, np.array([px]), cost)[0]))


def test_liquidity_gate_fails_closed_on_no_bid_wide_spread_and_ignores_missing_oi():
    def spread(short, long):
        return Structure("CREDIT_SPREAD", "PUT_CREDIT_SPREAD", "T", "2026-12-18",
                         (Leg(short, -1), Leg(long, +1)))
    good = spread(_q("P", 95, 1.00, 1.10), _q("P", 90, 0.40, 0.50))
    assert liquid(good, max_relative_spread=0.5, min_bid=0.05) is None
    wing = spread(_q("P", 95, 1.00, 1.10), _q("P", 80, 0.01, 0.06))
    assert liquid(wing, max_relative_spread=0.5, min_bid=0.05) == "NO_REAL_MARKET"
    wide = spread(_q("P", 95, 1.00, 1.10), _q("P", 90, 0.10, 0.20))
    assert liquid(wide, max_relative_spread=0.5, min_bid=0.05) == "WIDE_SPREAD"
    assert liquid(good, max_relative_spread=0.5, min_bid=0.05, min_open_interest=50) is None
    thin = spread(_q("P", 95, 1.00, 1.10, oi=3), _q("P", 90, 0.40, 0.50, oi=3))
    assert liquid(thin, max_relative_spread=0.5, min_bid=0.05, min_open_interest=50) == "LOW_OPEN_INTEREST"


# ------------------------------------------------------------------- pipeline
def test_rich_implied_vol_versus_calm_history_passes_with_mixture_scoring():
    res = run_scan([chain(iv=0.25)], {"SPY": history(0.15)}, main_config(), asof=ASOF)
    assert res.passed, dict(res.rejections)
    top = res.passed[0]
    assert top.is_credit and top.models_agree
    w = top.forecast_weight
    assert top.conservative_ev_usd == pytest.approx(
        w * top.forecast_ev_usd + (1 - w) * top.implied_ev_usd, abs=0.02)
    assert top.forecast_ev_usd == pytest.approx(
        min(top.scores[VOL_FORECAST].ev_usd, top.scores[EMPIRICAL].ev_usd), abs=0.01)
    assert top.implied_ev_usd < 0                      # the market's own view: minus costs
    assert top.stress_ev_usd < top.forecast_ev_usd    # a shock can only hurt a short-vol trade
    assert top.score == pytest.approx(top.conservative_ev_usd / top.cvar95_usd, abs=0.001)
    assert 0 < top.p_max_loss < 1 and 0 < top.pop < 1
    assert top.cvar95_usd >= 0.10 * top.max_loss_usd


def test_gate_requires_a_real_gap_between_implied_and_forecast_volatility():
    """At the forecast's own level nothing passes; two points above it almost nothing."""
    hist = history(0.15)
    at_forecast = run_scan([chain(iv=0.145)], {"SPY": hist}, main_config(), asof=ASOF)
    assert at_forecast.passed == []
    two_points = run_scan([chain(iv=0.165)], {"SPY": hist}, main_config(), asof=ASOF)
    assert len(two_points.passed) < 0.10 * max(1, two_points.structures_scored)


def test_cheap_implied_vol_versus_wild_history_sells_no_premium():
    res = run_scan([chain(iv=0.15)], {"SPY": history(0.45)}, main_config(), asof=ASOF)
    assert not any(c.is_credit for c in res.passed)


def test_without_history_nothing_passes_and_chain_is_flagged():
    res = run_scan([chain(iv=0.25)], {}, main_config(), asof=ASOF)
    assert res.passed == []
    assert res.chains_without_history == ["SPY"]
    assert res.rejections["MODEL_UNAVAILABLE"] > 0


def test_stale_or_unknown_quote_age_never_passes():
    old = ASOF - timedelta(hours=3)
    stale = run_scan([chain(iv=0.25, quote_at=old)], {"SPY": history(0.15)}, main_config(), asof=ASOF)
    assert stale.passed == [] and stale.rejections["STALE_QUOTE"] > 0
    unknown = run_scan([chain(iv=0.25, quote_at=False)], {"SPY": history(0.15)}, main_config(), asof=ASOF)
    assert unknown.passed == [] and unknown.rejections["QUOTE_AGE_UNKNOWN"] > 0


def test_no_real_market_wings_are_rejected_before_scoring():
    res = run_scan([chain(iv=0.25, wing_quote=(0.08, 0.01, 0.06))], {"SPY": history(0.15)},
                   main_config(), asof=ASOF)
    assert res.rejections["NO_REAL_MARKET"] > 0
    assert not any(l["bid"] == 0.01 for c in res.passed for l in c.legs)


def test_single_name_with_two_expiries_is_blocked_etf_is_not():
    hist = history(0.15)
    single = chain(iv=0.25, underlying="NVDA", expiries=EXPIRIES[:2])
    res = run_scan([single], {"NVDA": hist}, main_config(), asof=ASOF)
    assert res.chains_blocked == {"NVDA": "EVENT_UNDETECTABLE"} and res.passed == []
    etf = chain(iv=0.25, underlying="SPY", expiries=EXPIRIES[:2])
    assert run_scan([etf], {"SPY": hist}, main_config(), asof=ASOF).passed


def test_event_blackout_rejects_expiries_spanning_the_event():
    assert event_blackout_from_env("NVDA:2026-11-19, junk, AAPL:bad") == {"NVDA": date(2026, 11, 19)}
    res = run_scan([chain(iv=0.25, underlying="NVDA")], {"NVDA": history(0.15)}, main_config(),
                   asof=ASOF, blackout={"NVDA": date(2026, 11, 19)})
    assert res.rejections["EVENT_BLACKOUT"] > 0
    assert all(c.expiration < "2026-11-19" for c in res.passed)


def test_picks_are_one_per_underlying_best_first():
    a = chain(iv=0.25)
    b = build_chain("QQQ", ASOF, synthetic_quotes(iv=0.24), snapshot_id=None, spot=100.0,
                    source="TEST", min_dte=7, max_dte=45)
    res = run_scan([a, b], {"SPY": history(0.15), "QQQ": history(0.15, seed=3)},
                   main_config(), asof=ASOF)
    assert [c.underlying for c in res.picks] == sorted({"SPY", "QQQ"}, key=lambda u: [c.underlying for c in res.passed].index(u))
    assert len({c.underlying for c in res.picks}) == len(res.picks) <= main_config().top_n


def test_trading_days_counts_remaining_session_fraction():
    days = trading_days_to_expiry(ASOF, "2026-11-06")
    assert days == pytest.approx(2 + 5 / 6.5, abs=0.01)
    assert trading_days_to_expiry(ASOF, "2026-11-03") == 0.0


def test_commission_default_is_saxo_classic_tier(monkeypatch):
    monkeypatch.delenv("CHRISTIANIA_COMMISSION_PER_CONTRACT", raising=False)
    assert main_config().cost.commission_per_contract == 2.00


# ----------------------------------------------------------------------- 0DTE
def intraday_sessions(n=60, seed=5, vol=0.12):
    rng = np.random.default_rng(seed)
    out = []
    day = date(2026, 8, 1)
    while len(out) < n:
        day += timedelta(days=1)
        if day.weekday() >= 5:
            continue
        minutes = tuple(9 * 60 + 35 + 5 * i for i in range(78))
        path = 100 * np.exp(np.cumsum(rng.normal(0, vol / math.sqrt(252 * 78), 78)))
        out.append(IntradaySession(day.isoformat(), minutes, tuple(float(x) for x in path)))
    return out


def test_zero_dte_distributions_use_remaining_session_returns():
    sessions = intraday_sessions()
    closes = {s.session_date: s.last_close for s in sessions}
    hist = IntradayHistory("SPY", tuple(sessions), closes)
    asof = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)   # 10:00 NY
    d = zero_dte_distributions(hist, asof=asof, expiration="2026-11-04", today=date(2026, 11, 4))
    assert set(d) == {VOL_FORECAST, EMPIRICAL}
    assert "10:00" in d[EMPIRICAL].note and len(d[EMPIRICAL].log_returns) == 60
    late = zero_dte_distributions(hist, asof=datetime(2026, 11, 4, 20, 30, tzinfo=UTC),
                                  expiration="2026-11-04", today=date(2026, 11, 4))
    assert late[EMPIRICAL].horizon_variance < d[EMPIRICAL].horizon_variance
    nxt = zero_dte_distributions(hist, asof=asof, expiration="2026-11-05", today=date(2026, 11, 4))
    assert nxt[EMPIRICAL].horizon_variance > d[EMPIRICAL].horizon_variance
    with pytest.raises(ModelUnavailable):
        zero_dte_distributions(IntradayHistory("SPY", tuple(sessions[:10]), closes), asof=asof,
                               expiration="2026-11-04", today=date(2026, 11, 4))


def test_zero_dte_lane_scores_only_with_intraday_history():
    q = synthetic_quotes(iv=0.30, expiries=("2026-11-04", "2026-11-05"),
                         strikes=np.arange(90, 110.5, 0.5))
    c = build_chain("SPY", ASOF, q, snapshot_id=None, spot=100.0, source="TEST",
                    min_dte=0, max_dte=1)
    sessions = intraday_sessions(vol=0.10)
    hist = IntradayHistory("SPY", tuple(sessions), {s.session_date: s.last_close for s in sessions})
    res = run_scan([c], {}, zero_dte_config(), asof=ASOF, intraday_by_symbol={"SPY": hist})
    assert res.structures_scored > 0 and res.chains_without_history == []
    assert all(p.expiration in {"2026-11-04", "2026-11-05"} for p in res.passed)
    none = run_scan([c], {}, zero_dte_config(), asof=ASOF)
    assert none.passed == [] and none.chains_without_history == ["SPY"]


def test_parse_ohlc_sessions_groups_bars_and_drops_partial_days():
    rows = []
    for d, n in (("2026-11-03", 78), ("2026-11-04", 10)):
        for i in range(n):
            rows.append({"timestamp": f"{d}T{9 + (30 + 5 * i) // 60:02d}:{(30 + 5 * i) % 60:02d}:00",
                         "open": 100, "high": 101, "low": 99, "close": 100 + i * 0.01, "volume": 1})
    sessions = parse_ohlc_sessions({"response": rows})
    assert [s.session_date for s in sessions] == ["2026-11-03"]
    assert sessions[0].minutes[0] == 9 * 60 + 35 and sessions[0].price_at(9 * 60 + 34) is None


# --------------------------------------------------------------------- ledger
def seed_scan(conn, asof, iv=0.25, underlying="SPY", spot=100.0):
    expiries = tuple((asof.date() + timedelta(days=k)).isoformat() for k in (9, 16, 30, 44))
    q = synthetic_quotes(asof=asof, iv=iv, spot=spot, expiries=expiries)
    c = build_chain(underlying, asof, q, snapshot_id=None, spot=spot, source="T", min_dte=7, max_dte=45)
    res = run_scan([c], {underlying: history(0.15)}, main_config(), asof=asof)
    return record_scan(conn, res, completed_at=asof), res


def test_picks_freeze_once_per_session_at_the_decision_scan(db_path):
    conn = get_connection(db_path)
    early = datetime(2026, 11, 4, 14, 45, tzinfo=UTC)          # 09:45 NY: no decision yet
    seed_scan(conn, early)
    assert session_picks(conn, LANE_MAIN, "2026-11-04") == []
    # Seven scans with a drifting forward from 10:00 on: exactly one pick, from the first.
    first_id = None
    for i, spot in enumerate(np.arange(100.0, 100.61, 0.1)):
        sid, res = seed_scan(conn, datetime(2026, 11, 4, 15, 0, tzinfo=UTC) + timedelta(minutes=15 * i),
                             spot=float(spot))
        first_id = first_id or sid
    picks = session_picks(conn, LANE_MAIN, "2026-11-04")
    assert len(picks) == 1 and picks[0]["first_scan_id"] == first_id
    assert conn.execute("SELECT COUNT(*) FROM engine_scans WHERE decision=1").fetchone()[0] == 1
    # The next session freezes again.
    seed_scan(conn, datetime(2026, 11, 5, 15, 5, tzinfo=UTC))
    assert len(picks_with_outcomes(conn)) == 2
    with pytest.raises(sqlite3.DatabaseError):
        with conn:
            conn.execute("UPDATE engine_picks SET conservative_ev_usd=999")
    conn.close()


def test_settlement_flags_near_strike_and_after_hours_and_waits_for_the_close(db_path):
    conn = get_connection(db_path)
    _, res = seed_scan(conn, datetime(2026, 11, 4, 15, 5, tzinfo=UTC))
    pick = picks_with_outcomes(conn)[0]
    exp = pick["expiration"]
    short = min(float(l["strike"]) for l in pick["record"]["legs"] if l["side"] < 0)
    with conn:
        conn.execute(
            "INSERT INTO engine_daily_closes VALUES (?,?,?,'THETADATA_EOD','x',?,1)",
            ("SPY", exp, short + 0.01, f"{exp}T16:05:00"),
        )
    noon = datetime.combine(date.fromisoformat(exp), datetime.min.time(), NY).replace(hour=12)
    assert settle_due_picks(conn, now=noon) == 0
    assert settle_due_picks(conn, now=datetime(2026, 12, 20, 15, 0, tzinfo=UTC)) == 1
    settled = picks_with_outcomes(conn)[0]
    assert settled["near_strike"] == 1 and settled["settlement_after_hours"] == 1
    assert settled["pnl_usd"] == pytest.approx(pick_pnl_at(pick["record"], short + 0.01), abs=0.01)
    assert latest_scan(conn, LANE_MAIN)["decision"] == 1
    conn.close()


def test_real_trades_record_close_settle_and_exposure(db_path):
    conn = get_connection(db_path)
    _, res = seed_scan(conn, datetime(2026, 11, 4, 15, 5, tzinfo=UTC))
    rec = res.picks[0].to_record()
    taken = datetime(2026, 11, 4, 15, 20, tzinfo=UTC)
    fill = rec["entry_cash_usd"] / 100 - 0.05          # a nickel worse than modelled
    t1 = record_trade(conn, rec, lots=2, fill_per_share=fill, commission_usd=16.0, taken_at=taken)
    t2 = record_trade(conn, rec, lots=1, fill_per_share=fill, commission_usd=8.0, taken_at=taken)
    trades = trades_with_closes(conn)
    assert len(trades) == 2 and all(t["pnl_usd"] is None for t in trades)
    assert trades[0]["max_loss_usd"] == pytest.approx((rec["max_loss_usd"] + 5) * trades[0]["lots"], abs=0.01)
    ex = exposure(trades, today=date(2026, 11, 4))
    assert ex.open_trades == 2 and ex.trades_today == 2
    assert ex.open_risk_usd == pytest.approx(sum(t["max_loss_usd"] for t in trades))
    assert set(ex.by_group) == {"Index/sector ETFs"}
    # Manual close of t1 by buying back at a quarter of the credit.
    pnl1 = close_trade(conn, t1, cash_per_share=-fill / 4, commission_usd=16.0,
                       closed_at=taken + timedelta(days=5))
    assert pnl1 == pytest.approx((fill * 0.75) * 100 * 2 - 32.0, abs=0.01)
    # t2 settles at expiry.
    with conn:
        conn.execute("INSERT INTO engine_daily_closes VALUES ('SPY',?,100.0,'THETADATA_EOD','x',NULL,0)",
                     (rec["expiration"],))
    assert settle_due_trades(conn, now=datetime(2026, 12, 20, 15, 0, tzinfo=UTC)) == 1
    done = {t["id"]: t for t in trades_with_closes(conn)}
    assert done[t2]["close_kind"] == "EXPIRY" and done[t1]["close_kind"] == "MANUAL"
    assert exposure(list(done.values()), today=date(2026, 12, 20)).open_trades == 0
    with pytest.raises(sqlite3.DatabaseError):
        with conn:
            conn.execute("DELETE FROM engine_trades")
    conn.close()


def test_scorecard_clusters_by_expiry_day_and_verdict_waits_for_sixty_days():
    def pick(day, pnl):
        return {"pnl_usd": pnl, "settlement_date": day, "max_loss_usd": 200.0,
                "conservative_ev_usd": 20.0, "near_strike": 0, "record": {"pop": 0.6}}
    few = [pick("2026-11-20", 50), pick("2026-11-20", -200), pick("2026-11-27", 40), {"pnl_usd": None,
           "settlement_date": None, "max_loss_usd": 200.0, "conservative_ev_usd": 20.0, "record": {}}]
    card = scorecard(few)
    assert card.expiry_days == 2 and card.settled == 3 and card.open == 1
    assert card.worst_day_usd == -150 and card.max_drawdown_usd == -150
    assert verdict(card)[0] == "wait"
    rng = np.random.default_rng(1)
    many = [pick(f"2027-{1 + i // 28:02d}-{1 + i % 28:02d}", float(rng.choice([400, -200], p=[0.7, 0.3])))
            for i in range(70) for _ in range(3)]
    card = scorecard(many)
    assert card.expiry_days == 70 and card.pnl_ci95_usd is not None
    lo, hi = card.pnl_ci95_usd
    assert lo < card.avg_pnl_usd < hi
    assert verdict(card)[0] in {"good", "wait"}
    assert drawdown([10, 5, 20, -5, 0]) == -25
    assert cluster_bootstrap_ci({"d1": [1.0]}) is None


# -------------------------------------------------------------------- history
def test_parse_eod_rows_keys_by_session_date_flags_after_hours_and_skips_garbage():
    rows = parse_eod_rows({"response": [
        {"close": 101.5, "created": "2026-11-02T17:15:03.123", "last_trade": "2026-11-02T16:00:00.250"},
        {"close": 102.0, "created": "2026-11-03T17:15:00", "last_trade": "2026-11-03T19:59:58"},
        {"close": "bad", "created": "2026-11-04T17:15:00"},
        {"close": 0, "created": "2026-11-05T17:15:00"},
    ]})
    assert [(r.session_date, r.close, r.after_hours) for r in rows] == [
        ("2026-11-02", 101.5, False), ("2026-11-03", 102.0, True)]


class FakeTheta:
    base_url = "fake"

    def __init__(self, closes, intraday_vol=0.10):
        self.closes = closes
        self.intraday_vol = intraday_vol
        self.calls = []

    def _get_payload(self, path, params):
        self.calls.append((path, dict(params)))
        if path == "/stock/history/eod":
            start = datetime.strptime(params["start_date"], "%Y%m%d").date()
            end = datetime.strptime(params["end_date"], "%Y%m%d").date()
            assert (end - start).days < 365, "ThetaData caps one EOD request at 365 days"
            rows, day = [], start
            while day <= end:
                if day.weekday() < 5:
                    # Index by business day since a fixed epoch so chunked requests
                    # continue the same price path instead of restarting it.
                    i = int(np.busday_count("2020-01-01", day.isoformat()))
                    rows.append({"close": self.closes[i % len(self.closes)],
                                 "created": f"{day.isoformat()}T17:15:00",
                                 "last_trade": f"{day.isoformat()}T16:00:00"})
                day += timedelta(days=1)
            return {"response": rows}
        if path == "/stock/history/ohlc":
            start = datetime.strptime(params["start_date"], "%Y%m%d").date()
            end = datetime.strptime(params["end_date"], "%Y%m%d").date()
            assert (end - start).days <= 31, "multi-day OHLC requests are limited to one month"
            rng = np.random.default_rng(start.toordinal())
            rows, day = [], start
            while day <= end:
                if day.weekday() < 5:
                    px = 100.0
                    for i in range(78):
                        px *= math.exp(rng.normal(0, self.intraday_vol / math.sqrt(252 * 78)))
                        m = 9 * 60 + 30 + 5 * i
                        rows.append({"timestamp": f"{day.isoformat()}T{m // 60:02d}:{m % 60:02d}:00",
                                     "open": px, "high": px, "low": px, "close": px, "volume": 1})
                day += timedelta(days=1)
            return {"response": rows}
        if path == "/option/snapshot/quote":
            return {"response": []}
        raise AssertionError(path)


def test_eod_requests_are_chunked_and_history_status_reports_gaps(db_path):
    fake = FakeTheta(history(0.15, n=600))
    closes = fetch_eod_closes(fake, "SPY", date(2024, 10, 1), date(2026, 11, 3))
    assert len(fake.calls) == 3 and len(closes) > 500
    conn = get_connection(db_path)
    now = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)
    with conn:
        conn.executemany("INSERT INTO engine_daily_closes VALUES (?,?,100,'THETADATA_EOD','x',NULL,0)",
                         [("SPY", "2026-11-03"), ("QQQ", "2026-10-20")])
    status = history_status(conn, ["SPY", "QQQ", "NVDA"], now=now)
    assert (status.current, status.stale, status.missing) == (1, 1, 1)
    assert status.target == "2026-11-03" and status.oldest_gap_days == 10 and status.ok is False
    assert "1 with no history" in status.sentence()
    assert settlement_price(conn, "NVDA", "2026-11-03") is None
    conn.close()


def test_last_completed_session_respects_eod_report_time():
    assert last_completed_session(datetime(2026, 11, 4, 15, 0, tzinfo=UTC)) == date(2026, 11, 3)
    assert last_completed_session(datetime(2026, 11, 4, 23, 0, tzinfo=UTC)) == date(2026, 11, 4)
    assert last_completed_session(datetime(2026, 11, 2, 14, 0, tzinfo=UTC)) == date(2026, 10, 30)


def test_refresh_intraday_fetches_bounded_ranges_newest_first(db_path):
    conn = get_connection(db_path)
    fake = FakeTheta([100])
    now = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)
    status = refresh_intraday(conn, fake, ["SPY"], now=now, max_requests=2)
    assert status["SPY"].startswith("PARTIAL") or status["SPY"].startswith("FETCHED")
    stored = conn.execute("SELECT MIN(session_date), MAX(session_date), COUNT(*) FROM engine_intraday_sessions").fetchone()
    assert stored[1] == "2026-11-03" and stored[2] >= 30
    status = refresh_intraday(conn, fake, ["SPY"], now=now, max_requests=4)
    assert status["SPY"] in {"CURRENT"} or status["SPY"].startswith("FETCHED")
    assert refresh_intraday(conn, fake, ["SPY"], now=now, max_requests=4)["SPY"] == "CURRENT"
    assert all(p == "/stock/history/ohlc" for p, _ in fake.calls)
    conn.close()


# --------------------------------------------------------------------- worker
def seed_snapshot(db_path, underlying="SPY", captured=ASOF, iv=0.25):
    conn = get_connection(db_path)
    with conn:
        sid = conn.execute(
            """INSERT INTO market_snapshots (captured_at, underlying, provider, underlying_price,
               underlying_source, fx_source, us_session_date, us_session_state)
               VALUES (?, ?, 'THETADATA', NULL, 'UNKNOWN', 'UNKNOWN', ?, 'INTRADAY')""",
            (captured.isoformat().replace("+00:00", "Z"), underlying,
             captured.astimezone(NY).date().isoformat()),
        ).lastrowid
        naive_ny = captured.astimezone(NY).replace(tzinfo=None).isoformat()
        for q in synthetic_quotes(iv=iv):
            conn.execute(
                """INSERT INTO option_quotes (snapshot_id, right, strike, expiration, quote_at,
                   bid, bid_source, ask, ask_source, last_source, iv_source, delta_source,
                   gamma_source, theta_source, vega_source, volume_source, open_interest,
                   open_interest_source)
                   VALUES (?,?,?,?,?,?,'FETCHED',?,'FETCHED','UNKNOWN','UNKNOWN','UNKNOWN',
                           'UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN',NULL,'UNKNOWN')""",
                (sid, q.right, q.strike, q.expiration, naive_ny, q.bid, q.ask),
            )
    conn.close()
    return sid


def test_worker_step_end_to_end_records_scan_picks_and_history(db_path, monkeypatch):
    from src.engine.worker import run_engine_step

    monkeypatch.setenv("CHRISTIANIA_ZERO_DTE_SYMBOLS", "SPY")
    seed_snapshot(db_path)
    fake = FakeTheta(history(0.15, n=600))
    summary = run_engine_step(theta_client=fake, db_path=db_path, now=ASOF + timedelta(minutes=5))
    assert summary.errors == [], summary.errors
    assert summary.main_scan_id is not None and summary.main_passed > 0
    assert summary.closes["SPY"].startswith("FETCHED") and "SPY" in summary.intraday
    conn = get_connection(db_path)
    assert len(picks_with_outcomes(conn, LANE_MAIN)) == 1       # 11:05 NY is after the decision time
    assert latest_scan(conn, "ZERO_DTE") is not None            # live chain empty, scan still recorded
    conn.close()


def test_worker_isolates_provider_failures(db_path):
    from src.engine.worker import run_engine_step

    class Broken:
        base_url = "broken"

        def _get_payload(self, path, params):
            raise OSError("terminal down")

    seed_snapshot(db_path)
    summary = run_engine_step(theta_client=Broken(), db_path=db_path, now=ASOF + timedelta(minutes=5))
    assert summary.closes["SPY"].startswith("FAILED")
    assert summary.main_scan_id is not None and summary.main_passed == 0


def test_prune_keeps_decision_scans_and_recent_candidates(db_path):
    conn = get_connection(db_path)
    seed_scan(conn, datetime(2026, 9, 1, 15, 5, tzinfo=UTC))      # decision scan, old
    seed_scan(conn, datetime(2026, 9, 1, 15, 20, tzinfo=UTC))     # refresh scan, old
    seed_scan(conn, datetime(2026, 11, 4, 15, 20, tzinfo=UTC))    # recent
    before = conn.execute("SELECT COUNT(*) FROM engine_candidates").fetchone()[0]
    removed = prune_candidates(conn, now=datetime(2026, 11, 4, 16, 0, tzinfo=UTC))
    assert removed > 0
    kept = conn.execute(
        "SELECT DISTINCT s.decision, s.session_date FROM engine_candidates c JOIN engine_scans s ON s.id=c.scan_id"
    ).fetchall()
    assert (1, "2026-09-01") in [tuple(k) for k in kept] and (0, "2026-09-01") not in [tuple(k) for k in kept]
    assert conn.execute("SELECT COUNT(*) FROM engine_candidates").fetchone()[0] == before - removed
    conn.close()


# ------------------------------------------------------------------- reprice
class LiveTheta(FakeTheta):
    """FakeTheta that also serves a live option chain (synthetic, naive NY timestamps)."""

    def __init__(self, closes, iv=0.25, asof=ASOF):
        super().__init__(closes)
        self.iv, self.asof = iv, asof

    def _get_payload(self, path, params):
        if path == "/option/snapshot/quote":
            stamp = self.asof.astimezone(NY).replace(tzinfo=None).isoformat(timespec="seconds")
            return {"response": [
                {"expiration": q.expiration, "strike": q.strike, "right": q.right,
                 "bid": q.bid, "ask": q.ask, "timestamp": stamp}
                for q in synthetic_quotes(asof=self.asof, iv=self.iv)
            ]}
        return super()._get_payload(path, params)


def test_reprice_scores_the_same_structure_on_live_quotes(db_path):
    from src.engine.reprice import reprice
    from src.engine.worker import run_engine_step

    seed_snapshot(db_path)
    fake = LiveTheta(history(0.15, n=600))
    run_engine_step(theta_client=fake, db_path=db_path, now=ASOF + timedelta(minutes=5))
    conn = get_connection(db_path)
    pick = next(p["record"] for p in picks_with_outcomes(conn, LANE_MAIN)
                if p["record"]["entry_cash_usd"] > 0)
    live = reprice(pick, theta_client=fake, conn=conn, now=ASOF + timedelta(minutes=20))
    assert live.status == "OK" and live.candidate.structure_key == pick["structure_key"]
    assert live.candidate.entry_cash_usd == pytest.approx(pick["entry_cash_usd"], abs=1.0)
    # Vol has collapsed on the live chain: the same short-vol structure no longer passes.
    cheap = LiveTheta(history(0.15, n=600), iv=0.12)
    worse = reprice(pick, theta_client=cheap, conn=conn, now=ASOF + timedelta(minutes=20))
    assert worse.status == "OK" and not worse.candidate.passed
    # A leg without a live quote is reported, not priced.
    gone = reprice({**pick, "legs": [{**pick["legs"][0], "strike": 1.0}] + pick["legs"][1:]},
                   theta_client=fake, conn=conn, now=ASOF + timedelta(minutes=20))
    assert gone.status == "LEG_NOT_QUOTED" and "1P" in gone.detail or "1C" in gone.detail
    conn.close()


def test_record_trade_checks_fill_sign_and_exposure_counts_open_risk(db_path):
    from src.engine.ledger import exposure, record_trade, trades_with_closes
    from src.engine.worker import run_engine_step

    seed_snapshot(db_path)
    run_engine_step(theta_client=FakeTheta(history(0.15, n=600)), db_path=db_path,
                    now=ASOF + timedelta(minutes=5))
    conn = get_connection(db_path)
    rec = next(p["record"] for p in picks_with_outcomes(conn, LANE_MAIN)
               if p["record"]["entry_cash_usd"] > 0)  # a credit structure
    with pytest.raises(ValueError):
        record_trade(conn, rec, lots=1, fill_per_share=-1.0, commission_usd=8.0, taken_at=ASOF)
    record_trade(conn, rec, lots=2, fill_per_share=rec["entry_cash_usd"] / 100 - 0.05,
                 commission_usd=16.0, taken_at=ASOF)
    trades = trades_with_closes(conn)
    assert len(trades) == 1 and trades[0]["pnl_usd"] is None
    # Max loss at the real fill: 5 cents less credit per share, two lots.
    assert trades[0]["max_loss_usd"] == pytest.approx((rec["max_loss_usd"] + 5) * 2, abs=0.01)
    ex = exposure(trades, today=ASOF.astimezone(NY).date())
    assert ex.open_trades == 1 and ex.open_risk_usd == pytest.approx(trades[0]["max_loss_usd"])
    assert ex.trades_today == 1 and ex.after(100) == pytest.approx(ex.open_risk_usd + 100)
    conn.close()


def test_market_view_prices_skewed_structures_at_about_minus_costs():
    """Under the smile-implied distribution the market's own skew is not a free lunch."""
    from src.engine.pipeline import market_distribution

    def skewed(atm=0.22, put_skew=0.60):
        quotes = []
        for exp in EXPIRIES:
            t = calendar_years_to_expiry(ASOF, exp)
            f = 100 * math.exp(0.04 * t)
            for k in np.arange(70, 131, 1.0):
                m = math.log(k / f)
                iv = atm + (put_skew * -m if m < 0 else -0.10 * m)
                for right in "CP":
                    p = black76_price(right, f, float(k), t, iv)
                    if p < 0.03:
                        continue
                    sp = max(0.02, 0.04 * p)
                    quotes.append(Quote(right, float(k), exp, round(p - sp / 2, 2), round(p + sp / 2, 2),
                                        ASOF.isoformat(), None))
        return build_chain("SPY", ASOF, quotes, snapshot_id=None, spot=100.0, source="T",
                           min_dte=7, max_dte=45)

    cost = CostPolicy(0.5, 2.0)
    for put_skew in (0.0, 0.6):
        e = skewed(put_skew=put_skew).expiries[-1]
        market = market_distribution(e)
        spread = Structure("CREDIT_SPREAD", "PUT_CREDIT_SPREAD", "SPY", e.expiration,
                           (Leg(next(q for q in e.quotes if q.right == "P" and q.strike == 91), -1),
                            Leg(next(q for q in e.quotes if q.right == "P" and q.strike == 86), +1)))
        ev = float(pnl(spread, market.terminal_prices(e.forward), cost).mean())
        # The market prices the spread at its own (skewed) IVs: EV is roughly the costs,
        # never a positive edge from selling the skew.
        assert -12 < ev < 0, (put_skew, ev)
        assert market.note.startswith("smile") if put_skew else True


def test_eod_history_respects_the_terminal_limits(monkeypatch):
    """365-day cap, first-served-date clamp, rate-limit retry, partial-chunk tolerance."""
    from src.engine.history import fetch_eod_closes
    from src.providers.thetadata import ThetaDataResponseError

    monkeypatch.setattr("src.engine.history._time.sleep", lambda s: None)

    class Terminal:
        base_url = "fake"
        first_served = date(2023, 6, 1)

        def __init__(self):
            self.calls = []
            self.throttled_once = False

        def _get_payload(self, path, params):
            start = datetime.strptime(params["start_date"], "%Y%m%d").date()
            end = datetime.strptime(params["end_date"], "%Y%m%d").date()
            self.calls.append((start, end))
            if (end - start).days > 365:
                raise ThetaDataResponseError("ThetaData HTTP 400: Too many days between start and end date; max 365 days allowed")
            if start < self.first_served:
                raise ThetaDataResponseError("ThetaData HTTP 400: start date precedes the first available date")
            if not self.throttled_once:
                self.throttled_once = True
                raise ThetaDataResponseError("ThetaData HTTP 429: Too Many Requests")
            rows, day = [], start
            while day <= end:
                if day.weekday() < 5:
                    rows.append({"close": 100.0, "created": f"{day.isoformat()}T17:15:00",
                                 "last_trade": f"{day.isoformat()}T16:00:00"})
                day += timedelta(days=1)
            return {"response": rows}

    term = Terminal()
    closes = fetch_eod_closes(term, "SPY", date(2021, 6, 3), date(2024, 7, 1))
    assert all((e - s).days <= 364 for s, e in term.calls)
    assert min(s for s, _ in term.calls) >= date(2023, 6, 1)         # clamped, no wasted calls
    assert closes[0].session_date == "2023-06-01" and closes[-1].session_date == "2024-07-01"
    assert term.throttled_once                                        # the 429 was retried, not fatal

    # A tier that serves earlier data: override the clamp.
    monkeypatch.setenv("CHRISTIANIA_STOCK_HISTORY_FIRST_DATE", "2016-01-01")
    term2 = Terminal()
    term2.first_served = date(2016, 1, 1)
    closes = fetch_eod_closes(term2, "SPY", date(2021, 6, 3), date(2021, 12, 31))
    assert closes and closes[0].session_date == "2021-06-03"

    # Every chunk rejected: the error surfaces.
    term3 = Terminal()
    term3.first_served = date(2030, 1, 1)
    monkeypatch.setenv("CHRISTIANIA_STOCK_HISTORY_FIRST_DATE", "2023-06-01")
    with pytest.raises(ThetaDataResponseError):
        fetch_eod_closes(term3, "SPY", date(2024, 1, 1), date(2024, 6, 1))


def test_max_loss_per_lot_gate_rejects_oversized_structures(monkeypatch):
    monkeypatch.setenv("CHRISTIANIA_MAX_LOSS_PER_LOT_USD", "150")
    cfg = main_config()
    assert cfg.max_loss_per_lot_usd == 150.0
    res = run_scan([chain(iv=0.25)], {"SPY": history(0.15)}, cfg, asof=ASOF)
    assert all(c.max_loss_usd <= 150 for c in res.passed)
    assert res.rejections["MAX_LOSS_TOO_LARGE"] > 0


def test_eod_history_never_asks_for_the_future(monkeypatch):
    from src.engine.history import fetch_eod_closes

    seen = []

    class Term:
        base_url = "fake"

        def _get_payload(self, path, params):
            seen.append((params["start_date"], params["end_date"]))
            return {"response": []}

    problems: list[str] = []
    fetch_eod_closes(Term(), "SPY", date(2026, 1, 1), date(2026, 12, 28), today=date(2026, 11, 7),
                     problems=problems)
    assert seen and max(e for _, e in seen) == "20261107"


def test_splits_are_recognised_adjusted_and_settled_in_strike_units(db_path):
    from src.engine.history import (
        adjusted_closes, detect_splits, settlement_price, split_factor_between,
    )

    # A 10:1 split on day 4; a genuine -20% day on day 7 must not be treated as a split.
    raw = [("2024-06-03", 1200.0), ("2024-06-04", 1210.0), ("2024-06-05", 1190.0),
           ("2024-06-06", 1220.0), ("2024-06-07", 121.0), ("2024-06-10", 123.0),
           ("2024-06-11", 125.0), ("2024-06-12", 100.0), ("2024-06-13", 102.0)]
    splits = detect_splits(raw)
    assert splits == {"2024-06-07": 10.0}
    adj = adjusted_closes(raw)
    assert adj[:4] == pytest.approx([120.0, 121.0, 119.0, 122.0])
    assert adj[4:] == [121.0, 123.0, 125.0, 100.0, 102.0]
    assert split_factor_between(raw, "2024-06-05", "2024-06-13") == 10.0
    assert split_factor_between(raw, "2024-06-07", "2024-06-13") == 1.0   # entered after the split

    conn = get_connection(db_path)
    with conn:
        conn.executemany(
            "INSERT INTO engine_daily_closes (symbol, session_date, close, source, fetched_at) "
            "VALUES ('NVDA', ?, ?, 'THETADATA_EOD', 'x')", raw)
    # Pick entered 2024-06-05 with pre-split strikes settles at 102 x 10 = 1,020.
    s = settlement_price(conn, "NVDA", "2024-06-13", entered="2024-06-05")
    assert s.price == pytest.approx(1020.0) and s.raw_close == 102.0 and s.split_factor == 10.0
    # Models see a continuous series.
    from src.engine.history import load_closes
    series = load_closes(conn, "NVDA", before=date(2024, 6, 14))
    assert max(abs(math.log(b / a)) for a, b in zip(series, series[1:])) < 0.3
    conn.close()
