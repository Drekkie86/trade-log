from __future__ import annotations

import sqlite3

from src.operations.sqlite_runtime import (
    inspect_database,
    open_readonly_connection,
)


LEGACY_COLUMNS = """
    id INTEGER,
    proposal_id INTEGER,
    fx_observation_id INTEGER,
    candidate_id INTEGER,
    sizing_policy_version TEXT,
    cost_model_version TEXT,
    cost_provenance TEXT,
    proposal_max_loss_usd_minor INTEGER,
    estimated_cost_usd_minor INTEGER,
    reserved_risk_usd_minor INTEGER,
    converted_max_loss_eur_minor INTEGER,
    estimated_cost_eur_minor INTEGER,
    reserved_risk_eur_minor INTEGER,
    bankroll_cap_eur_minor INTEGER,
    decision TEXT,
    reason_code TEXT,
    decided_at TEXT,
    evidence_json TEXT
"""


def _create_database(path, *, normalized_view: bool) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            "CREATE TABLE schema_version(version INTEGER PRIMARY KEY, applied_at TEXT);"
        )
        conn.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES (29, '2026-09-17T00:00:00Z');"
        )
        conn.execute(
            f"CREATE TABLE shadow_admission_decisions ({LEGACY_COLUMNS});"
        )
        conn.execute(
            """
            INSERT INTO shadow_admission_decisions VALUES (
                1, 10, 20, 30,
                'LEGACY', 'COST', 'LEGACY_COST',
                100, 10, 110,
                90, 9, 99, 50000,
                'ADMITTED', 'LEGACY_REASON',
                '2026-09-17T00:00:00Z', '{}'
            );
            """
        )

        if normalized_view:
            conn.execute(
                """
                CREATE VIEW v_shadow_admission_decisions_all AS
                SELECT * FROM shadow_admission_decisions
                UNION ALL
                SELECT
                    2, 11, 21, 31,
                    'INTRINSIC', 'COST', 'INTRINSIC_COST',
                    200, 20, 220,
                    180, 18, 198, NULL,
                    'ADMITTED', 'INTRINSIC_REASON',
                    '2026-09-17T00:01:00Z', '{}';
                """
            )

        conn.commit()
    finally:
        conn.close()


def test_readonly_connection_normalizes_legacy_and_intrinsic_admission_rows(
    tmp_path,
):
    db = tmp_path / "normalized.db"
    _create_database(db, normalized_view=True)

    conn = open_readonly_connection(db)
    try:
        unqualified = conn.execute(
            "SELECT id, bankroll_cap_eur_minor FROM shadow_admission_decisions ORDER BY id;"
        ).fetchall()
        historical_only = conn.execute(
            "SELECT id FROM main.shadow_admission_decisions ORDER BY id;"
        ).fetchall()
        temp_object = conn.execute(
            """
            SELECT type
            FROM temp.sqlite_master
            WHERE name='shadow_admission_decisions';
            """
        ).fetchone()
        query_only = conn.execute("PRAGMA query_only;").fetchone()[0]
    finally:
        conn.close()

    assert [(row[0], row[1]) for row in unqualified] == [
        (1, 50000),
        (2, None),
    ]
    assert [row[0] for row in historical_only] == [1]
    assert temp_object[0] == "view"
    assert query_only == 1


def test_readonly_connection_is_noop_without_normalized_v29_view(tmp_path):
    db = tmp_path / "legacy.db"
    _create_database(db, normalized_view=False)

    conn = open_readonly_connection(db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM shadow_admission_decisions;"
        ).fetchone()[0]
        temp_object = conn.execute(
            """
            SELECT type
            FROM temp.sqlite_master
            WHERE name='shadow_admission_decisions';
            """
        ).fetchone()
    finally:
        conn.close()

    assert count == 1
    assert temp_object is None


def test_database_health_still_operates_with_readonly_compatibility_view(tmp_path):
    db = tmp_path / "health.db"
    _create_database(db, normalized_view=True)

    health = inspect_database(db)

    assert health.exists is True
    assert health.schema_version == 29
    assert health.expected_schema_version == 29
    assert health.journal_mode == "wal"
    assert health.quick_check == "ok"
    assert health.foreign_key_violation_count == 0
