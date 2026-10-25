"""Read-only database adapter works independently of shadow butterfly proposals."""
import sqlite3
import pytest

from src.research.independent_family_read_model_v1 import inspect_latest_run
from src.research.massive_underlying_observation_v1 import STOCK_PRICE_SOURCE


def seed(db):
    conn = sqlite3.connect(db)
    conn.executescript("""
      CREATE TABLE research_runs (id INTEGER PRIMARY KEY, status TEXT);
      CREATE TABLE market_snapshots (
          id INTEGER PRIMARY KEY, research_run_id INTEGER, provider TEXT,
          underlying TEXT, captured_at TEXT, underlying_price REAL,
          underlying_source TEXT, underlying_at TEXT, notes TEXT
      );
      CREATE TABLE option_quotes (
          id INTEGER PRIMARY KEY, snapshot_id INTEGER, right TEXT,
          strike REAL, expiration TEXT, quote_at TEXT, bid REAL, ask REAL,
          shares_per_contract REAL
      );
      CREATE TABLE listing_reference_contracts (
          id INTEGER PRIMARY KEY, research_run_id INTEGER, provider TEXT,
          underlying TEXT, expiration TEXT, right TEXT, strike REAL,
          shares_per_contract REAL
      );
      CREATE TABLE fx_observations (
          id INTEGER PRIMARY KEY,base_currency TEXT,quote_currency TEXT,
          rate REAL,observed_at TEXT,provider TEXT,provenance TEXT
      );
      CREATE TABLE unified_capture_dispositions_v1 (
          id INTEGER PRIMARY KEY, research_run_id INTEGER,snapshot_id INTEGER,
          state TEXT,decisions_frozen INTEGER
      );
      INSERT INTO research_runs VALUES (11,'COMPLETED');
      INSERT INTO fx_observations VALUES
       (1,'EUR','USD',1.15,'2026-10-19T14:59:50Z','TEST','TEST_ASOF');
    """)
    conn.execute(
        """INSERT INTO market_snapshots
        VALUES (88,11,'THETADATA','XYZ','2026-10-19T15:00:00Z',
                100,'FETCHED','2026-10-19T14:59:56Z',?)""",
        (f"stock price source={STOCK_PRICE_SOURCE}; test-independent",),
    )
    for r in ("C", "P"):
        for strike in (90, 95, 100, 105, 110):
            conn.execute(
                """INSERT INTO option_quotes
                 (snapshot_id,right,strike,expiration,quote_at,bid,ask,
                 shares_per_contract) VALUES (88,?,?,'2026-10-23',
                 '2026-10-19T14:59:55Z',1,1.1,100)""",
                (r, strike),
            )
            conn.execute(
                """INSERT INTO listing_reference_contracts
                 (research_run_id,provider,underlying,expiration,right,strike,
                  shares_per_contract) VALUES
                 (11,'MASSIVE','XYZ','2026-10-23',?,?,100)""",
                (r, strike),
            )
    conn.commit()
    conn.close()


def test_latest_run_uses_all_families_without_butterfly_proposals(tmp_path):
    path = tmp_path / "db.sqlite"
    seed(path)
    before = path.stat().st_size
    result = inspect_latest_run(db_path=path)
    assert result.research_run_id == 11
    assert result.snapshots_seen == 1
    assert result.snapshots_with_independent_spot == 1
    assert result.families_constructed == 7
    assert result.live_trades_authorized == 0
    assert result.shadow_experiments_authorized == 0
    assert result.outcomes[0].strategy_ids == (
        "S03", "S04", "S06", "S07", "S08", "S09", "S10"
    )
    assert path.stat().st_size == before


def test_explicit_allocation_has_no_hardcoded_cap(tmp_path):
    path = tmp_path / "db.sqlite"
    seed(path)
    report = inspect_latest_run(db_path=path, allocated_eur="25000")
    assert report.families_constructed == 7
    assert report.live_trades_authorized == 0
    with pytest.raises(ValueError, match="ALLOCATION_MUST_BE_POSITIVE"):
        inspect_latest_run(db_path=path, allocated_eur="0")


def test_model_only_snapshot_reports_missing_price_without_quotes_scan(tmp_path):
    path = tmp_path / "db.sqlite"
    seed(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE market_snapshots SET underlying_source='UNKNOWN',notes='model only'"
    )
    conn.commit()
    conn.close()
    result = inspect_latest_run(db_path=path)
    assert result.families_constructed == 0
    assert result.snapshots_with_independent_spot == 0
    assert "INDEPENDENT_CONTEMPORANEOUS_STOCK_REFERENCE_MISSING" in (
        result.outcomes[0].blockers
    )


def test_snapshot_bounding_fails_not_silent_partial_sample(tmp_path):
    path = tmp_path / "db.sqlite"
    seed(path)
    conn = sqlite3.connect(path)
    conn.execute(
        """INSERT INTO market_snapshots
        (id,research_run_id,provider,underlying,captured_at,underlying_source)
        VALUES (89,11,'THETADATA','ABC','2026-10-19T15:00:00Z','UNKNOWN')"""
    )
    conn.commit()
    conn.close()
    try:
        inspect_latest_run(db_path=path, max_snapshots=1)
    except ValueError as exc:
        assert "EXCEEDS_BOUND" in str(exc)
    else:
        raise AssertionError("Bound silently truncated evidence")
