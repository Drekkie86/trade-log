from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database.migration_runner import (
    apply_migration_file,
    get_schema_version,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "032_h2_h3_followup_confirmation.sql"


def _build_v31_minimal(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(
        """
        CREATE TABLE schema_version (
            version INTEGER NOT NULL,
            applied_at TEXT NOT NULL
        );
        INSERT INTO schema_version(version, applied_at)
        VALUES (31, '2026-09-17T00:00:00Z');

        CREATE TABLE prospective_research_freeze_v1_runs (
            id INTEGER PRIMARY KEY
        );
        INSERT INTO prospective_research_freeze_v1_runs(id) VALUES (7);

        CREATE TABLE local_surface_residual_v2_runs (
            id INTEGER PRIMARY KEY,
            config_hash TEXT NOT NULL
        );

        CREATE TABLE local_surface_residual_v2_observations (
            id INTEGER PRIMARY KEY,
            option_quote_id INTEGER NOT NULL,
            model_run_id INTEGER NOT NULL
                REFERENCES local_surface_residual_v2_runs(id)
        );

        CREATE TABLE discovery_rows (
            observation_id INTEGER NOT NULL,
            us_session_date TEXT NOT NULL
        );

        CREATE VIEW v_local_surface_residual_v2_discovery_dataset AS
        SELECT observation_id, us_session_date
        FROM discovery_rows;

        CREATE VIEW v_local_surface_v2_prospective_partition_v1 AS
        SELECT 1 AS sentinel;

        CREATE VIEW v_local_surface_v2_prospective_partition_v2 AS
        SELECT 2 AS sentinel;
        """
    )
    conn.commit()
    return conn


def _insert_program(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        """
        INSERT INTO prospective_followup_programs_v1 (
            program_key,
            protocol_version,
            source_original_freeze_run_id,
            frozen_at,
            frozen_through_session_date,
            prospective_start_session_date,
            protocol_state,
            config_hash,
            config_json,
            discovery_context_json,
            p_values_enabled,
            fdr_enabled,
            admission_enabled,
            model_promotion_enabled,
            decision_enabled
        ) VALUES (
            'H2_H3_FOLLOWUP_CONFIRMATION_V1',
            '1.0.0',
            7,
            '2026-09-18T08:00:00Z',
            '2026-09-17',
            '2026-09-18',
            'FROZEN_FOLLOWUP_OBSERVATION_ONLY',
            ?,
            '{}',
            '{}',
            0, 0, 0, 0, 0
        );
        """,
        ("a" * 64,),
    )
    conn.commit()
    return int(cursor.lastrowid)


def test_migration_032_keeps_original_freeze_views_and_adds_fixed_followup_partition(
    tmp_path: Path,
) -> None:
    db = tmp_path / "migration032.db"
    conn = _build_v31_minimal(db)
    try:
        apply_migration_file(
            conn,
            MIGRATION,
            expected_from=31,
            target_version=32,
        )

        assert get_schema_version(conn) == 32
        assert conn.execute(
            "SELECT sentinel FROM v_local_surface_v2_prospective_partition_v1;"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT sentinel FROM v_local_surface_v2_prospective_partition_v2;"
        ).fetchone()[0] == 2

        program_id = _insert_program(conn)

        conn.execute(
            "INSERT INTO local_surface_residual_v2_runs(id, config_hash) VALUES (1, ?);",
            ("b" * 64,),
        )
        conn.executemany(
            """
            INSERT INTO local_surface_residual_v2_observations(
                id, option_quote_id, model_run_id
            ) VALUES (?, ?, 1);
            """,
            [(10, 100, 1), (11, 101, 1)],
        )
        conn.executemany(
            "INSERT INTO discovery_rows(observation_id, us_session_date) VALUES (?, ?);",
            [(10, "2026-09-17"), (11, "2026-09-18")],
        )
        conn.commit()

        phases = conn.execute(
            """
            SELECT us_session_date, followup_evidence_phase
            FROM v_h2_h3_followup_partition_v1
            WHERE followup_program_id = ?
            ORDER BY us_session_date;
            """,
            (program_id,),
        ).fetchall()

        assert phases == [
            ("2026-09-17", "DISCOVERY_EXCLUDED"),
            ("2026-09-18", "FOLLOWUP_PROSPECTIVE"),
        ]
    finally:
        conn.close()


def test_migration_032_followup_program_is_immutable(tmp_path: Path) -> None:
    db = tmp_path / "migration032_immutable.db"
    conn = _build_v31_minimal(db)
    try:
        apply_migration_file(
            conn,
            MIGRATION,
            expected_from=31,
            target_version=32,
        )
        program_id = _insert_program(conn)

        with pytest.raises(
            sqlite3.IntegrityError,
            match="Prospective follow-up programme evidence is immutable",
        ):
            conn.execute(
                """
                UPDATE prospective_followup_programs_v1
                SET prospective_start_session_date = '2026-09-19'
                WHERE id = ?;
                """,
                (program_id,),
            )
    finally:
        conn.close()
