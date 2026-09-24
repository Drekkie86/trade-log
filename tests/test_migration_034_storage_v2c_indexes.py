from __future__ import annotations

import sqlite3

from src.database.repository import (
    EXPECTED_SCHEMA_VERSION,
)
from src.operations.archive_pruning import (
    audit_prune_foreign_key_indexes,
)


EXPECTED_NEW_INDEXES = {
    "idx_shadow_candidates_reference_contract": (
        "shadow_candidates",
        ("reference_contract_id",),
    ),
    "idx_hypothesis_scanner_evaluations_reference": (
        "hypothesis_scanner_evaluations",
        ("reference_contract_id",),
    ),
    "idx_hypothesis_scanner_evaluations_quote": (
        "hypothesis_scanner_evaluations",
        ("option_quote_id",),
    ),
    "idx_surface_v2_reference": (
        "local_surface_residual_v2_observations",
        ("reference_contract_id",),
    ),
}


def _index_columns(
    conn: sqlite3.Connection,
    index_name: str,
) -> tuple[str, ...]:
    rows = conn.execute(
        f'PRAGMA index_info("{index_name}");'
    ).fetchall()

    return tuple(
        str(row[2])
        for row in sorted(
            rows,
            key=lambda item:
                int(item[0]),
        )
    )


def test_migration_034_adds_v2c_fk_delete_indexes(
    db_path,
):
    conn = sqlite3.connect(
        db_path
    )
    try:
        version = int(
            conn.execute(
                "SELECT MAX(version) "
                "FROM schema_version;"
            ).fetchone()[0]
        )

        assert (
            version
            == EXPECTED_SCHEMA_VERSION
            == 34
        )

        for (
            index_name,
            (
                table_name,
                expected_columns,
            ),
        ) in EXPECTED_NEW_INDEXES.items():
            row = conn.execute(
                """
                SELECT tbl_name
                FROM sqlite_master
                WHERE type = 'index'
                  AND name = ?;
                """,
                (index_name,),
            ).fetchone()

            assert row is not None
            assert row[0] == table_name
            assert (
                _index_columns(
                    conn,
                    index_name,
                )
                == expected_columns
            )

        checks = (
            audit_prune_foreign_key_indexes(
                conn
            )
        )

        assert checks
        assert all(
            check.supported
            for check in checks
        )

    finally:
        conn.close()


def test_v2c_fk_audit_detects_missing_child_index(
    db_path,
):
    conn = sqlite3.connect(
        db_path
    )
    try:
        conn.execute(
            "DROP INDEX "
            "idx_shadow_candidates_reference_contract;"
        )

        checks = (
            audit_prune_foreign_key_indexes(
                conn
            )
        )

        missing = [
            check
            for check in checks
            if not check.supported
        ]

        assert [
            check.label
            for check in missing
        ] == [
            (
                "shadow_candidates"
                "(reference_contract_id)"
                "->listing_reference_contracts"
            )
        ]

    finally:
        conn.close()


def test_v2c_fk_indexes_are_query_plan_usable(
    db_path,
):
    conn = sqlite3.connect(
        db_path
    )
    try:
        probes = (
            (
                "shadow_candidates",
                "reference_contract_id",
                "idx_shadow_candidates_reference_contract",
            ),
            (
                "hypothesis_scanner_evaluations",
                "reference_contract_id",
                "idx_hypothesis_scanner_evaluations_reference",
            ),
            (
                "hypothesis_scanner_evaluations",
                "option_quote_id",
                "idx_hypothesis_scanner_evaluations_quote",
            ),
            (
                "local_surface_residual_v2_observations",
                "reference_contract_id",
                "idx_surface_v2_reference",
            ),
        )

        for (
            table_name,
            column_name,
            index_name,
        ) in probes:
            rows = conn.execute(
                "EXPLAIN QUERY PLAN "
                f"SELECT id FROM {table_name} "
                f"WHERE {column_name} = ?;",
                (1,),
            ).fetchall()

            detail = " ".join(
                str(row[3])
                for row in rows
            )

            assert (
                index_name
                in detail
            )

    finally:
        conn.close()
