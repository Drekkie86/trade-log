from __future__ import annotations

import sqlite3

from src.operations.prune_schema import (
    PRUNE_PARENT_TABLES,
    audit_prune_foreign_key_indexes,
)


EXPECTED_V34_INDEXES = {
    "idx_shadow_candidates_reference_contract":
        (
            "shadow_candidates",
            (
                "reference_contract_id",
            ),
        ),
    "idx_shadow_candidates_entry_quote_observation":
        (
            "shadow_candidates",
            (
                "entry_quote_observation_id",
            ),
        ),
    "idx_shadow_candidates_entry_greek_observation":
        (
            "shadow_candidates",
            (
                "entry_greek_observation_id",
            ),
        ),
    "idx_hypothesis_scanner_evaluations_reference_contract":
        (
            "hypothesis_scanner_evaluations",
            (
                "reference_contract_id",
            ),
        ),
    "idx_hypothesis_scanner_evaluations_option_quote":
        (
            "hypothesis_scanner_evaluations",
            (
                "option_quote_id",
            ),
        ),
    "idx_surface_v2_reference_contract":
        (
            "local_surface_residual_v2_observations",
            (
                "reference_contract_id",
            ),
        ),
}


def _index_columns(
    conn: sqlite3.Connection,
    index_name: str,
) -> tuple[str, ...]:
    return tuple(
        str(row[2])
        for row in conn.execute(
            f'PRAGMA index_info("{index_name}");'
        ).fetchall()
    )


def test_migration_034_adds_parent_delete_support_indexes(
    db_path,
):
    conn = sqlite3.connect(
        db_path
    )

    try:
        version = int(
            conn.execute(
                """
                SELECT MAX(version)
                FROM schema_version;
                """
            ).fetchone()[0]
        )

        assert version == 34

        for (
            index_name,
            (
                table_name,
                columns,
            ),
        ) in EXPECTED_V34_INDEXES.items():
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
                == columns
            )
    finally:
        conn.close()


def test_all_prune_parent_foreign_keys_have_leading_indexes(
    db_path,
):
    audit = (
        audit_prune_foreign_key_indexes(
            db_path
        )
    )

    assert audit.target_parents == (
        PRUNE_PARENT_TABLES
    )
    assert audit.checks
    assert audit.missing == ()
    assert audit.passed is True

    observed = {
        (
            item.child_table,
            item.parent_table,
            item.child_columns,
        )
        for item in audit.checks
    }

    # These were the production gaps exposed by the Sep-16 V2C delete.
    assert (
        "shadow_candidates",
        "listing_reference_contracts",
        (
            "reference_contract_id",
        ),
    ) in observed

    assert (
        "hypothesis_scanner_evaluations",
        "listing_reference_contracts",
        (
            "reference_contract_id",
        ),
    ) in observed

    assert (
        "hypothesis_scanner_evaluations",
        "option_quotes",
        (
            "option_quote_id",
        ),
    ) in observed

    assert (
        "local_surface_residual_v2_observations",
        "listing_reference_contracts",
        (
            "reference_contract_id",
        ),
    ) in observed

    assert (
        "shadow_candidates",
        "provider_observation_availability",
        (
            "entry_quote_observation_id",
        ),
    ) in observed

    assert (
        "shadow_candidates",
        "provider_observation_availability",
        (
            "entry_greek_observation_id",
        ),
    ) in observed


def test_prune_fk_audit_fails_if_required_index_is_removed(
    db_path,
):
    conn = sqlite3.connect(
        db_path
    )

    try:
        conn.execute(
            """
            DROP INDEX
            idx_surface_v2_reference_contract;
            """
        )
        conn.commit()
    finally:
        conn.close()

    audit = (
        audit_prune_foreign_key_indexes(
            db_path
        )
    )

    assert audit.passed is False

    missing = {
        (
            item.child_table,
            item.parent_table,
            item.child_columns,
        )
        for item in audit.missing
    }

    assert (
        "local_surface_residual_v2_observations",
        "listing_reference_contracts",
        (
            "reference_contract_id",
        ),
    ) in missing


def test_prune_fk_audit_detects_future_unindexed_child_fk(
    db_path,
):
    conn = sqlite3.connect(
        db_path
    )

    try:
        conn.execute(
            """
            CREATE TABLE future_prune_consumer_test(
                id INTEGER PRIMARY KEY,
                option_quote_id INTEGER NOT NULL
                    REFERENCES option_quotes(id)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    audit = (
        audit_prune_foreign_key_indexes(
            db_path
        )
    )

    assert audit.passed is False

    assert any(
        item.child_table
        == "future_prune_consumer_test"
        and item.parent_table
        == "option_quotes"
        and item.child_columns
        == (
            "option_quote_id",
        )
        and item.supporting_index
        is None
        for item in audit.missing
    )
