from pathlib import Path

from src.database.repository import get_connection

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "trade_log_schema.sql"


def build_v14(path):
    conn = get_connection(path)

    conn.executescript(
        SCHEMA.read_text(
            encoding="utf-8"
        )
    )

    native_version = conn.execute(
        "SELECT MAX(version) "
        "FROM schema_version;"
    ).fetchone()[0]

    for migration in sorted(
        (ROOT / "migrations").glob("*.sql")
    ):
        number = int(
            migration.name.split("_", 1)[0]
        )

        # Dedicated migration tests are frozen to their own target.
        if (
            number > native_version
            and number <= 14
        ):
            conn.executescript(
                migration.read_text(
                    encoding="utf-8"
                )
            )

    conn.commit()
    return conn


def test_v14_schema_accepts_orphaned_daemon_iterations(
    tmp_path,
):
    conn = build_v14(
        tmp_path / "v14.db"
    )

    try:
        version = conn.execute(
            "SELECT MAX(version) "
            "FROM schema_version;"
        ).fetchone()[0]

        assert version == 14

        conn.execute(
            """
            INSERT INTO research_daemon_iterations (
                owner_token,
                scheduled_for,
                started_at,
                completed_at,
                status,
                error_type
            )
            VALUES (
                'test-owner',
                '2026-09-01T13:00:00Z',
                '2026-09-01T13:00:00Z',
                '2026-09-01T14:00:00Z',
                'ORPHANED',
                'INTERRUPTED_PROCESS'
            );
            """
        )

        conn.commit()

        row = conn.execute(
            """
            SELECT status
            FROM research_daemon_iterations
            WHERE owner_token = 'test-owner';
            """
        ).fetchone()

        assert row["status"] == "ORPHANED"
    finally:
        conn.close()
