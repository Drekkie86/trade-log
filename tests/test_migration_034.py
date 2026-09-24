from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database.migration_runner import (
    apply_migration_file,
    get_schema_version,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "migrations"
    / "034_prune_fk_support_indexes.sql"
)


EXPECTED = {
    (
        "shadow_candidates",
        "reference_contract_id",
    ): "idx_shadow_candidates_reference_contract",
    (
        "hypothesis_scanner_evaluations",
        "reference_contract_id",
    ): "idx_hypothesis_scanner_evaluations_reference_contract",
    (
        "hypothesis_scanner_evaluations",
        "option_quote_id",
    ): "idx_hypothesis_scanner_evaluations_option_quote",
    (
        "local_surface_residual_v2_observations",
        "reference_contract_id",
    ): "idx_surface_v2_reference_contract",
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

        CREATE TABLE option_quotes (
            id INTEGER PRIMARY KEY
        );

        CREATE TABLE listing_reference_contracts (
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


def _leading_index_columns(
    conn: sqlite3.Connection,
    table_name: str,
) -> dict[str, tuple[str, ...]]:
    result = {}

    for row in conn.execute(
        f'PRAGMA index_list("{table_name}");'
    ).fetchall():
        index_name = str(
            row[1]
        )
        columns = tuple(
            str(item[2])
            for item in conn.execute(
                f'PRAGMA index_info("{index_name}");'
            ).fetchall()
        )
        result[
            index_name
        ] = columns

    return result


def test_migration_034_adds_only_required_fk_support_indexes(
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
            (
                table_name,
                column_name,
            ),
            index_name,
        ) in EXPECTED.items():
            indexes = (
                _leading_index_columns(
                    conn,
                    table_name,
                )
            )

            assert (
                index_name
                in indexes
            )
            assert (
                indexes[
                    index_name
                ][:1]
                == (
                    column_name,
                )
            )

        assert (
            _leading_index_columns(
                conn,
                "local_surface_residual_v2_observations",
            )[
                "idx_surface_v2_quote"
            ][:1]
            == (
                "option_quote_id",
            )
        )
    finally:
        conn.close()


def test_migration_034_fails_on_conflicting_index_name(
    tmp_path: Path,
) -> None:
    db = (
        tmp_path
        / "migration034-conflict.db"
    )
    conn = _build_v33_minimal(
        db
    )

    try:
        conn.execute(
            """
            CREATE INDEX
            idx_shadow_candidates_reference_contract
            ON shadow_candidates(id);
            """
        )
        conn.commit()

        with pytest.raises(
            sqlite3.OperationalError,
            match="already exists",
        ):
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
            == 33
        )

        columns = (
            _leading_index_columns(
                conn,
                "shadow_candidates",
            )
        )

        assert (
            columns[
                "idx_shadow_candidates_reference_contract"
            ]
            == (
                "id",
            )
        )
    finally:
        conn.close()
