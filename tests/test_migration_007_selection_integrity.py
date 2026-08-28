from pathlib import Path
import sqlite3

import pytest


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


def build_v7_database(
    tmp_path,
):
    db_path = (
        tmp_path
        / "migration_007.db"
    )

    schema = (
        PROJECT_ROOT
        / "trade_log_schema.sql"
    ).read_text(
        encoding="utf-8"
    )

    migration = (
        PROJECT_ROOT
        / "migrations"
        / "007_selection_universe_integrity.sql"
    ).read_text(
        encoding="utf-8"
    )

    connection = sqlite3.connect(
        db_path
    )

    connection.row_factory = (
        sqlite3.Row
    )

    connection.execute(
        "PRAGMA foreign_keys = ON;"
    )

    connection.executescript(
        schema
    )

    before = connection.execute(
        """
        SELECT MAX(version)
        FROM schema_version;
        """
    ).fetchone()[0]

    assert before == 6

    connection.executescript(
        migration
    )

    after = connection.execute(
        """
        SELECT MAX(version)
        FROM schema_version;
        """
    ).fetchone()[0]

    assert after == 7

    return connection


def create_run(
    connection,
    *,
    suffix: str,
):
    return int(
        connection.execute(
            """
            INSERT INTO research_runs (
                cohort_id,
                preregistration_hash,
                code_git_sha,
                started_at,
                us_session_date,
                us_session_state,
                status
            )
            VALUES (
                'COHORT_001_DATA_QUALITY_BASELINE',
                ?,
                ?,
                '2026-08-28T12:00:00Z',
                '2026-08-28',
                'PRE_OPEN',
                'STARTED'
            );
            """,
            (
                f"hash-{suffix}",
                f"sha-{suffix}",
            ),
        ).lastrowid
    )


def create_snapshot(
    connection,
    *,
    run_id: int,
):
    return int(
        connection.execute(
            """
            INSERT INTO market_snapshots (
                captured_at,
                underlying,
                provider,
                underlying_price,
                underlying_source,
                fx_to_eur,
                fx_source,
                research_run_id,
                us_session_date,
                us_session_state
            )
            VALUES (
                '2026-08-28T12:00:01Z',
                'AAPL',
                'MASSIVE',
                NULL,
                'UNKNOWN',
                NULL,
                'UNKNOWN',
                ?,
                '2026-08-28',
                'PRE_OPEN'
            );
            """,
            (run_id,),
        ).lastrowid
    )


def create_quote(
    connection,
    *,
    snapshot_id: int,
    symbol: str,
):
    return int(
        connection.execute(
            """
            INSERT INTO option_quotes (
                snapshot_id,
                provider_contract_id,
                option_symbol,
                right,
                strike,
                expiration,

                bid,
                bid_source,

                ask,
                ask_source,

                last,
                last_source,

                implied_volatility,
                iv_source,

                delta,
                delta_source,

                gamma,
                gamma_source,

                theta,
                theta_source,

                vega,
                vega_source,

                volume,
                volume_source,

                open_interest,
                open_interest_source
            )
            VALUES (
                ?, ?, ?, 'C', 320, '2026-09-11',

                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN',

                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN',

                NULL, 'UNKNOWN',
                NULL, 'UNKNOWN'
            );
            """,
            (
                snapshot_id,
                symbol,
                symbol,
            ),
        ).lastrowid
    )


def test_migration_007_selection_universe_integrity(
    tmp_path,
):
    connection = build_v7_database(
        tmp_path
    )

    try:
        columns = {
            row["name"]
            for row in connection.execute(
                """
                PRAGMA table_info(
                    research_runs
                );
                """
            )
        }

        assert (
            "selection_eligible_count"
            in columns
        )

        assert (
            "selection_exclusion_count"
            in columns
        )

        tables = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table';
                """
            )
        }

        assert (
            "selection_exclusions"
            in tables
        )

        integrity = (
            connection.execute(
                "PRAGMA integrity_check;"
            ).fetchone()[0]
        )

        assert integrity == "ok"

        foreign_keys = (
            connection.execute(
                "PRAGMA foreign_key_check;"
            ).fetchall()
        )

        assert foreign_keys == []

    finally:
        connection.close()


def test_selection_exclusion_must_belong_to_same_run(
    tmp_path,
):
    connection = build_v7_database(
        tmp_path
    )

    try:
        first_run = create_run(
            connection,
            suffix="one",
        )

        second_run = create_run(
            connection,
            suffix="two",
        )

        second_snapshot = create_snapshot(
            connection,
            run_id=second_run,
        )

        quote_id = create_quote(
            connection,
            snapshot_id=second_snapshot,
            symbol="O:OTHER",
        )

        with pytest.raises(
            sqlite3.IntegrityError,
            match=(
                "Selection exclusion must "
                "belong"
            ),
        ):
            connection.execute(
                """
                INSERT INTO selection_exclusions (
                    run_id,
                    snapshot_id,
                    option_quote_id,
                    provider,
                    underlying,
                    provider_contract_id,
                    option_symbol,
                    option_right,
                    strike,
                    expiration,
                    reason_code,
                    reason_detail,
                    excluded_at,
                    preregistration_hash,
                    code_git_sha
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    'MASSIVE',
                    'AAPL',
                    'O:OTHER',
                    'O:OTHER',
                    'C',
                    320,
                    '2026-09-11',
                    'MISSING_DELTA',
                    'test',
                    '2026-08-28T12:00:02Z',
                    'hash-one',
                    'sha-one'
                );
                """,
                (
                    first_run,
                    second_snapshot,
                    quote_id,
                ),
            )

    finally:
        connection.close()
