from src.database.repository import get_connection


def test_v25_recovery_provenance_objects(db_path):
    conn = get_connection(db_path)
    try:
        assert conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()[0] == 25

        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(research_run_underlyings);"
            ).fetchall()
        }
        assert {"recovery_error_type", "recovery_error_message"} <= columns

        view = conn.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'view'
              AND name = 'v_local_surface_v2_prospective_partition_v2';
            """
        ).fetchone()
        assert view is not None

        sql = view["sql"]
        for required in (
            "recovery_attempt_count",
            "was_recovered",
            "recovery_provenance_state",
            "recovery_error_type",
            "recovery_error_message",
            "research_run_underlyings",
        ):
            assert required in sql
    finally:
        conn.close()


def test_v25_keeps_v1_partition_for_reproducibility(db_path):
    conn = get_connection(db_path)
    try:
        names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'view';"
            ).fetchall()
        }
        assert "v_local_surface_v2_prospective_partition_v1" in names
        assert "v_local_surface_v2_prospective_partition_v2" in names
    finally:
        conn.close()
