"""Casino research candidates must use genuine same-snapshot, same-day quotes."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from src.research.massive_underlying_observation_v1 import STOCK_PRICE_SOURCE
from src.research.casino_0dte_watchlist_v1 import load_casino_0dte_watchlist


def _db(path, *, trustworthy=True, multiplier=100, quote_multiplier=None):
    conn = sqlite3.connect(path)
    try:
        conn.executescript("""
            CREATE TABLE market_snapshots (
                id INTEGER PRIMARY KEY, research_run_id INTEGER,
                underlying TEXT, us_session_date TEXT, captured_at TEXT,
                underlying_at TEXT, underlying_price REAL,
                underlying_source TEXT, notes TEXT
            );
            CREATE TABLE option_quotes (
                id INTEGER PRIMARY KEY, snapshot_id INTEGER, expiration TEXT,
                right TEXT, strike REAL, bid REAL, ask REAL,
                quote_at TEXT, shares_per_contract REAL
            );
            CREATE TABLE listing_reference_contracts (
                research_run_id INTEGER,provider TEXT,underlying TEXT,
                expiration TEXT,right TEXT,strike REAL,shares_per_contract REAL
            );
            CREATE TABLE fx_observations (
                id INTEGER PRIMARY KEY,base_currency TEXT,quote_currency TEXT,
                observed_at TEXT, rate REAL,provider TEXT,provenance TEXT
            );
        """)
        conn.execute("""
            INSERT INTO market_snapshots VALUES
            (1,10,'SPY','2026-10-19','2026-10-19T14:59:55Z',
             '2026-10-19T14:59:50Z',600.0,?,?)
        """, ("FETCHED" if trustworthy else "MODEL",
              f"stock price source={STOCK_PRICE_SOURCE}; sampled=yes"))
        conn.execute("""
            INSERT INTO option_quotes VALUES
            (20,1,'2026-10-19','C',612,0.13,0.15,
             '2026-10-19T10:59:51',?)
        """, (quote_multiplier,))
        if multiplier is not None:
            conn.execute("""
                INSERT INTO listing_reference_contracts VALUES
                (10,'MASSIVE','SPY','2026-10-19','C',612,?)
            """, (multiplier,))
        conn.execute("""
            INSERT INTO fx_observations VALUES
            (1,'EUR','USD','2026-10-19T14:00:00Z',1.10,'MASSIVE','observed')
        """)
        conn.commit()
    finally:
        conn.close()


def test_source_qualified_watchlist_is_only_scenario_not_trade(tmp_path):
    db = tmp_path / "casino.db"
    _db(db)
    now = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
    found = load_casino_0dte_watchlist(db, now=now)
    assert len(found) == 1
    candidate = found[0]
    assert candidate.option_quote_id == 20
    assert candidate.snapshot_id == 1
    assert candidate.multiplier == 100
    assert candidate.indicative_max_loss_eur <= 25
    assert candidate.hypothetical_return_multiple > 0
    assert "NO_PREDICTIVE_EDGE" in candidate.evidence_state
    assert found[0].display_row()["Quote ID"] == 20
    assert load_casino_0dte_watchlist(db, now=now + timedelta(minutes=11)) == ()


def test_watchlist_fails_closed_on_non_independent_spot(tmp_path):
    db = tmp_path / "model.db"
    _db(db, trustworthy=False)
    assert not load_casino_0dte_watchlist(
        db, now=datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
    )


def test_watchlist_fails_closed_without_verified_multiplier(tmp_path):
    db = tmp_path / "missing.db"
    _db(db, multiplier=None)
    assert not load_casino_0dte_watchlist(
        db, now=datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
    )


def test_watchlist_rejects_conflicting_multiplier_and_future_day(tmp_path):
    db = tmp_path / "conflict.db"
    _db(db, multiplier=100, quote_multiplier=50)
    assert not load_casino_0dte_watchlist(
        db, now=datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
    )
    assert not load_casino_0dte_watchlist(
        db, now=datetime(2026, 10, 18, 15, 0, tzinfo=UTC)
    )

def test_watchlist_requires_source_fx_and_regular_session(tmp_path):
    db = tmp_path / "no_fx.db"
    _db(db)
    conn = sqlite3.connect(db)
    try:
        conn.execute("DELETE FROM fx_observations")
        conn.commit()
    finally:
        conn.close()
    now = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
    assert load_casino_0dte_watchlist(db, now=now) == ()
    assert load_casino_0dte_watchlist(
        db, now=datetime(2026, 10, 19, 20, 2, tzinfo=UTC)
    ) == ()
