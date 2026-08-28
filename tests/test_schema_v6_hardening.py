from pathlib import Path
import sqlite3


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


def build_v6_database(
    tmp_path,
):
    db_path = (
        tmp_path
        / "christiania_v6.db"
    )

    schema_sql = (
        PROJECT_ROOT
        / "trade_log_schema.sql"
    ).read_text(
        encoding="utf-8"
    )

    migration_005 = (
        PROJECT_ROOT
        / "migrations"
        / "005_provider_evidence_hardening.sql"
    ).read_text(
        encoding="utf-8"
    )

    migration_006 = (
        PROJECT_ROOT
        / "migrations"
        / "006_cohort_research_integrity.sql"
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
        schema_sql
    )

    connection.executescript(
        migration_005
    )

    connection.executescript(
        migration_006
    )

    connection.commit()

    return connection


def test_schema_reaches_v6(
    tmp_path,
):
    connection = build_v6_database(
        tmp_path
    )

    try:
        version = connection.execute(
            """
            SELECT version
            FROM schema_version
            ORDER BY version DESC
            LIMIT 1;
            """
        ).fetchone()["version"]

        assert version == 6

    finally:
        connection.close()


def test_v6_research_tables_exist(
    tmp_path,
):
    connection = build_v6_database(
        tmp_path
    )

    try:
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

        expected = {
            "research_runs",
            "research_run_underlyings",
            "research_provider_attempts",
            "normalization_drops",
            "research_selections",
        }

        assert expected <= tables

    finally:
        connection.close()


def test_option_dates_exist(
    tmp_path,
):
    connection = build_v6_database(
        tmp_path
    )

    try:
        columns = {
            row["name"]
            for row in connection.execute(
                """
                PRAGMA table_info(
                    option_quotes
                );
                """
            )
        }

        assert (
            "open_interest_as_of_date"
            in columns
        )

        assert (
            "volume_trading_date"
            in columns
        )

    finally:
        connection.close()


def test_quote_classifier_fields_exist(
    tmp_path,
):
    connection = build_v6_database(
        tmp_path
    )

    try:
        option_columns = {
            row["name"]
            for row in connection.execute(
                """
                PRAGMA table_info(
                    saxo_option_observations
                );
                """
            )
        }

        expected = {
            "quote_quality_version",
            "is_stale",
            "is_indicative",
            "is_delayed",
            "is_locked",
            "is_crossed",
            "observation_gap_seconds",
            "retry_count",
            "resolution_sequence",
        }

        assert expected <= option_columns

    finally:
        connection.close()


def test_selection_requires_same_run_snapshot(
    tmp_path,
):
    connection = build_v6_database(
        tmp_path
    )

    try:
        run_id = connection.execute(
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
                'hash',
                'sha',
                '2026-08-28T00:00:00Z',
                '2026-08-27',
                'POST_CLOSE',
                'STARTED'
            );
            """
        ).lastrowid

        snapshot_id = connection.execute(
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
                '2026-08-28T00:00:01Z',
                'AAPL',
                'MASSIVE',
                NULL,
                'UNKNOWN',
                NULL,
                'UNKNOWN',
                ?,
                '2026-08-27',
                'POST_CLOSE'
            );
            """,
            (run_id,),
        ).lastrowid

        quote_id = connection.execute(
            """
            INSERT INTO option_quotes (
                snapshot_id,
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
                ?,
                'O:AAPL260918C00320000',
                'C',
                320,
                '2026-09-18',

                NULL,
                'UNKNOWN',

                NULL,
                'UNKNOWN',

                NULL,
                'UNKNOWN',

                NULL,
                'UNKNOWN',

                NULL,
                'UNKNOWN',

                NULL,
                'UNKNOWN',

                NULL,
                'UNKNOWN',

                NULL,
                'UNKNOWN',

                NULL,
                'UNKNOWN',

                NULL,
                'UNKNOWN'
            );
            """,
            (snapshot_id,),
        ).lastrowid

        connection.execute(
            """
            INSERT INTO research_selections (
                run_id,
                option_quote_id,
                selected_at,
                selection_rule,
                dte_stratum,
                delta_stratum,
                option_right,
                resolution_sequence,
                preregistration_hash,
                code_git_sha
            )
            VALUES (
                ?,
                ?,
                '2026-08-28T00:00:02Z',
                'BASELINE_STRATIFIED_SAMPLE_V1',
                '15-30',
                '0.35-0.50',
                'C',
                1,
                'hash',
                'sha'
            );
            """,
            (
                run_id,
                quote_id,
            ),
        )

        row = connection.execute(
            """
            SELECT resolution_sequence
            FROM research_selections
            WHERE run_id = ?;
            """,
            (run_id,),
        ).fetchone()

        assert (
            row["resolution_sequence"]
            == 1
        )

    finally:
        connection.close()


def test_terminal_run_is_immutable(
    tmp_path,
):
    connection = build_v6_database(
        tmp_path
    )

    try:
        run_id = connection.execute(
            """
            INSERT INTO research_runs (
                cohort_id,
                preregistration_hash,
                code_git_sha,
                started_at,
                ended_at,
                us_session_date,
                us_session_state,
                status
            )
            VALUES (
                'COHORT_001_DATA_QUALITY_BASELINE',
                'hash',
                'sha',
                '2026-08-28T00:00:00Z',
                '2026-08-28T00:10:00Z',
                '2026-08-27',
                'POST_CLOSE',
                'COMPLETED'
            );
            """
        ).lastrowid

        try:
            connection.execute(
                """
                UPDATE research_runs
                SET notes = 'changed'
                WHERE id = ?;
                """,
                (run_id,),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError(
                "Terminal run unexpectedly "
                "remained mutable."
            )

    finally:
        connection.close()
