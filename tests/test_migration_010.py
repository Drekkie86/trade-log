import sqlite3
from pathlib import Path

import pytest

from src.database.repository import get_connection

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "trade_log_schema.sql"


def build_v10(path):
    conn = get_connection(path)
    conn.executescript(
        SCHEMA.read_text(
            encoding="utf-8"
        )
    )

    native_version = conn.execute(
        "SELECT MAX(version) FROM schema_version;"
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


def test_v10_schema_and_immutability(
    tmp_path,
):
    conn = build_v10(
        tmp_path / "v10.db"
    )

    try:
        version = conn.execute(
            "SELECT MAX(version) FROM schema_version;"
        ).fetchone()[0]

        assert version == 10

        names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master;"
            )
        }

        assert "hypothesis_scanner_runs" in names
        assert "hypothesis_scanner_evaluations" in names
    finally:
        conn.close()
