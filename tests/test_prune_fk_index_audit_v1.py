from __future__ import annotations

import sqlite3

from src.operations.prune_fk_index_audit import (
    PRUNE_PARENT_TABLES,
    audit_prune_parent_fk_indexes,
)


EXPECTED_RELATIONS = {
    (
        "candidate_controls",
        ("control_quote_id",),
        "option_quotes",
    ),
    (
        "candidate_legs",
        ("option_quote_id",),
        "option_quotes",
    ),
    (
        "hypothesis_scanner_evaluations",
        ("option_quote_id",),
        "option_quotes",
    ),
    (
        "hypothesis_scanner_evaluations",
        ("reference_contract_id",),
        "listing_reference_contracts",
    ),
    (
        "local_surface_residual_v2_observations",
        ("option_quote_id",),
        "option_quotes",
    ),
    (
        "local_surface_residual_v2_observations",
        ("reference_contract_id",),
        "listing_reference_contracts",
    ),
    (
        "provider_model_observations",
        ("option_quote_id",),
        "option_quotes",
    ),
    (
        "provider_observation_availability",
        ("reference_contract_id",),
        "listing_reference_contracts",
    ),
    (
        "research_selections",
        ("option_quote_id",),
        "option_quotes",
    ),
    (
        "saxo_contract_failures",
        ("option_quote_id",),
        "option_quotes",
    ),
    (
        "saxo_option_observations",
        ("option_quote_id",),
        "option_quotes",
    ),
    (
        "selection_exclusions",
        ("option_quote_id",),
        "option_quotes",
    ),
    (
        "shadow_candidates",
        ("reference_contract_id",),
        "listing_reference_contracts",
    ),
    (
        "shadow_structure_proposals",
        ("target_reference_contract_id",),
        "listing_reference_contracts",
    ),
}


def test_v34_schema_covers_every_fk_into_prune_parents(
    db_path,
) -> None:
    conn = sqlite3.connect(
        db_path
    )

    try:
        audit = (
            audit_prune_parent_fk_indexes(
                conn
            )
        )

        assert (
            audit.parent_tables
            == PRUNE_PARENT_TABLES
        )
        assert (
            audit.missing_parent_tables
            == ()
        )
        assert audit.passed is True

        actual = {
            (
                check.child_table,
                check.child_columns,
                check.parent_table,
            )
            for check
            in audit.checks
        }

        assert (
            actual
            == EXPECTED_RELATIONS
        )

        assert all(
            check.supporting_index
            for check
            in audit.checks
        )
    finally:
        conn.close()


def test_audit_fails_when_support_index_is_removed(
    db_path,
) -> None:
    conn = sqlite3.connect(
        db_path
    )

    try:
        conn.execute(
            """
            DROP INDEX
            idx_shadow_candidates_reference_contract;
            """
        )

        audit = (
            audit_prune_parent_fk_indexes(
                conn
            )
        )

        assert audit.passed is False

        missing = {
            check.key
            for check
            in audit.missing
        }

        assert (
            "shadow_candidates"
            "(reference_contract_id)"
            "->listing_reference_contracts(id)"
            in missing
        )
    finally:
        conn.close()


def test_audit_requires_prune_parent_tables() -> None:
    conn = sqlite3.connect(
        ":memory:"
    )

    try:
        conn.executescript(
            """
            CREATE TABLE option_quotes(
                id INTEGER PRIMARY KEY
            );
            """
        )

        audit = (
            audit_prune_parent_fk_indexes(
                conn
            )
        )

        assert audit.passed is False
        assert (
            audit.missing_parent_tables
            == (
                "listing_reference_contracts",
            )
        )
    finally:
        conn.close()
