import sqlite3

import pytest
from pathlib import Path

from src.database.repository import get_connection

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "019_local_surface_residual_v2_observational.sql"


def test_migration_019_adds_observational_surface_tables_and_view(db_path):
    conn = get_connection(db_path)
    try:
        assert conn.execute("SELECT MAX(version) FROM schema_version;").fetchone()[0] == 23
        objects = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view','index');")}
        assert {
            "local_surface_residual_v2_runs",
            "local_surface_residual_v2_observations",
            "v_local_surface_residual_v2_discovery_dataset",
            "idx_surface_v2_run_underlying_expiry_right",
            "idx_surface_v2_quote",
        }.issubset(objects)
    finally:
        conn.close()


def test_v19_schema_hard_disables_surface_decisions(db_path):
    conn = get_connection(db_path)
    try:
        run_id = int(conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id, preregistration_hash, code_git_sha, started_at,
                ended_at, us_session_date, us_session_state, status
            ) VALUES ('V19_FIREWALL', 'hash', 'sha', '2026-09-03T18:00:00Z',
                      '2026-09-03T18:01:00Z', '2026-09-03', 'INTRADAY', 'COMPLETED');
            """
        ).lastrowid)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO local_surface_residual_v2_runs (
                    research_run_id, model_family_id, model_version, fit_spec_version,
                    config_hash, config_json, observed_at, structural_input_count,
                    reference_mapped_count, evaluable_count, surfaced_count, decision_enabled
                ) VALUES (?, 'LOCAL_SURFACE_RESIDUAL_V2', 'x', 'x', 'h', '{}',
                          '2026-09-03T18:01:00Z', 0, 0, 0, 1, 0);
                """,
                (run_id,),
            )
    finally:
        conn.close()


def test_migration_019_rehearses_from_exact_v18_shape(tmp_path):
    db = tmp_path / "migration_019_from_v18.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
            INSERT INTO schema_version VALUES (18, '2026-09-03T00:00:00Z');
            CREATE TABLE research_runs (id INTEGER PRIMARY KEY);
            CREATE TABLE listing_reference_contracts (id INTEGER PRIMARY KEY);
            CREATE TABLE market_snapshots (id INTEGER PRIMARY KEY, us_session_date TEXT);
            CREATE TABLE option_quotes (
                id INTEGER PRIMARY KEY, snapshot_id INTEGER, bid REAL, ask REAL,
                FOREIGN KEY(snapshot_id) REFERENCES market_snapshots(id)
            );
            CREATE TABLE provider_model_observations (
                id INTEGER PRIMARY KEY, option_quote_id INTEGER, provider TEXT,
                greek_age_seconds REAL, quote_greek_skew_seconds REAL,
                underlying_greek_skew_seconds REAL
            );
            """
        )
        conn.executescript(MIGRATION.read_text(encoding="utf-8"))
        assert conn.execute("SELECT MAX(version) FROM schema_version;").fetchone()[0] == 19
        assert conn.execute("PRAGMA integrity_check;").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        conn.close()
