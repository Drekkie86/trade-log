from __future__ import annotations

import sqlite3

from src.research.casino_0dte_runtime_v1 import load_casino_0dte_runtime


def test_runtime_reports_no_zero_dte_evidence_without_same_day_expiry(tmp_path) -> None:
    path = tmp_path / "runtime.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE market_snapshots (id INTEGER PRIMARY KEY, us_session_date TEXT, underlying TEXT);"
        )
        conn.execute(
            """
            CREATE TABLE option_quotes (
                id INTEGER PRIMARY KEY,
                snapshot_id INTEGER,
                expiration TEXT,
                gamma REAL,
                theta REAL,
                bid REAL,
                ask REAL
            );
            """
        )
        conn.execute(
            "INSERT INTO market_snapshots (id, us_session_date, underlying) VALUES (1, '2026-09-13', 'SPY');"
        )
        conn.execute(
            "INSERT INTO option_quotes (snapshot_id, expiration, bid, ask) VALUES (1, '2026-09-14', 1.0, 1.1);"
        )
        conn.commit()
    finally:
        conn.close()

    result = load_casino_0dte_runtime(path)
    assert result.state == "ACCUMULATING_ZERO_DTE_EVIDENCE"
    assert result.zero_dte_quote_count == 0
    assert result.main_engine_authority == "UNCHANGED_BY_CASINO"
    assert result.casino_authority == "RESEARCH_SHADOW_ONLY_NO_EXECUTION"


def test_runtime_counts_same_session_expiration_evidence(tmp_path) -> None:
    path = tmp_path / "runtime.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE market_snapshots (id INTEGER PRIMARY KEY, us_session_date TEXT, underlying TEXT);"
        )
        conn.execute(
            """
            CREATE TABLE option_quotes (
                id INTEGER PRIMARY KEY,
                snapshot_id INTEGER,
                expiration TEXT,
                gamma REAL,
                theta REAL,
                bid REAL,
                ask REAL
            );
            """
        )
        conn.executemany(
            "INSERT INTO market_snapshots (id, us_session_date, underlying) VALUES (?, ?, ?);",
            [(1, "2026-09-13", "SPY"), (2, "2026-09-13", "QQQ")],
        )
        conn.executemany(
            """
            INSERT INTO option_quotes (snapshot_id, expiration, gamma, theta, bid, ask)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            [
                (1, "2026-09-13", 0.02, -0.4, 1.0, 1.1),
                (1, "2026-09-13", None, None, 0.5, 0.7),
                (2, "2026-09-13", 0.01, -0.2, 2.0, 2.2),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    result = load_casino_0dte_runtime(path)
    assert result.state == "ZERO_DTE_RESEARCH_EVIDENCE_AVAILABLE"
    assert result.zero_dte_session_count == 1
    assert result.zero_dte_snapshot_count == 2
    assert result.zero_dte_quote_count == 3
    assert result.zero_dte_underlying_count == 2
    assert result.greek_observation_count == 2
    assert result.spread_observation_count == 3
    assert result.dealer_positioning_state == "NOT_MEASURED_DO_NOT_INFER"
