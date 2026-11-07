"""Christiania trade engine: models, chains, structures, pipeline, ledger, worker."""
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
from src.engine.history import last_completed_session, parse_eod_rows, settlement_price
from src.engine.ledger import (
    latest_scan, pick_pnl_at, picks_with_outcomes, record_scan, scorecard, settle_due_picks,
)
from src.engine.models import (
    EMPIRICAL, IMPLIED, VOL_FORECAST, ModelUnavailable, empirical_distribution,
    implied_event_variance, lognormal,
)
from src.engine.pipeline import (
    LANE_MAIN, main_config, run_scan, trading_days_to_expiry, zero_dte_config,
)
from src.engine.structures import CostPolicy, Leg, Structure, pnl

ASOF = datetime(2026, 11, 4, 16, 0, tzinfo=UTC)  # Wednesday 11:00 New York
EXPIRIES = ("2026-11-13", "2026-11-20", "2026-12-04", "2026-12-18")


def synthetic_quotes(asof=ASOF, spot=100.0, iv=0.25, expiries=EXPIRIES, quote_at=None,
                     strikes=None, oi=500):
    quotes = []
    stamp = (quote_at or asof).isoformat()
    for exp in expiries:
        t = calendar_years_to_expiry(asof, exp)
        f = spot * math.exp(0.04 * t)
        for k in (strikes if strikes is not None else np.arange(70, 131, 1.0)):
            for right in "CP":
                p = black76_price(right, f, float(k), t, iv)
                if p < 0.03:
                    continue
                spread = max(0.02, 0.04 * p)
                quotes.append(Quote(right, float(k), exp, round(p - spread / 2, 2),
                                    round(p + spread / 2, 2), stamp, oi))
    return quotes


def history(vol: float, n: int = 400, seed: int = 7) -> list[float]:
    rng = np.random.default_rng(seed)
    return list(100 * np.exp(np.cumsum(rng.normal(0, vol / math.sqrt(252), n))))


def chain(iv=0.25, **kw):
    return build_chain("TEST", ASOF, synthetic_quotes(iv=iv, **kw), snapshot_id=None,
                       spot=100.0, source="TEST", min_dte=7, max_dte=45)


# --------------------------------------------------------------------- models
def test_lognormal_is_a_martingale_around_the_forward():
    d = lognormal(VOL_FORECAST, "X", 0.04)
    assert np.mean(np.exp(d.log_returns)) == pytest.approx(1.0, abs=1e-12)
    assert np.var(d.log_returns) == pytest.approx(0.04, rel=0.01)


def test_empirical_distribution_is_demeaned_and_needs_history():
    trending = list(100 * np.exp(np.linspace(0, 1, 300)))  # pure uptrend
    d = empirical_distribution(trending, 10)
    assert np.mean(np.exp(d.log_returns)) == pytest.approx(1.0, abs=1e-12)
    with pytest.raises(ModelUnavailable):
        empirical_distribution(trending[:40], 10)


def test_event_variance_detected_only_in_the_jump_interval_and_carried_forward():
    flat = [(0.02, 0.20), (0.04, 0.20), (0.06, 0.20), (0.08, 0.20)]
    assert implied_event_variance(flat) == [0, 0, 0, 0]
    # A big jump in total variance between the 2nd and 3rd expiry (earnings).
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
def _q(right, k, bid, ask):
    return Quote(right, k, "2026-12-18", bid, ask, ASOF.isoformat(), 1000)


def test_put_credit_spread_fill_payoff_and_max_loss():
    s = Structure("CREDIT_SPREAD", "PUT_CREDIT_SPREAD", "TEST", "2026-12-18",
                  (Leg(_q("P", 95, 1.00, 1.10), -1), Leg(_q("P", 90, 0.40, 0.50), +1)))
    cost = CostPolicy(slippage_fraction=0.5, commission_per_contract=0.65)
    # sell at 1.05-0.025 = 1.025, buy at 0.45+0.025 = 0.475 -> 0.55 credit
    assert s.entry_cash_per_share(0.5) == pytest.approx(0.55)
    prices = np.array([50.0, 92.5, 120.0])
    out = pnl(s, prices, cost)
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


# ------------------------------------------------------------------- pipeline
def test_rich_implied_vol_versus_calm_history_surfaces_premium_selling():
    res = run_scan([chain(iv=0.25)], {"TEST": history(0.15)}, main_config(), asof=ASOF)
    assert res.passed, dict(res.rejections)
    top = res.passed[0]
    assert top.family in {"CREDIT_SPREAD", "IRON_CONDOR", "IRON_FLY"}
    assert top.is_credit and top.models_agree
    assert top.conservative_ev_usd == pytest.approx(
        min(top.scores[VOL_FORECAST].ev_usd, top.scores[EMPIRICAL].ev_usd), abs=0.01)
    # Under the market's own distribution the trade is worth about minus costs.
    assert top.scores[IMPLIED].ev_usd < 0
    assert top.max_loss_usd > 0 and top.ev_per_risk >= main_config().min_ev_per_risk


def test_cheap_implied_vol_versus_wild_history_sells_no_premium():
    res = run_scan([chain(iv=0.15)], {"TEST": history(0.45)}, main_config(), asof=ASOF)
    assert not any(c.is_credit for c in res.passed)


def test_without_history_nothing_passes_and_chain_is_flagged():
    res = run_scan([chain(iv=0.25)], {}, main_config(), asof=ASOF)
    assert res.passed == []
    assert res.chains_without_history == ["TEST"]
    assert res.rejections["MODEL_UNAVAILABLE"] > 0


def test_stale_quotes_never_pass():
    old = ASOF - timedelta(hours=3)
    res = run_scan([chain(iv=0.25, quote_at=old)], {"TEST": history(0.15)}, main_config(),
                   asof=ASOF)
    assert res.passed == []
    assert res.rejections["STALE_QUOTE"] > 0


def test_picks_are_diversified_one_per_underlying_first():
    a = chain(iv=0.25)
    b = build_chain("OTHER", ASOF, synthetic_quotes(iv=0.24), snapshot_id=None, spot=100.0,
                    source="TEST", min_dte=7, max_dte=45)
    res = run_scan([a, b], {"TEST": history(0.15), "OTHER": history(0.15, seed=3)},
                   main_config(), asof=ASOF)
    assert {c.underlying for c in res.picks[:2]} == {"TEST", "OTHER"}


def test_trading_days_counts_remaining_session_fraction():
    days = trading_days_to_expiry(ASOF, "2026-11-06")  # Wed 11:00 -> Fri expiry
    assert days == pytest.approx(2 + 5 / 6.5, abs=0.01)
    assert trading_days_to_expiry(ASOF, "2026-11-03") == 0.0


def test_zero_dte_lane_scores_same_day_expiry():
    q = synthetic_quotes(iv=0.20, expiries=("2026-11-04",), strikes=np.arange(95, 105.5, 0.5))
    c = build_chain("SPY", ASOF, q, snapshot_id=None, spot=100.0, source="TEST",
                    min_dte=0, max_dte=1)
    res = run_scan([c], {"SPY": history(0.10)}, zero_dte_config(), asof=ASOF)
    assert res.structures_scored > 0
    assert all(p.expiration == "2026-11-04" for p in res.passed)


# --------------------------------------------------------------------- ledger
def test_scan_is_recorded_picks_frozen_once_per_session_and_settled(db_path):
    conn = get_connection(db_path)
    res = run_scan([chain(iv=0.25)], {"TEST": history(0.15)}, main_config(), asof=ASOF)
    record_scan(conn, res, completed_at=ASOF)
    record_scan(conn, res, completed_at=ASOF)  # same session: no duplicate picks
    picks = picks_with_outcomes(conn)
    assert len(picks) == len(res.picks) == 5
    scan = latest_scan(conn, LANE_MAIN)
    assert scan["passed"][0]["structure_key"] == res.passed[0].structure_key

    with pytest.raises(sqlite3.DatabaseError):
        with conn:
            conn.execute("UPDATE engine_picks SET conservative_ev_usd=999")

    first = res.picks[0]
    with conn:
        conn.execute(
            "INSERT INTO engine_daily_closes VALUES (?,?,?,'THETADATA_EOD',?)",
            ("TEST", first.expiration, 100.0, "2026-12-20T00:00:00Z"),
        )
    after = datetime(2026, 12, 20, 15, 0, tzinfo=UTC)
    assert settle_due_picks(conn, now=after) >= 1
    settled = [p for p in picks_with_outcomes(conn) if p["pnl_usd"] is not None]
    target = next(p for p in settled if p["structure_key"] == first.structure_key)
    assert target["pnl_usd"] == pytest.approx(pick_pnl_at(target["record"], 100.0), abs=0.01)
    card = scorecard(picks_with_outcomes(conn))
    assert card.settled == len(settled) and card.open == card.picks - card.settled
    conn.close()


def test_settlement_waits_for_the_close_on_expiry_day(db_path):
    conn = get_connection(db_path)
    res = run_scan([chain(iv=0.25)], {"TEST": history(0.15)}, main_config(), asof=ASOF)
    record_scan(conn, res, completed_at=ASOF)
    exp = res.picks[0].expiration
    with conn:
        conn.execute("INSERT INTO engine_daily_closes VALUES ('TEST',?,101.0,'THETADATA_EOD','x')",
                     (exp,))
    noon = datetime.combine(date.fromisoformat(exp), datetime.min.time(), NY).replace(hour=12)
    assert settle_due_picks(conn, now=noon) == 0
    conn.close()


# -------------------------------------------------------------------- history
def test_parse_eod_rows_keys_by_session_date_and_skips_garbage():
    rows = parse_eod_rows({"response": [
        {"close": 101.5, "created": "2026-11-02T17:15:03.123"},
        {"close": "bad", "created": "2026-11-03T17:15:00"},
        {"close": 0, "created": "2026-11-04T17:15:00"},
        {"close": 99.0, "created": "2026-10-30T17:15:00"},
    ]})
    assert [(r.session_date, r.close) for r in rows] == [("2026-10-30", 99.0),
                                                        ("2026-11-02", 101.5)]


def test_last_completed_session_respects_eod_report_time():
    morning = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)   # 10:00 NY Wednesday
    evening = datetime(2026, 11, 4, 23, 0, tzinfo=UTC)   # 18:00 NY Wednesday
    monday = datetime(2026, 11, 2, 14, 0, tzinfo=UTC)
    assert last_completed_session(morning) == date(2026, 11, 3)
    assert last_completed_session(evening) == date(2026, 11, 4)
    assert last_completed_session(monday) == date(2026, 10, 30)


# --------------------------------------------------------------------- worker
class FakeTheta:
    base_url = "fake"

    def __init__(self, closes):
        self.closes = closes
        self.calls = []

    def _get_payload(self, path, params):
        self.calls.append((path, dict(params)))
        if path == "/stock/history/eod":
            start = datetime.strptime(params["start_date"], "%Y%m%d").date()
            end = datetime.strptime(params["end_date"], "%Y%m%d").date()
            rows, day, i = [], start, 0
            while day <= end:
                if day.weekday() < 5:
                    rows.append({"close": self.closes[i % len(self.closes)],
                                 "created": f"{day.isoformat()}T17:15:00"})
                    i += 1
                day += timedelta(days=1)
            return {"response": rows}
        if path == "/option/snapshot/quote":
            return {"response": []}
        raise AssertionError(path)


def seed_snapshot(db_path, underlying="TEST", captured=ASOF, iv=0.25):
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
                           'UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN',?,'FETCHED')""",
                (sid, q.right, q.strike, q.expiration, naive_ny, q.bid, q.ask, 500),
            )
    conn.close()
    return sid


def test_worker_step_end_to_end_records_scan_and_picks(db_path):
    from src.engine.worker import run_engine_step

    seed_snapshot(db_path)
    fake = FakeTheta(history(0.15, n=600))
    summary = run_engine_step(theta_client=fake, db_path=db_path,
                              now=ASOF + timedelta(minutes=5))
    assert summary.errors == [] or all("0dte" in e for e in summary.errors), summary.errors
    assert summary.main_scan_id is not None and summary.main_passed > 0
    assert summary.closes.get("TEST", "").startswith("FETCHED")
    conn = get_connection(db_path)
    assert len(picks_with_outcomes(conn, LANE_MAIN)) == 5
    conn.close()


def test_worker_isolates_provider_failures(db_path):
    from src.engine.worker import run_engine_step

    class Broken:
        base_url = "broken"

        def _get_payload(self, path, params):
            raise OSError("terminal down")

    seed_snapshot(db_path)
    summary = run_engine_step(theta_client=Broken(), db_path=db_path,
                              now=ASOF + timedelta(minutes=5))
    assert summary.closes["TEST"].startswith("FAILED")
    # No history -> MAIN scan still recorded, nothing passes.
    assert summary.main_scan_id is not None and summary.main_passed == 0
