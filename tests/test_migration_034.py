from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database.migration_runner import (
    apply_migration_file,
    get_schema_version,
)
from src.operations.archive_pruning import (
    _foreign_key_index_checks,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "migrations"
    / "034_storage_v2c_fk_delete_indexes.sql"
)


EXPECTED_INDEXES = {
    "shadow_candidates": {
        "reference_contract_id":
            "idx_shadow_candidates_reference_contract",
    },
    "hypothesis_scanner_evaluations": {
        "reference_contract_id":
            "idx_hypothesis_scanner_evaluations_reference_contract",
        "option_quote_id":
            "idx_hypothesis_scanner_evaluations_option_quote",
    },
    "local_surface_residual_v2_observations": {
        "reference_contract_id":
            "idx_surface_v2_reference_contract",
    },
}


def _build_v33_minimal(
    path: Path,
) -> sqlite3.Connection:
    conn = sqlite3.connect(
        path
    )
    conn.execute(
        "PRAGMA foreign_keys = ON;"
    )
    conn.executescript(
        """
        CREATE TABLE schema_version (
            version INTEGER NOT NULL,
            applied_at TEXT NOT NULL
        );

        INSERT INTO schema_version(
            version,
            applied_at
        )
        VALUES(
            33,
            '2026-09-24T00:00:00Z'
        );

        CREATE TABLE listing_reference_contracts (
            id INTEGER PRIMARY KEY
        );

        CREATE TABLE option_quotes (
            id INTEGER PRIMARY KEY
        );

        CREATE TABLE shadow_candidates (
            id INTEGER PRIMARY KEY,
            reference_contract_id INTEGER NOT NULL
                REFERENCES listing_reference_contracts(id)
        );

        CREATE TABLE hypothesis_scanner_evaluations (
            id INTEGER PRIMARY KEY,
            scanner_run_id INTEGER NOT NULL,
            reference_contract_id INTEGER NOT NULL
                REFERENCES listing_reference_contracts(id),
            option_quote_id INTEGER NOT NULL
                REFERENCES option_quotes(id),
            UNIQUE(
                scanner_run_id,
                option_quote_id
            )
        );

        CREATE TABLE local_surface_residual_v2_observations (
            id INTEGER PRIMARY KEY,
            model_run_id INTEGER NOT NULL,
            reference_contract_id INTEGER NOT NULL
                REFERENCES listing_reference_contracts(id),
            option_quote_id INTEGER NOT NULL
                REFERENCES option_quotes(id),
            UNIQUE(
                model_run_id,
                option_quote_id
            )
        );

        CREATE INDEX idx_surface_v2_quote
        ON local_surface_residual_v2_observations(
            option_quote_id
        );
        """
    )
    conn.commit()
    return conn


def _index_columns(
    conn: sqlite3.Connection,
    index_name: str,
) -> tuple[str, ...]:
    rows = conn.execute(
        f'PRAGMA index_info("{index_name}");'
    ).fetchall()

    return tuple(
        str(row[2])
        for row in rows
    )


def test_migration_034_adds_exact_missing_parent_delete_indexes(
    tmp_path: Path,
) -> None:
    db = (
        tmp_path
        / "migration034.db"
    )
    conn = _build_v33_minimal(
        db
    )

    try:
        before = (
            _foreign_key_index_checks(
                conn
            )
        )

        missing_before = {
            (
                check.child_table,
                check.child_columns,
                check.parent_table,
            )
            for check in before
            if not check.supported
        }

        assert missing_before == {
            (
                "shadow_candidates",
                ("reference_contract_id",),
                "listing_reference_contracts",
            ),
            (
                "hypothesis_scanner_evaluations",
                ("reference_contract_id",),
                "listing_reference_contracts",
            ),
            (
                "hypothesis_scanner_evaluations",
                ("option_quote_id",),
                "option_quotes",
            ),
            (
                "local_surface_residual_v2_observations",
                ("reference_contract_id",),
                "listing_reference_contracts",
            ),
        }

        apply_migration_file(
            conn,
            MIGRATION,
            expected_from=33,
            target_version=34,
        )

        assert (
            get_schema_version(
                conn
            )
            == 34
        )

        for (
            table_name,
            columns,
        ) in EXPECTED_INDEXES.items():
            for (
                column_name,
                index_name,
            ) in columns.items():
                assert (
                    _index_columns(
                        conn,
                        index_name,
                    )
                    == (
                        column_name,
                    )
                )

        after = (
            _foreign_key_index_checks(
                conn
            )
        )

        assert after
        assert all(
            check.supported
            for check in after
        )
    finally:
        conn.close()


def test_v34_audit_fails_if_support_index_is_removed(
    tmp_path: Path,
) -> None:
    db = (
        tmp_path
        / "migration034_drop.db"
    )
    conn = _build_v33_minimal(
        db
    )

    try:
        apply_migration_file(
            conn,
            MIGRATION,
            expected_from=33,
            target_version=34,
        )

        conn.execute(
            """
            DROP INDEX
            idx_hypothesis_scanner_evaluations_reference_contract;
            """
        )

        checks = (
            _foreign_key_index_checks(
                conn
            )
        )

        failed = [
            check
            for check in checks
            if not check.supported
        ]

        assert len(failed) == 1

        check = failed[0]

        assert (
            check.child_table
            == "hypothesis_scanner_evaluations"
        )
        assert (
            check.parent_table
            == "listing_reference_contracts"
        )
        assert (
            check.child_columns
            == (
                "reference_contract_id",
            )
        )
    finally:
        conn.close()



def test_migration_034_prune_commit_ledger_is_immutable(
    tmp_path: Path,
) -> None:
    db = (
        tmp_path
        / "migration034_ledger.db"
    )
    conn = _build_v33_minimal(
        db
    )

    try:
        apply_migration_file(
            conn,
            MIGRATION,
            expected_from=33,
            target_version=34,
        )

        conn.execute(
            """
            INSERT INTO research_archive_prune_commits_v1(
                session_date,
                committed_at,
                state,
                schema_version,
                archive_manifest_sha256,
                remote_proof_sha256,
                historical_analysis_version,
                hot_analysis_sha256,
                archive_analysis_sha256,
                receipt_json,
                receipt_sha256
            )
            VALUES(
                '2026-09-01',
                '2026-09-25T00:00:00Z',
                'REFERENCE_AWARE_HOT_PRUNE_COMMITTED',
                34,
                ?,
                ?,
                1,
                ?,
                ?,
                '{}',
                ?
            );
            """,
            (
                "a" * 64,
                "b" * 64,
                "c" * 64,
                "d" * 64,
                "e" * 64,
            ),
        )

        with pytest.raises(
            sqlite3.IntegrityError,
            match=(
                "Research archive prune commit "
                "evidence is immutable"
            ),
        ):
            conn.execute(
                """
                UPDATE research_archive_prune_commits_v1
                SET committed_at =
                    '2026-09-25T01:00:00Z'
                WHERE session_date =
                    '2026-09-01';
                """
            )

        with pytest.raises(
            sqlite3.IntegrityError,
            match=(
                "Research archive prune commit "
                "evidence cannot be deleted"
            ),
        ):
            conn.execute(
                """
                DELETE FROM research_archive_prune_commits_v1
                WHERE session_date =
                    '2026-09-01';
                """
            )
    finally:
        conn.close()
