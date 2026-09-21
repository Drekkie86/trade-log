from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from src.database.repository import resolve_db_path


@dataclass(frozen=True)
class StorageObject:
    name: str
    object_type: str
    bytes: int
    pages: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StorageAudit:
    database_path: str
    database_size_bytes: int
    page_size_bytes: int
    page_count: int
    freelist_pages: int
    freelist_bytes: int
    objects: tuple[StorageObject, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "objects": [
                item.as_dict()
                for item in self.objects
            ],
        }


def audit_storage(
    db_path: str | Path | None = None,
) -> StorageAudit:
    path = resolve_db_path(db_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Christiania database not found: {path}"
        )

    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=30.0,
    )

    try:
        page_size = int(
            conn.execute(
                "PRAGMA page_size;"
            ).fetchone()[0]
        )
        page_count = int(
            conn.execute(
                "PRAGMA page_count;"
            ).fetchone()[0]
        )
        freelist = int(
            conn.execute(
                "PRAGMA freelist_count;"
            ).fetchone()[0]
        )

        rows = conn.execute(
            """
            SELECT
                d.name,
                COALESCE(m.type, 'internal') AS object_type,
                SUM(d.pgsize) AS bytes,
                COUNT(*) AS pages
            FROM dbstat AS d
            LEFT JOIN sqlite_master AS m
              ON m.name = d.name
            GROUP BY
                d.name,
                COALESCE(m.type, 'internal')
            ORDER BY
                bytes DESC,
                d.name;
            """
        ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError(
            "SQLite dbstat storage attribution is unavailable: "
            f"{type(exc).__name__}:{exc}"
        ) from exc
    finally:
        conn.close()

    objects = tuple(
        StorageObject(
            name=str(row[0]),
            object_type=str(row[1]),
            bytes=int(row[2] or 0),
            pages=int(row[3] or 0),
        )
        for row in rows
    )

    return StorageAudit(
        database_path=str(path),
        database_size_bytes=path.stat().st_size,
        page_size_bytes=page_size,
        page_count=page_count,
        freelist_pages=freelist,
        freelist_bytes=freelist * page_size,
        objects=objects,
    )
