"""Backtest harness: warm-up, same pipeline over EOD chains, cached, slots, settled, judged."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from src.engine.backtest import (
    BacktestSettings, evaluate_criteria, quotes_from_eod_rows, run_backtest, single_slot_path,
    write_report,
)
from src.engine.chains import black76_price
from src.engine.pipeline import main_config


class FakeEodTheta:
    """Deterministic price path (14 % realised vol) with one -12 % day; Black-76 EOD
    chains at 22 % IV, so lambda is about 0.4 and premium is worth selling."""

    def __init__(self, start=date(2026, 1, 1), days=900, seed=3, jump_day=date(2026, 9, 2),
                 jump=0.88):
        rng = np.random.default_rng(seed)
        self.closes: dict[str, float] = {}
        px, day = 100.0, start - timedelta(days=days)
        while day <= start + timedelta(days=400):
            if day.weekday() < 5:
                move = rng.normal(0, 0.14 / math.sqrt(252))
                if day == jump_day:
                    move = math.log(jump)
                px *= math.exp(move)
                self.closes[day.isoformat()] = px
            day += timedelta(days=1)
        self.requests = 0

    def _fridays(self, session: date):
        d = session + timedelta(days=1)
        out = []
        while (d - session).days <= 50:
            if d.weekday() == 4:
                out.append(d)
            d += timedelta(days=1)
        return out

    def _get_payload(self, path, params):
        self.requests += 1
        if path == "/stock/history/eod":
            if params["symbol"] == "NOPE":
                raise OSError("no such symbol")
            start = datetime.strptime(params["start_date"], "%Y%m%d").date()
            end = datetime.strptime(params["end_date"], "%Y%m%d").date()
            rows = [{"close": c, "created": f"{d}T17:15:00", "last_trade": f"{d}T16:00:00"}
                    for d, c in self.closes.items() if start.isoformat() <= d <= end.isoformat()]
            return {"response": rows}
        if path == "/option/history/eod":
            session = datetime.strptime(params["start_date"], "%Y%m%d").date()
            spot = self.closes.get(session.isoformat())
            if spot is None:
                return {"response": []}
            rows = []
            for exp in self._fridays(session):
                t = (exp - session).days / 365.0
                f = spot * math.exp(0.04 * t)
                for k in np.arange(round(spot * 0.75), round(spot * 1.25) + 1, 1.0):
                    for right in ("CALL", "PUT"):
                        p = black76_price(right[0], f, float(k), t, 0.22)
                        if p < 0.03:
                            continue
                        spread = max(0.02, 0.04 * p)
                        rows.append({"contract": {"symbol": params["symbol"], "expiration": exp.isoformat(),
                                                  "strike": float(k), "right": right},
                                     "data": [{"bid": round(p - spread / 2, 2), "ask": round(p + spread / 2, 2),
                                               "created": f"{session}T17:15:00"}]})
            return {"response": rows}
        raise AssertionError(path)


def settings_for(tmp_path, **kw) -> BacktestSettings:
    base = dict(stock_pace_seconds=0.0, symbols=("SPY",), start=date(2026, 8, 3), end=date(2026, 9, 18),
                cache_dir=tmp_path / "cache", config=main_config(), oos_start=date(2026, 9, 1))
    return BacktestSettings(**{**base, **kw})


def test_quotes_from_eod_rows_normalises_rights_dates_and_timestamps():
    rows = [{"right": "CALL", "strike": "100", "expiration": "20261218", "bid": 1.0, "ask": 1.1},
            {"right": "P", "strike": 95.0, "expiration": "2026-12-18", "bid": "", "ask": 0.5},
            {"right": "X", "strike": 95.0, "expiration": "2026-12-18", "bid": 1, "ask": 2}]
    quotes = quotes_from_eod_rows(rows, date(2026, 11, 4))
    assert [(q.right, q.expiration, q.bid) for q in quotes] == [("C", "2026-12-18", 1.0), ("P", "2026-12-18", None)]
    assert quotes[0].quote_at == "2026-11-04T21:00:00Z"


def test_backtest_warms_up_scores_one_open_pick_per_name_settles_caches_and_summarises(tmp_path):
    fake = FakeEodTheta()
    settings = settings_for(tmp_path, symbols=("SPY", "NOPE"))
    messages = []
    report = run_backtest(fake, settings, progress=messages.append)
    assert report.sessions == 34 and any("NOPE" in m for m in messages)
    cov = report.summary["coverage"]
    assert cov["warmup_sessions_requested"] > 250 and cov["iv_points"]["SPY"] > 250
    assert report.picks and all(p["underlying"] == "SPY" for p in report.picks)
    assert all(p["entry_cash_usd"] > 0 and p["premium_ratio"] is not None for p in report.picks)
    assert all(0.2 < p["premium_ratio"] < 0.7 for p in report.picks)
    # One open pick per name at a time: each pick is entered after the previous one expired.
    ordered = sorted(report.picks, key=lambda p: p["session"])
    for a, b in zip(ordered, ordered[1:]):
        assert b["session"] > a["expiration"]
    s = report.summary
    assert s["settled"] > 0 and s["open"] >= 0 and s["expiry_days"] > 0
    assert set(s["by_family"]) <= {"CREDIT_SPREAD", "IRON_CONDOR", "IRON_FLY"}
    assert s["assumptions"]["commission_per_contract"] == 2.0 and s["assumptions"]["oos_start"] == "2026-09-01"
    # The -12 % day on 2026-09-02 hits every short-put pick open across it.
    hit = [p for p in report.picks if p["pnl_usd"] is not None and p["shape"] != "CALL_CREDIT_SPREAD"
           and p["session"] < "2026-09-02" <= p["expiration"]]
    assert hit and sum(p["pnl_usd"] for p in hit) < 0
    assert s["worst_day_usd"] < 0 and s["max_drawdown_usd"] < 0
    assert s["criteria"]["verdict"] == "INSUFFICIENT"          # 34 sessions is not 60 expiry days
    assert set(s["single_slot"]) == {"all", "out_of_sample"}
    paths = write_report(report, tmp_path / "out")
    assert all(p.exists() for p in paths.values())
    summary = json.loads(paths["summary"].read_text())
    assert summary["picks"] == len(report.picks) and summary["settings"]["symbols"] == ["SPY", "NOPE"]
    assert summary["settings"]["oos_start"] == "2026-09-01"
    premium_rows = paths["premium"].read_text().splitlines()
    assert premium_rows[0] == "session,underlying,iv30,ratio,observations" and len(premium_rows) > 30
    # Second run: everything served from the cache except the symbol that failed
    # (a failure is never cached, it may have been transient).
    before = fake.requests
    again = run_backtest(fake, settings)
    assert fake.requests == before + 1 and again.summary["total_pnl_usd"] == s["total_pnl_usd"]


def test_half_written_cache_entries_are_refetched_not_trusted(tmp_path):
    from src.engine.backtest import CachedSource

    fake = FakeEodTheta()
    source = CachedSource(fake, tmp_path / "cache", pace_seconds=0.0)
    rows = source.chain_rows("SPY", date(2026, 8, 3))
    path = tmp_path / "cache" / "option_eod" / "SPY" / "2026-08-03.json"
    assert rows and path.exists() and not list(path.parent.glob("*.tmp"))
    path.write_text(path.read_text()[:40], encoding="utf-8")          # a run died mid-write
    before = fake.requests
    assert source.chain_rows("SPY", date(2026, 8, 3)) == rows and fake.requests == before + 1
    assert source.chain_rows("SPY", date(2026, 8, 3)) == rows and fake.requests == before + 1


def test_backtest_rejects_an_empty_range(tmp_path):
    with pytest.raises(ValueError):
        run_backtest(FakeEodTheta(), settings_for(tmp_path, start=date(2026, 8, 1), end=date(2026, 8, 2)))


def test_backtest_stops_on_a_dead_terminal_and_reports_coverage(tmp_path, monkeypatch):
    """A logged-out terminal must abort the run, not race through thousands of empty sessions."""
    from src.engine import backtest as bt
    from src.providers.thetadata import ThetaDataResponseError

    monkeypatch.setattr(bt.clock, "sleep", lambda s: None)
    base = FakeEodTheta()
    state = {"chains": 0}

    class Dying(FakeEodTheta):
        def _get_payload(self, path, params):
            if path == "/option/history/eod":
                state["chains"] += 1
                if state["chains"] > 6:
                    raise ThetaDataResponseError("ThetaData HTTP 478: invalid session")
            return base._get_payload(path, params)

    messages = []
    report = run_backtest(Dying(), settings_for(tmp_path), progress=messages.append)
    cov = report.summary["coverage"]
    assert cov["aborted_reason"] and "478" in cov["aborted_reason"]
    assert cov["warmup_sessions_with_chains"] == 6 and cov["sessions_with_chains"] == 0
    assert any(m.startswith("ABORTED") for m in messages)
    assert state["chains"] == 6 + 4           # three waits + the final attempt, then stop
    assert report.picks == []
    # The six cached sessions survive for the rerun.
    assert len(list((tmp_path / "cache" / "option_eod" / "SPY").glob("*.json"))) == 6


def test_backtest_tolerates_missing_warmup_sessions_but_not_a_run_of_scoring_failures(tmp_path, monkeypatch):
    from src.engine import backtest as bt
    from src.providers.thetadata import ThetaDataResponseError

    monkeypatch.setattr(bt.clock, "sleep", lambda s: None)
    base = FakeEodTheta()

    class OldTierGap(FakeEodTheta):
        """The subscription does not serve sessions before 2025-10-01 (warm-up only)."""

        def _get_payload(self, path, params):
            if path == "/option/history/eod" and params["start_date"] < "20251001":
                raise ThetaDataResponseError("ThetaData HTTP 472: no data for the requested date")
            return base._get_payload(path, params)

    report = run_backtest(OldTierGap(), settings_for(tmp_path))
    cov = report.summary["coverage"]
    assert cov["aborted_reason"] is None and cov["chain_failures"] > 50
    assert cov["warmup_sessions_with_chains"] < cov["warmup_sessions_requested"]

    class Broken(FakeEodTheta):
        def _get_payload(self, path, params):
            if path == "/option/history/eod" and params["start_date"] >= "20260803":
                raise ThetaDataResponseError("ThetaData HTTP 500: boom")
            return base._get_payload(path, params)

    report = run_backtest(Broken(), settings_for(tmp_path / "b"))
    assert report.summary["coverage"]["aborted_reason"] and "in a row" in report.summary["coverage"]["aborted_reason"]


def _pick(session, expiration, pnl, score=0.1, max_loss=400.0, pop=0.7, pml=0.1, underlying="SPY"):
    return {"session": session, "expiration": expiration, "pnl_usd": pnl, "score": score,
            "ev_usd": 20.0, "max_loss_usd": max_loss, "pop": pop, "p_max_loss": pml,
            "family": "CREDIT_SPREAD", "underlying": underlying}


def test_pre_registered_criteria_are_mechanical():
    from src.engine.backtest import _block

    rng = np.random.default_rng(5)
    days = [f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(70)]
    good = [_pick("2025-01-01", d, float(rng.choice([60.0, -400.0], p=[0.9, 0.1])), pop=0.9, pml=0.1)
            for d in days for _ in range(4)]
    # calibrate the synthetic predictions to the sample so the gaps are small
    hit = np.mean([p["pnl_usd"] > 0 for p in good])
    for p in good:
        p["pop"], p["p_max_loss"] = hit, 1 - hit
    crit = evaluate_criteria(_block(good))
    assert crit["verdict"] == "PASS", crit
    assert crit["checks"]["ci_lower_bound_above_zero"]["pass"] and crit["checks"]["expiry_days"]["value"] == 70

    bad = [_pick("2025-01-01", d, float(rng.choice([60.0, -400.0], p=[0.6, 0.4])), pop=0.9, pml=0.1)
           for d in days for _ in range(4)]
    crit = evaluate_criteria(_block(bad))
    assert crit["verdict"] == "FAIL"
    assert not crit["checks"]["ci_lower_bound_above_zero"]["pass"]
    assert not crit["checks"]["hit_rate_gap"]["pass"] and not crit["checks"]["full_loss_rate_excess"]["pass"]

    thin = evaluate_criteria(_block(good[:40]))
    assert thin["verdict"] == "INSUFFICIENT"
    assert evaluate_criteria(_block([]))["verdict"] == "INSUFFICIENT"
    assert "Pre-registered" in crit["statement"]


def test_single_slot_path_holds_one_position_at_a_time_and_takes_the_best_score():
    picks = [
        _pick("2025-01-02", "2025-01-17", 50.0, score=0.10, underlying="SPY"),
        _pick("2025-01-02", "2025-01-10", 30.0, score=0.20, underlying="QQQ"),   # best score that day
        _pick("2025-01-06", "2025-01-24", 40.0, score=0.30),                      # slot busy until 01-10
        _pick("2025-01-10", "2025-01-31", -400.0, score=0.30),                    # still busy on the expiry day
        _pick("2025-01-13", "2025-01-31", 25.0, score=0.05),                      # slot free
        _pick("2025-02-03", "2025-02-21", None, score=0.9),                       # unsettled: ignored
    ]
    path = single_slot_path(picks)
    assert [(p["session"], p["underlying"]) for p in path] == [("2025-01-02", "QQQ"), ("2025-01-13", "SPY")]
