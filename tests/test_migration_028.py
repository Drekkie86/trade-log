import sqlite3
from pathlib import Path

import pytest

from src.database.migration_runner import apply_migration_sql


M = Path(__file__).resolve().parents[1] / "migrations" / "028_local_surface_v2_immutability.sql"


def seed(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE schema_version(
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        INSERT INTO schema_version VALUES(27, 'x');

        CREATE TABLE local_surface_residual_v2_observations(
            id INTEGER PRIMARY KEY,
            loo_residual REAL,
            evidence_json TEXT NOT NULL
        );

        INSERT INTO local_surface_residual_v2_observations(
            id, loo_residual, evidence_json
        ) VALUES (
            1, 0.04, '{"frozen":true}'
        );
        """
    )
    conn.commit()


def migrate(conn: sqlite3.Connection) -> None:
    apply_migration_sql(
        conn,
        M.read_text(encoding="utf-8"),
        expected_from=27,
        target_version=28,
    )


def test_existing_local_surface_v2_observation_rejects_update_and_delete():
    conn = sqlite3.connect(":memory:")
    try:
        seed(conn)
        migrate(conn)

        with pytest.raises(sqlite3.IntegrityError, match="immutable scientific evidence"):
            conn.execute(
                "UPDATE local_surface_residual_v2_observations SET loo_residual = 999.0 WHERE id = 1;"
            )

        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            conn.execute(
                "DELETE FROM local_surface_residual_v2_observations WHERE id = 1;"
            )

        row = conn.execute(
            "SELECT loo_residual, evidence_json FROM local_surface_residual_v2_observations WHERE id = 1;"
        ).fetchone()
        assert row == (0.04, '{"frozen":true}')
        assert conn.execute("SELECT MAX(version) FROM schema_version;").fetchone()[0] == 28
    finally:
        conn.close()
