from __future__ import annotations

import math
import random
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from src.decision.quote_noise import (
    _estimate,
    prior_iv_variation_for_leg,
    MIN_PAIRS,
)


def test_prior_quote_proxy_needs_distinct_timestamps_and_six_pairs():
    start = datetime(2026, 10, 16, 13, tzinfo=UTC)
    short = [(start + timedelta(minutes=i * 15), 0.25 + 0.001*i, 100.0)
             for i in range(11)]
    assert _estimate(short, asof=start + timedelta(hours=8)) is None
    longer = short + [(start + timedelta(minutes=165), 0.275, 100.0)]
    estimate = _estimate(longer, asof=start + timedelta(hours=8))
    assert estimate is not None
    assert estimate[1] == MIN_PAIRS
    assert estimate[0] > 0


def test_realized_quote_instability_proxy_is_conservative_in_gaussian_fixture():
    rng = random.Random(20261018)
    true_sigma = 0.012
    start = datetime(2026, 10, 16, 13, tzinfo=UTC)
    rows = [(start + timedelta(minutes=i * 15),
             0.25 + rng.gauss(0, true_sigma), 100.0)
            for i in range(24)]
    estimated = _estimate(rows, asof=start + timedelta(hours=7))
    assert estimated is not None
    assert estimated[1] == 12
    assert estimated[0] >= 0.7 * true_sigma


def test_asof_sql_ignores_future_quotes_and_stale_timestamp_replays():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript("""
            CREATE TABLE market_snapshots(
                id INTEGER PRIMARY KEY, captured_at TEXT,
                us_session_date TEXT, underlying_price REAL
            );
            CREATE TABLE option_quotes(
                id INTEGER PRIMARY KEY, snapshot_id INTEGER, option_symbol TEXT,
                expiration TEXT, right TEXT, strike REAL, quote_at TEXT,
                bid REAL, ask REAL
            );
            CREATE TABLE provider_model_observations(
                id INTEGER PRIMARY KEY, option_quote_id INTEGER,
                provider TEXT, implied_volatility REAL
            );
            CREATE INDEX idx_option_quotes_symbol ON option_quotes(option_symbol);
        """)
        start = datetime(2026, 10, 16, 13, tzinfo=UTC)
        rng = random.Random(13)
        for i in range(16):
            t = start + timedelta(minutes=15 * i)
            iso = t.isoformat()
            db.execute("INSERT INTO market_snapshots VALUES(?,?,?,?)",
                       (i + 1, iso, "2026-10-16", 100.0))
            db.execute("INSERT INTO option_quotes VALUES(?,?,?,?,?,?,?,?,?)",
                       (i + 1, i + 1, "SPY261218C00100000",
                        "2026-12-18", "C", 100, iso, 2.0, 2.10))
            db.execute("INSERT INTO provider_model_observations VALUES(?,?,?,?)",
                       (i + 1, i + 1, "THETADATA", 0.25 + rng.gauss(0, 0.01)))
        before = prior_iv_variation_for_leg(db, 16)
        assert before is not None and before[1] >= 6

        later = (start + timedelta(hours=6)).isoformat()
        db.execute("INSERT INTO market_snapshots VALUES(17,?,?,?)",
                   (later, "2026-10-16", 100.0))
        db.execute("INSERT INTO option_quotes VALUES(17,17,?,?,?,?,?,?,?)",
                   ("SPY261218C00100000", "2026-12-18", "C", 100, later, 2.0, 2.10))
        db.execute("INSERT INTO provider_model_observations VALUES(17,17,'THETADATA',0.90)")
        # The persisted decision is always pinned to quote 16's snapshot.
        after = prior_iv_variation_for_leg(db, 16)
        assert before == after
        db.execute("UPDATE option_quotes SET quote_at=? WHERE id BETWEEN 1 AND 15",
                   (start.isoformat(),))
        assert prior_iv_variation_for_leg(db, 16) is None
    finally:
        db.close()
