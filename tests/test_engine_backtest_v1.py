"""Backtest harness: same pipeline over EOD chains, cached, settled, summarised."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from src.engine.backtest import BacktestSettings, quotes_from_eod_rows, run_backtest, write_report
from src.engine.chains import black76_price
from src.engine.pipeline import main_config


class FakeEodTheta:
    """Deterministic price path with one -8 % day; Black-76 EOD chains at 22 % IV."""

    def __init__(self, start=date(2026, 1, 1), days=900, seed=3, jump_day=date(2026, 9, 10)):
        rng = np.random.default_rng(seed)
        self.closes: dict[str, float] = {}
        px, day = 100.0, start - timedelta(days=days)
        while day <= start + timedelta(days=400):
            if day.weekday() < 5:
                move = rng.normal(0, 0.14 / math.sqrt(252))
                if day == jump_day:
                    move = math.log(0.92)
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


def test_quotes_from_eod_rows_normalises_rights_dates_and_timestamps():
    rows = [{"right": "CALL", "strike": "100", "expiration": "20261218", "bid": 1.0, "ask": 1.1},
            {"right": "P", "strike": 95.0, "expiration": "2026-12-18", "bid": "", "ask": 0.5},
            {"right": "X", "strike": 95.0, "expiration": "2026-12-18", "bid": 1, "ask": 2}]
    quotes = quotes_from_eod_rows(rows, date(2026, 11, 4))
    assert [(q.right, q.expiration, q.bid) for q in quotes] == [("C", "2026-12-18", 1.0), ("P", "2026-12-18", None)]
    assert quotes[0].quote_at == "2026-11-04T21:00:00Z"


def test_backtest_runs_settles_caches_and_summarises(tmp_path):
    fake = FakeEodTheta()
    settings = BacktestSettings(stock_pace_seconds=0.0, symbols=("SPY", "NOPE"), start=date(2026, 8, 3), end=date(2026, 9, 18),
                                cache_dir=tmp_path / "cache", config=main_config())
    messages = []
    report = run_backtest(fake, settings, progress=messages.append)
    assert report.sessions == 34 and any("NOPE" in m for m in messages)
    assert report.picks and all(p["underlying"] == "SPY" for p in report.picks)
    assert len({p["session"] for p in report.picks}) == len(report.picks)   # one per underlying per session
    s = report.summary
    assert s["settled"] > 0 and s["open"] >= 0 and s["expiry_days"] > 0
    assert set(s["by_family"]) and s["assumptions"]["commission_per_contract"] == 2.0
    # The -8 % day on 2026-09-10 hits every short-vol pick expiring after it.
    hit = [p for p in report.picks if p["pnl_usd"] is not None
           and p["session"] < "2026-09-10" <= p["expiration"]]
    assert hit and sum(p["pnl_usd"] for p in hit) < 0
    assert s["worst_day_usd"] < 0 and s["max_drawdown_usd"] < 0
    paths = write_report(report, tmp_path / "out")
    assert all(p.exists() for p in paths.values())
    summary = json.loads(paths["summary"].read_text())
    assert summary["picks"] == len(report.picks) and summary["settings"]["symbols"] == ["SPY", "NOPE"]
    # Second run: everything served from the cache except the symbol that failed
    # (a failure is never cached, it may have been transient).
    before = fake.requests
    again = run_backtest(fake, settings)
    assert fake.requests == before + 1 and again.summary["total_pnl_usd"] == s["total_pnl_usd"]


def test_backtest_rejects_an_empty_range(tmp_path):
    with pytest.raises(ValueError):
        run_backtest(FakeEodTheta(), BacktestSettings(stock_pace_seconds=0.0, symbols=("SPY",), start=date(2026, 8, 1),
                                                      end=date(2026, 8, 2), cache_dir=tmp_path))
