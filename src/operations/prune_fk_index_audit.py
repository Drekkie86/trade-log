from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from src.database.repository import (
    resolve_db_path,
)


PRUNE_PARENT_TABLES = (
    "listing_reference_contracts",
    "option_quotes",
)

_SAFE_IDENTIFIER = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*$"
)


@dataclass(frozen=True)
class ForeignKeyIndexCheck:
    child_table: str
    child_columns: tuple[str, ...]
    parent_table: str
    parent_columns: tuple[str, ...]
    supporting_index: str | None

    @property
    def passed(self) -> bool:
        return (
            self.supporting_index
            is not None
        )

    @property
    def key(self) -> str:
        return (
            f"{self.child_table}"
            f"({','.join(self.child_columns)})"
            "->"
            f"{self.parent_table}"
            f"({','.join(self.parent_columns)})"
        )

    def as_dict(
        self,
    ) -> dict[str, object]:
        return (
            asdict(self)
            | {
                "passed": self.passed,
                "key": self.key,
            }
        )


@dataclass(frozen=True)
class ForeignKeyIndexAudit:
    parent_tables: tuple[str, ...]
    missing_parent_tables: tuple[str, ...]
    checks: tuple[
        ForeignKeyIndexCheck,
        ...,
    ]

    @property
    def missing(self) -> tuple[
        ForeignKeyIndexCheck,
        ...,
    ]:
        return tuple(
            check
            for check
            in self.checks
            if not check.passed
        )

    @property
    def passed(self) -> bool:
        return (
            not self.missing_parent_tables
            and not self.missing
        )

    @property
    def state(self) -> str:
        return (
            "PASS"
            if self.passed
            else "FAIL"
        )

    def as_dict(
        self,
    ) -> dict[str, object]:
        return {
            "state": self.state,
            "passed": self.passed,
            "parent_tables": list(
                self.parent_tables
            ),
            "missing_parent_tables": list(
                self.missing_parent_tables
            ),
            "checks": [
                check.as_dict()
                for check
                in self.checks
            ],
            "missing": [
                check.as_dict()
                for check
                in self.missing
            ],
        }


def _quoted_identifier(
    value: str,
) -> str:
    if not _SAFE_IDENTIFIER.fullmatch(
        value
    ):
        raise ValueError(
            "Unsafe SQLite identifier: "
            f"{value!r}"
        )

    return (
        '"'
        + value
        + '"'
    )


def _table_names(
    conn: sqlite3.Connection,
) -> tuple[str, ...]:
    return tuple(
        str(row[0])
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name;
            """
        ).fetchall()
    )


def _index_columns(
    conn: sqlite3.Connection,
    table_name: str,
) -> dict[str, tuple[str, ...]]:
    quoted = _quoted_identifier(
        table_name
    )

    indexes: dict[
        str,
        tuple[str, ...],
    ] = {}

    for row in conn.execute(
        f"PRAGMA index_list({quoted});"
    ).fetchall():
        index_name = str(
            row[1]
        )

        if not _SAFE_IDENTIFIER.fullmatch(
            index_name
        ):
            continue

        quoted_index = (
            _quoted_identifier(
                index_name
            )
        )

        columns = tuple(
            str(item[2])
            for item
            in conn.execute(
                (
                    "PRAGMA index_info("
                    f"{quoted_index}"
                    ");"
                )
            ).fetchall()
            if item[2] is not None
        )

        indexes[
            index_name
        ] = columns

    return indexes


def _primary_key_columns(
    conn: sqlite3.Connection,
    table_name: str,
) -> tuple[str, ...]:
    quoted = _quoted_identifier(
        table_name
    )

    rows = conn.execute(
        f"PRAGMA table_info({quoted});"
    ).fetchall()

    ordered = sorted(
        (
            (
                int(row[5]),
                str(row[1]),
            )
            for row in rows
            if int(row[5]) > 0
        ),
        key=lambda item: item[0],
    )

    return tuple(
        name
        for _position, name
        in ordered
    )


def _supporting_index(
    conn: sqlite3.Connection,
    *,
    child_table: str,
    child_columns: tuple[str, ...],
) -> str | None:
    primary_key = (
        _primary_key_columns(
            conn,
            child_table,
        )
    )

    if (
        primary_key
        and primary_key[
            :len(child_columns)
        ]
        == child_columns
    ):
        return "PRIMARY_KEY"

    for (
        index_name,
        columns,
    ) in _index_columns(
        conn,
        child_table,
    ).items():
        if (
            columns[
                :len(child_columns)
            ]
            == child_columns
        ):
            return index_name

    return None


def audit_prune_parent_fk_indexes(
    conn: sqlite3.Connection,
    *,
    parent_tables: Iterable[str] = (
        PRUNE_PARENT_TABLES
    ),
) -> ForeignKeyIndexAudit:
    parents = tuple(
        str(value)
        for value
        in parent_tables
    )

    if not parents:
        raise ValueError(
            "At least one prune parent table "
            "is required."
        )

    for parent in parents:
        _quoted_identifier(
            parent
        )

    tables = _table_names(
        conn
    )

    missing_parents = tuple(
        parent
        for parent in parents
        if parent not in tables
    )

    checks: list[
        ForeignKeyIndexCheck
    ] = []

    parent_set = set(
        parents
    )

    for child_table in tables:
        quoted_child = (
            _quoted_identifier(
                child_table
            )
        )

        grouped: dict[
            int,
            list[tuple],
        ] = {}

        for row in conn.execute(
            (
                "PRAGMA foreign_key_list("
                f"{quoted_child}"
                ");"
            )
        ).fetchall():
            parent_table = str(
                row[2]
            )

            if (
                parent_table
                not in parent_set
            ):
                continue

            grouped.setdefault(
                int(row[0]),
                [],
            ).append(
                tuple(row)
            )

        for fk_rows in grouped.values():
            ordered = sorted(
                fk_rows,
                key=lambda row: int(
                    row[1]
                ),
            )

            parent_table = str(
                ordered[0][2]
            )

            child_columns = tuple(
                str(row[3])
                for row in ordered
            )

            parent_columns = tuple(
                str(row[4])
                for row in ordered
            )

            supporting = (
                _supporting_index(
                    conn,
                    child_table=
                        child_table,
                    child_columns=
                        child_columns,
                )
            )

            checks.append(
                ForeignKeyIndexCheck(
                    child_table=
                        child_table,
                    child_columns=
                        child_columns,
                    parent_table=
                        parent_table,
                    parent_columns=
                        parent_columns,
                    supporting_index=
                        supporting,
                )
            )

    checks.sort(
        key=lambda item: (
            item.parent_table,
            item.child_table,
            item.child_columns,
        )
    )

    return ForeignKeyIndexAudit(
        parent_tables=parents,
        missing_parent_tables=
            missing_parents,
        checks=tuple(
            checks
        ),
    )



def audit_prune_database_fk_indexes(
    *,
    db_path: str | Path | None = None,
) -> ForeignKeyIndexAudit:
    database = resolve_db_path(
        db_path
    )

    uri = (
        database.resolve().as_uri()
        + "?mode=ro"
    )

    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=30.0,
    )

    try:
        conn.execute(
            "PRAGMA query_only = ON;"
        )

        return (
            audit_prune_parent_fk_indexes(
                conn
            )
        )
    finally:
        conn.close()
