import sqlite3
from pathlib import Path

import pytest

from src.database.repository import get_connection

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "020_local_surface_empirical_null_v1.sql"


def test_migration_020_adds_null_model_tables_and_view(db_path):
    conn = get_connection(db_path)
    try:
        assert conn.execute("SELECT MAX(version) FROM schema_version;").fetchone()[0] == 23
        objects = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view','index');")}
        assert {
            "local_surface_null_v1_runs",
            "local_surface_null_v1_strata",
            "local_surface_null_v1_membership",
            "local_surface_null_v1_dependence",
            "v_local_surface_null_v1_discovery_membership",
            "idx_null_v1_membership_observation",
            "idx_null_v1_membership_stratum",
        }.issubset(objects)
    finally:
        conn.close()


def test_v20_schema_hard_disables_pvalues_fdr_and_decisions(db_path):
    conn = get_connection(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO local_surface_null_v1_runs (
                    null_family_id, null_model_version, stratification_version,
                    dependence_spec_version, source_v2_model_version, config_hash,
                    config_json, fitted_at, source_first_session_date, source_last_session_date,
                    source_max_observation_id, observation_count, stratum_count,
                    discovery_window_count, model_state, p_values_enabled, fdr_enabled, decision_enabled
                ) VALUES ('N', 'x', 'x', 'x', '0.1.0', 'h', '{}', '2026-09-03T00:00:00Z',
                          '2026-09-03', '2026-09-03', 1, 100, 1, 1,
                          'ESTIMATED_DISCOVERY_ONLY', 1, 0, 0);
                """
            )
    finally:
        conn.close()


def test_migration_020_rehearses_from_exact_v19_shape(tmp_path):
    db = tmp_path / "migration_020_from_v19.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
            INSERT INTO schema_version VALUES (19, '2026-09-03T00:00:00Z');
            CREATE TABLE local_surface_residual_v2_observations (id INTEGER PRIMARY KEY);
            CREATE VIEW v_local_surface_residual_v2_discovery_dataset AS
                SELECT NULL AS observation_id, NULL AS research_run_id, NULL AS us_session_date,
                       NULL AS underlying, NULL AS expiration, NULL AS strike, NULL AS right,
                       NULL AS abs_delta, NULL AS dte, NULL AS spread_to_mid,
                       NULL AS greek_age_seconds, NULL AS quote_greek_skew_seconds,
                       NULL AS underlying_greek_skew_seconds, NULL AS loo_residual;
            """
        )
        conn.executescript(MIGRATION.read_text(encoding="utf-8"))
        assert conn.execute("SELECT MAX(version) FROM schema_version;").fetchone()[0] == 20
        assert conn.execute("PRAGMA integrity_check;").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        conn.close()
