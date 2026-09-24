from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import sqlite3

from src.database.repository import (
    resolve_db_path,
)


PRUNE_PARENT_TABLES = (
    "local_surface_residual_v2_observations",
    "hypothesis_scanner_evaluations",
    "provider_model_observations",
    "provider_observation_availability",
    "listing_reference_contracts",
    "option_quotes",
)

_SAFE_IDENTIFIER = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*$"
)


@dataclass(frozen=True)
class ForeignKeyIndexCheck:
    child_table: str
    foreign_key_id: int
    parent_table: str
    child_columns: tuple[str, ...]
    parent_columns: tuple[str, ...]
    supporting_index: str | None
    passed: bool

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["child_columns"] = list(
            self.child_columns
        )
        data["parent_columns"] = list(
            self.parent_columns
        )
        return data


@dataclass(frozen=True)
class PruneForeignKeyIndexAudit:
    target_parents: tuple[str, ...]
    checks: tuple[ForeignKeyIndexCheck, ...]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(
            item.passed
            for item in self.checks
        )

    @property
    def missing(self) -> tuple[
        ForeignKeyIndexCheck,
        ...,
    ]:
        return tuple(
            item
            for item in self.checks
            if not item.passed
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "target_parents": list(
                self.target_parents
            ),
            "passed": self.passed,
            "checks": [
                item.as_dict()
                for item in self.checks
            ],
            "missing": [
                item.as_dict()
                for item in self.missing
            ],
        }


def _quote_identifier(
    value: str,
) -> str:
    if not _SAFE_IDENTIFIER.fullmatch(
        value
    ):
        raise ValueError(
            f"Unsafe SQLite identifier: {value!r}"
        )

    return '"' + value + '"'


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


def _foreign_keys(
    conn: sqlite3.Connection,
    child_table: str,
) -> tuple[
    tuple[
        int,
        str,
        tuple[str, ...],
        tuple[str, ...],
    ],
    ...,
]:
    quoted = _quote_identifier(
        child_table
    )
    rows = conn.execute(
        f"PRAGMA foreign_key_list({quoted});"
    ).fetchall()

    grouped: dict[
        tuple[int, str],
        list[tuple[int, str, str]],
    ] = {}

    for row in rows:
        fk_id = int(row[0])
        sequence = int(row[1])
        parent = str(row[2])
        child_column = str(row[3])
        parent_column = str(
            row[4]
            if row[4] is not None
            else ""
        )

        grouped.setdefault(
            (fk_id, parent),
            [],
        ).append(
            (
                sequence,
                child_column,
                parent_column,
            )
        )

    result = []

    for (
        fk_id,
        parent,
    ), columns in grouped.items():
        ordered = sorted(
            columns,
            key=lambda item: item[0],
        )

        result.append(
            (
                fk_id,
                parent,
                tuple(
                    item[1]
                    for item in ordered
                ),
                tuple(
                    item[2]
                    for item in ordered
                ),
            )
        )

    return tuple(
        sorted(
            result,
            key=lambda item: (
                item[1],
                item[0],
            ),
        )
    )


def _supporting_index(
    conn: sqlite3.Connection,
    child_table: str,
    child_columns: tuple[str, ...],
) -> str | None:
    quoted = _quote_identifier(
        child_table
    )

    for row in conn.execute(
        f"PRAGMA index_list({quoted});"
    ).fetchall():
        index_name = str(
            row[1]
        )

        # Partial indexes do not cover every child row and therefore
        # cannot be the generic FK support index used by parent deletes.
        partial = bool(
            row[4]
            if len(row) > 4
            else False
        )
        if partial:
            continue

        index_quoted = _quote_identifier(
            index_name
        )

        columns = tuple(
            str(index_row[2])
            for index_row
            in conn.execute(
                f"PRAGMA index_info({index_quoted});"
            ).fetchall()
            if index_row[2] is not None
        )

        if (
            len(columns)
            >= len(child_columns)
            and columns[
                :len(child_columns)
            ]
            == child_columns
        ):
            return index_name

    return None


def audit_prune_foreign_key_indexes_connection(
    conn: sqlite3.Connection,
) -> PruneForeignKeyIndexAudit:
    checks: list[
        ForeignKeyIndexCheck
    ] = []

    targets = set(
        PRUNE_PARENT_TABLES
    )

    for child_table in _table_names(
        conn
    ):
        for (
            fk_id,
            parent_table,
            child_columns,
            parent_columns,
        ) in _foreign_keys(
            conn,
            child_table,
        ):
            if parent_table not in targets:
                continue

            index_name = (
                _supporting_index(
                    conn,
                    child_table,
                    child_columns,
                )
            )

            checks.append(
                ForeignKeyIndexCheck(
                    child_table=child_table,
                    foreign_key_id=fk_id,
                    parent_table=parent_table,
                    child_columns=(
                        child_columns
                    ),
                    parent_columns=(
                        parent_columns
                    ),
                    supporting_index=(
                        index_name
                    ),
                    passed=(
                        index_name
                        is not None
                    ),
                )
            )

    return PruneForeignKeyIndexAudit(
        target_parents=(
            PRUNE_PARENT_TABLES
        ),
        checks=tuple(
            sorted(
                checks,
                key=lambda item: (
                    item.parent_table,
                    item.child_table,
                    item.foreign_key_id,
                ),
            )
        ),
    )


def audit_prune_foreign_key_indexes(
    db_path: str | Path | None = None,
) -> PruneForeignKeyIndexAudit:
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
        return (
            audit_prune_foreign_key_indexes_connection(
                conn
            )
        )
    finally:
        conn.close()


def require_prune_foreign_key_indexes(
    conn: sqlite3.Connection,
) -> PruneForeignKeyIndexAudit:
    audit = (
        audit_prune_foreign_key_indexes_connection(
            conn
        )
    )

    if audit.passed:
        return audit

    missing = "; ".join(
        (
            f"{item.child_table}"
            f"({','.join(item.child_columns)})"
            f"->{item.parent_table}"
        )
        for item in audit.missing
    )

    raise RuntimeError(
        "Prune parent foreign-key support "
        "index audit failed: "
        + missing
    )
