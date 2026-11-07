import sqlite3
from pathlib import Path

from src.research.forecast_surface_runtime_v1 import load_forecast_surface_runtime


def _build_db(path: Path, *, session_days: int = 50) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE market_snapshots (
                id INTEGER PRIMARY KEY,
                captured_at TEXT NOT NULL,
                underlying TEXT NOT NULL,
                underlying_price REAL,
                us_session_date TEXT,
                us_session_state TEXT,
                research_run_id INTEGER
            );
            CREATE TABLE option_quotes (
                id INTEGER PRIMARY KEY,
                snapshot_id INTEGER NOT NULL,
                expiration TEXT NOT NULL,
                strike REAL NOT NULL,
                right TEXT NOT NULL
            );
            CREATE TABLE provider_model_observations (
                id INTEGER PRIMARY KEY,
                option_quote_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                implied_volatility REAL
            );
            """
        )
        for day in range(1, session_days + 1):
            session = f"2026-07-{day:02d}" if day <= 31 else f"2026-08-{day-31:02d}"
            conn.execute(
                "INSERT INTO market_snapshots(id,captured_at,underlying,underlying_price,us_session_date,us_session_state,research_run_id) VALUES(?,?,?,?,?,'POST_CLOSE',?);",
                (day, f"{session}T20:00:00Z", "SPY", 500.0 + day * 0.7, session, day),
            )
        snapshot_id = session_days
        quote_id = 1
        for strike, iv in [(480,0.26),(490,0.23),(500,0.21),(510,0.22),(520,0.25),(530,0.29)]:
            conn.execute(
                "INSERT INTO option_quotes(id,snapshot_id,expiration,strike,right) VALUES(?,?,?,?,?);",
                (quote_id, snapshot_id, "2026-10-16", strike, "C"),
            )
            conn.execute(
                "INSERT INTO provider_model_observations(id,option_quote_id,provider,implied_volatility) VALUES(?,?,?,?);",
                (quote_id, quote_id, "THETADATA", iv),
            )
            quote_id += 1
        conn.commit()
    finally:
        conn.close()


def test_runtime_reads_existing_database_without_mutation(tmp_path: Path) -> None:
    db = tmp_path / "trade_log.db"
    _build_db(db, session_days=50)

    before = db.read_bytes()
    result = load_forecast_surface_runtime(
        db,
        train_window=30,
        horizon_days=5,
        limit_underlyings=4,
        bootstrap_samples=20,
    )
    after = db.read_bytes()

    assert before == after
    assert result.decision_authority == "NONE_RESEARCH_ONLY"
    assert result.state == "RESEARCH_COMPARISONS_AVAILABLE"
    assert result.underlying_forecasts[0].state == "FORECAST_TOURNAMENT_AVAILABLE"
    assert result.underlying_forecasts[0].tournament is not None
    assert result.underlying_forecasts[0].tournament["comparable_model_count"] == 3
    assert result.surface.state == "SURFACE_TOURNAMENT_AVAILABLE"
    assert result.surface.tournament is not None


def test_runtime_reports_accumulating_history_instead_of_inventing_evidence(tmp_path: Path) -> None:
    db = tmp_path / "trade_log.db"
    _build_db(db, session_days=12)

    result = load_forecast_surface_runtime(
        db,
        train_window=30,
        horizon_days=5,
        bootstrap_samples=10,
    )

    assert result.state == "ACCUMULATING_EVIDENCE"
    assert result.underlying_forecasts[0].state == "ACCUMULATING_HISTORY"
    assert result.underlying_forecasts[0].tournament is None
    assert result.surface.state == "SURFACE_TOURNAMENT_AVAILABLE"
