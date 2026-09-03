from pathlib import Path

from src.database.repository import get_connection


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "018_evidence_integrity_instrumentation.sql"


def test_migration_018_adds_timing_columns_and_reference_gap_views(db_path):
    conn = get_connection(db_path)
    try:
        version = conn.execute(
            "SELECT MAX(version) AS version FROM schema_version;"
        ).fetchone()["version"]
        assert version == 23

        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(provider_model_observations);"
            ).fetchall()
        }
        assert {
            "timing_diagnostic_version",
            "greek_age_seconds",
            "quote_greek_skew_seconds",
            "underlying_greek_skew_seconds",
        }.issubset(columns)

        views = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view';"
            ).fetchall()
        }
        assert "v_unmatched_provider_gap_by_run" in views
        assert "v_unmatched_provider_identity_recurrence" in views
    finally:
        conn.close()


def test_reference_gap_views_classify_integer_and_half_increment_strikes(db_path):
    conn = get_connection(db_path)
    try:
        run_id = int(conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id, started_at, code_git_sha, preregistration_hash,
                us_session_date, us_session_state, status
            ) VALUES ('V18_VIEW_TEST', '2026-09-03T18:00:00Z', 'sha', 'hash',
                      '2026-09-03', 'INTRADAY', 'STARTED');
            """
        ).lastrowid)

        base = (
            run_id, "THETADATA", "THETADATA_QUOTE", "THETA_QUOTE_ONLY",
            "AAPL", "2026-09-11", "C", "THETADATA_IDENTITY_NOT_IN_REFERENCE_FRAME",
            "2026-09-03T18:00:05Z", "2026-09-03T14:00:02", "2026-09-03T18:00:05Z",
        )
        for strike in (257.0, 257.5):
            conn.execute(
                """
                INSERT INTO unmatched_provider_contract_observations (
                    research_run_id, provider, evidence_family, anomaly_type,
                    underlying, expiration, strike, right, reason_code,
                    observed_at, raw_timestamp, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                base[:6] + (strike,) + base[6:],
            )
        conn.commit()

        row = conn.execute(
            """
            SELECT * FROM v_unmatched_provider_gap_by_run
            WHERE research_run_id = ? AND underlying = 'AAPL';
            """,
            (run_id,),
        ).fetchone()
        assert row["observation_count"] == 2
        assert row["integer_strike_count"] == 1
        assert row["half_increment_strike_count"] == 1
        assert row["other_fractional_strike_count"] == 0
    finally:
        conn.close()


def test_migration_018_rehearses_from_exact_v17_shape(tmp_path):
    import sqlite3

    db = tmp_path / "migration_018_from_v17.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_version VALUES (17, '2026-09-03T00:00:00Z');

            CREATE TABLE provider_model_observations (
                id INTEGER PRIMARY KEY,
                option_quote_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                observed_at TEXT,
                source TEXT NOT NULL DEFAULT 'PROVIDER_DERIVED',
                model_name TEXT,
                provider_request_id TEXT,
                implied_volatility REAL,
                delta REAL,
                gamma REAL,
                theta REAL,
                vega REAL,
                model_underlying_price REAL,
                model_rate REAL,
                model_dividend_yield REAL,
                model_input_notes TEXT
            );

            CREATE TABLE unmatched_provider_contract_observations (
                id INTEGER PRIMARY KEY,
                research_run_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                evidence_family TEXT NOT NULL,
                anomaly_type TEXT NOT NULL,
                underlying TEXT NOT NULL,
                provider_contract_id TEXT,
                expiration TEXT,
                strike REAL,
                right TEXT,
                reason_code TEXT,
                observed_at TEXT NOT NULL,
                raw_timestamp TEXT,
                raw_payload_json TEXT,
                ingested_at TEXT NOT NULL
            );
            """
        )
        conn.executescript(MIGRATION.read_text(encoding="utf-8"))

        version = conn.execute(
            "SELECT MAX(version) FROM schema_version;"
        ).fetchone()[0]
        assert version == 18

        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(provider_model_observations);"
            ).fetchall()
        }
        assert "greek_age_seconds" in columns
        assert "quote_greek_skew_seconds" in columns
        assert "underlying_greek_skew_seconds" in columns

        assert conn.execute("PRAGMA integrity_check;").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        conn.close()
