import sqlite3
from pathlib import Path

import pytest

from src.database.migration_runner import apply_migration_sql


M = Path(__file__).resolve().parents[1] / "migrations" / "028_local_surface_v2_immutability.sql"

FROZEN_TABLES = (
    "local_surface_residual_v2_observations",
    "local_surface_calibration_readiness_v1_runs",
    "local_surface_calibration_validity_v1_runs",
    "local_surface_null_v1_runs",
    "local_surface_residual_v2_runs",
    "local_surface_robustness_v1_runs",
    "prospective_research_freeze_v1_runs",
    "provider_model_timing_reconstruction_v1_runs",
    "thetadata_timestamp_semantics_v1_runs",
)


def seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE schema_version(
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO schema_version VALUES(27, 'x');")

    for table in FROZEN_TABLES:
        conn.execute(
            f"""
            CREATE TABLE {table}(
                id INTEGER PRIMARY KEY,
                marker TEXT NOT NULL
            );
            """
        )
        conn.execute(
            f"INSERT INTO {table}(id, marker) VALUES(1, 'original');"
        )

    conn.commit()


def migrate(conn: sqlite3.Connection) -> None:
    apply_migration_sql(
        conn,
        M.read_text(encoding="utf-8"),
        expected_from=27,
        target_version=28,
    )


@pytest.mark.parametrize("table", FROZEN_TABLES)
def test_existing_frozen_research_rows_reject_update_and_delete(table: str):
    conn = sqlite3.connect(":memory:")
    try:
        seed(conn)
        migrate(conn)

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                f"UPDATE {table} SET marker = 'tampered' WHERE id = 1;"
            )

        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            conn.execute(
                f"DELETE FROM {table} WHERE id = 1;"
            )

        row = conn.execute(
            f"SELECT marker FROM {table} WHERE id = 1;"
        ).fetchone()
        assert row == ("original",)
        assert conn.execute(
            "SELECT MAX(version) FROM schema_version;"
        ).fetchone()[0] == 28
    finally:
        conn.close()
