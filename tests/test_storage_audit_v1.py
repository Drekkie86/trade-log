from __future__ import annotations

import sqlite3

from src.operations.storage_audit import audit_storage


def test_storage_audit_attributes_sqlite_objects(tmp_path):
    db = tmp_path / "storage.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE large_evidence(id INTEGER PRIMARY KEY, payload TEXT)"
        )
        conn.execute(
            "CREATE INDEX ix_large_evidence_payload ON large_evidence(payload)"
        )
        conn.executemany(
            "INSERT INTO large_evidence(payload) VALUES(?)",
            [(("x" * 500) + str(i),) for i in range(200)],
        )
        conn.commit()
    finally:
        conn.close()

    audit = audit_storage(db)

    assert audit.database_size_bytes > 0
    assert audit.page_size_bytes > 0
    assert audit.page_count > 0

    names = {
        item.name
        for item in audit.objects
    }
    assert "large_evidence" in names
    assert "ix_large_evidence_payload" in names

    sizes = {
        item.name: item.bytes
        for item in audit.objects
    }
    assert sizes["large_evidence"] > 0
    assert sizes["ix_large_evidence_payload"] > 0
