"""Bounded, fail-closed release checks for large, already-audited SQLite data.

A fresh independent-volume backup with *completed actual restore* is required
before the large database branch. The SQLite online backup API is atomic.
Check its schema, full logical page count, and critical indexed high-watermarks,
then use additive migration-delta checks. Do not silently label this a full
integrity_check or foreign-key audit. Small DBs retain exhaustive verification.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

LARGE_DB_THRESHOLD_BYTES = 4 * 1024**3
MAX_AUDIT_AGE = timedelta(hours=36)
HIGH_WATERMARK_TABLES = (
    "research_runs",
    "market_snapshots",
    "option_quotes",
    "shadow_candidates",
    "shadow_structure_proposals",
    "shadow_admission_decisions",
    "shadow_mark_observations",
)


def require_recent_independent_restored_archive(
    *, source: Path, backup_dir: Path, expected_schema_version: int,
    now: datetime | None = None,
) -> dict[str, object]:
    """Require the v3 manifest AND matching independent full-restore audit.

    The nightly scheduler's progress status is not a completed restore
    receipt. Reuse one fail-closed verifier for the deployment transition
    and the actual large-schema migration.
    """
    from src.operations.verified_volume_recovery_v1 import verify_recent_restored_archive

    return verify_recent_restored_archive(
        source=source, backup_dir=backup_dir,
        expected_schema_version=expected_schema_version, now=now,
    )



def _open_readonly(path: Path) -> sqlite3.Connection:
    c=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=10.0)
    c.execute("PRAGMA query_only=ON")
    return c


def snapshot_bounded_fingerprint(conn: sqlite3.Connection) -> dict[str, object]:
    """O(number of schema objects): no option-quote/history full scan."""
    schema=int(conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0])
    page_size=int(conn.execute("PRAGMA page_size").fetchone()[0])
    page_count=int(conn.execute("PRAGMA page_count").fetchone()[0])
    master=tuple(
        (str(kind),str(name),str(table_name),str(sql))
        for kind,name,table_name,sql in conn.execute(
            "SELECT type,name,tbl_name,COALESCE(sql,'') FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
    )
    table_names={row[1] for row in master if row[0]=="table"}
    highs={}
    for name in HIGH_WATERMARK_TABLES:
        if name in table_names:
            highs[name]=conn.execute(
                'SELECT id FROM "'+name+'" ORDER BY id DESC LIMIT 1'
            ).fetchone()
    return {
        "schema":schema,"page_count":page_count,"page_size":page_size,
        "objects":master,"high_watermarks":highs,
    }


def verify_sqlite_backup_bounded(
    *, source: Path, copy: Path, expected_version: int,
    recovery_dir: Path,
) -> dict[str, object]:
    """Backed by a fresh full restore audit, match source/copy snapshots.

    Caller must hold the release lock and quiesce all database writers.
    """
    audit=require_recent_independent_restored_archive(
        source=source,backup_dir=recovery_dir,
        expected_schema_version=expected_version,
    )
    with closing(_open_readonly(source)) as a, closing(_open_readonly(copy)) as b:
        original=snapshot_bounded_fingerprint(a)
        restored=snapshot_bounded_fingerprint(b)
    if original["schema"] != expected_version or restored["schema"] != expected_version:
        raise RuntimeError("LARGE_RELEASE_COPY_SCHEMA_MISMATCH")
    if original != restored:
        raise RuntimeError("LARGE_RELEASE_COPY_METADATA_OR_HIGHWATER_MISMATCH")
    if copy.stat().st_size != original["page_count"] * original["page_size"]:
        raise RuntimeError("LARGE_RELEASE_COPY_LOGICAL_BYTES_MISMATCH")
    return {
        "verification":"BOUNDED_COPY_IDENTITY_PLUS_RECENT_RESTORED_ARCHIVE",
        "page_count":original["page_count"],
        "schema":expected_version,
        "backup_restore_audit":audit,
    }
