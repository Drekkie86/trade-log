from pathlib import Path

from src.database.repository import get_connection

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "trade_log_schema.sql"


def build_v13(path):
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

        # IMPORTANT:
        # This dedicated migration test is intentionally frozen
        # to its own target version. Future migrations must not
        # change what "build_v13" means.
        if (
            number > native_version
            and number <= 13
        ):
            conn.executescript(
                migration.read_text(
                    encoding="utf-8"
                )
            )

    conn.commit()
    return conn


def test_v13_schema_exists(
    tmp_path,
):
    conn = build_v13(
        tmp_path / "v13.db"
    )

    try:
        version = conn.execute(
            "SELECT MAX(version) "
            "FROM schema_version;"
        ).fetchone()[0]

        assert version == 13

        names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master;"
            )
        }

        assert (
            "research_daemon_lock"
            in names
        )
        assert (
            "research_daemon_iterations"
            in names
        )
        assert (
            "shadow_mark_observations"
            in names
        )
    finally:
        conn.close()
