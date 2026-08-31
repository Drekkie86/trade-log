from src.database.repository import get_connection


def test_repository_connection_uses_generous_busy_timeout(
    db_path,
):
    conn = get_connection(db_path)

    try:
        busy_timeout_ms = conn.execute(
            "PRAGMA busy_timeout;"
        ).fetchone()[0]
    finally:
        conn.close()

    assert busy_timeout_ms >= 30_000
