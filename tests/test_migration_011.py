from pathlib import Path

from src.database.repository import get_connection

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "trade_log_schema.sql"


def build_latest(path):
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

        if number > native_version:
            conn.executescript(
                migration.read_text(
                    encoding="utf-8"
                )
            )

    conn.commit()
    return conn


def test_v11_schema_exists(
    tmp_path,
):
    conn = build_latest(
        tmp_path / "v11.db"
    )

    try:
        version = conn.execute(
            "SELECT MAX(version) "
            "FROM schema_version;"
        ).fetchone()[0]

        assert version == 11

        names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master;"
            )
        }

        assert (
            "shadow_structure_proposals"
            in names
        )
        assert (
            "trg_shadow_structure_proposals_no_update"
            in names
        )
    finally:
        conn.close()
