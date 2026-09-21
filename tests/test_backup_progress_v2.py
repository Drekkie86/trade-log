from __future__ import annotations

import sqlite3

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.sqlite_runtime import create_verified_backup


def test_verified_backup_reports_copy_verification_and_promotion(tmp_path):
    db = tmp_path / "source.db"
    backups = tmp_path / "backups"

    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE schema_version(
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO schema_version(version, applied_at)
            VALUES(?, '2026-09-01T00:00:00Z')
            """,
            (EXPECTED_SCHEMA_VERSION,),
        )
        conn.execute(
            "CREATE TABLE evidence(id INTEGER PRIMARY KEY, payload TEXT)"
        )
        conn.executemany(
            "INSERT INTO evidence(payload) VALUES(?)",
            [(("x" * 100),) for _ in range(1000)],
        )
        conn.commit()
    finally:
        conn.close()

    messages = []

    result = create_verified_backup(
        db_path=db,
        backup_dir=backups,
        retention=3,
        progress=messages.append,
    )

    assert result.integrity_check == "ok"
    joined = "\n".join(messages)
    assert "copy: started" in joined
    assert "copy: completed" in joined
    assert "integrity_check started" in joined
    assert "integrity_check completed result=ok" in joined
    assert "foreign_key_check completed violations=0" in joined
    assert "promotion: completed" in joined
