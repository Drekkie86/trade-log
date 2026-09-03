from pathlib import Path
import sqlite3

import pytest

from src.database.provider_evidence import (
    create_provider_model_observation,
    create_provider_model_observations,
    create_saxo_option_observation,
    create_saxo_resolution_failure,
    create_saxo_underlying_observation,
)
from src.providers.saxo import (
    SaxoOptionContract,
    SaxoOptionQuote,
    SaxoUnderlyingQuote,
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


def make_v6_database(
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

    connection.commit()

    return (
        db_path,
        connection,
    )


def create_source_quote(
    connection,
):
    snapshot_cursor = (
        connection.execute(
            """
            INSERT INTO market_snapshots (
                captured_at,
                underlying,
                provider,
                provider_snapshot_id,
                underlying_price,
                underlying_source,
                underlying_at,
                fx_to_eur,
                fx_source,
                fx_at,
                notes
            )
            VALUES (
                '2026-08-27T21:50:00Z',
                'AAPL',
                'MASSIVE',
                'request-1',
                NULL,
                'UNKNOWN',
                NULL,
                NULL,
                'UNKNOWN',
                NULL,
                'test'
            );
            """
        )
    )

    snapshot_id = (
        snapshot_cursor.lastrowid
    )

    quote_cursor = (
        connection.execute(
            """
            INSERT INTO option_quotes (
                snapshot_id,
                provider_contract_id,
                option_symbol,
                right,
                strike,
                expiration,
                quote_at,

                bid,
                bid_source,
                bid_at,

                ask,
                ask_source,
                ask_at,

                last,
                last_source,
                last_at,

                implied_volatility,
                iv_source,
                iv_at,

                delta,
                delta_source,
                delta_at,

                gamma,
                gamma_source,
                gamma_at,

                theta,
                theta_source,
                theta_at,

                vega,
                vega_source,
                vega_at,

                volume,
                volume_source,
                volume_at,

                open_interest,
                open_interest_source,
                open_interest_at,

                shares_per_contract
            )
            VALUES (
                ?,
                'O:AAPL260918C00320000',
                'O:AAPL260918C00320000',
                'C',
                320.0,
                '2026-09-18',
                NULL,

                NULL,
                'UNKNOWN',
                NULL,

                NULL,
                'UNKNOWN',
                NULL,

                NULL,
                'UNKNOWN',
                NULL,

                0.25,
                'DERIVED',
                NULL,

                0.41,
                'DERIVED',
                NULL,

                0.01,
                'DERIVED',
                NULL,

                -0.20,
                'DERIVED',
                NULL,

                0.30,
                'DERIVED',
                NULL,

                100,
                'FETCHED',
                NULL,

                35202,
                'FETCHED',
                NULL,

                100
            );
            """,
            (
                snapshot_id,
            ),
        )
    )

    connection.commit()

    return (
        snapshot_id,
        quote_cursor.lastrowid,
    )


def make_option_contract():
    return SaxoOptionContract(
        uic=49379211,
        option_root_id=309,
        underlying_uic=211,
        underlying="AAPL",
        put_call="Call",
        strike=320.0,
        expiration="2026-09-18",
        trading_status="Tradable",
        contract_size=100.0,
    )


def make_option_quote():
    return SaxoOptionQuote(
        uic=49379211,
        bid=5.40,
        ask=5.55,
        mid=5.475,
        bid_size=0.0,
        ask_size=0.0,
        delayed_by_minutes=15,
        market_state="Closed",
        price_source="OPRA",
        price_source_type="Firm",
        price_type_bid="OldIndicative",
        price_type_ask="OldIndicative",
        last_updated=(
            "2026-08-27"
            "T21:50:35.632000Z"
        ),
    )


def make_underlying_quote():
    return SaxoUnderlyingQuote(
        uic=211,
        asset_type="Stock",
        bid=314.54,
        ask=314.55,
        mid=314.55,
        bid_size=0.0,
        ask_size=0.0,
        delayed_by_minutes=15,
        market_state="Closed",
        price_source="TVIEWNASD",
        price_source_type="Indicative",
        price_type_bid="OldIndicative",
        price_type_ask="OldIndicative",
        last_updated=(
            "2026-08-27"
            "T21:55:39.638000Z"
        ),
    )


def test_provider_model_observation(
    tmp_path,
):
    _, connection = (
        make_v6_database(
            tmp_path
        )
    )

    try:
        _, quote_id = (
            create_source_quote(
                connection
            )
        )

        observation_id = (
            create_provider_model_observation(
                option_quote_id=quote_id,
                provider="MASSIVE",
                implied_volatility=0.25,
                delta=0.41,
                gamma=0.01,
                theta=-0.20,
                vega=0.30,
                ingested_at=(
                    "2026-08-27"
                    "T21:50:40Z"
                ),
                model_underlying_price=None,
                model_rate=None,
                conn=connection,
            )
        )

        row = connection.execute(
            """
            SELECT *
            FROM provider_model_observations
            WHERE id = ?;
            """,
            (
                observation_id,
            ),
        ).fetchone()

        assert row is not None

        assert (
            row["source"]
            == "PROVIDER_DERIVED"
        )

        assert (
            row["provider"]
            == "MASSIVE"
        )

        assert (
            row["observed_at"]
            is None
        )

        assert (
            row["model_underlying_price"]
            is None
        )

    finally:
        connection.close()


def test_saxo_option_observation(
    tmp_path,
):
    _, connection = (
        make_v6_database(
            tmp_path
        )
    )

    try:
        _, quote_id = (
            create_source_quote(
                connection
            )
        )

        observation_id = (
            create_saxo_option_observation(
                option_quote_id=quote_id,
                contract=(
                    make_option_contract()
                ),
                quote=(
                    make_option_quote()
                ),
                source_snapshot_captured_at=(
                    "2026-08-27"
                    "T21:50:00Z"
                ),
                ingested_at=(
                    "2026-08-27"
                    "T21:51:00Z"
                ),
                retry_count=2,
                resolution_sequence=4,
                conn=connection,
            )
        )

        row = connection.execute(
            """
            SELECT *
            FROM saxo_option_observations
            WHERE id = ?;
            """,
            (
                observation_id,
            ),
        ).fetchone()

        assert (
            row["quote_quality"]
            == "STALE"
        )

        assert (
            row["quote_quality_version"]
            == "SAXO_QUOTE_CLASSIFIER_V1"
        )

        assert row["is_stale"] == 1
        assert row["is_delayed"] == 1
        assert row["is_executable"] == 0

        assert (
            row["contract_size"]
            == 100.0
        )

        assert (
            row["ingestion_gap_seconds"]
            == pytest.approx(
                60.0
            )
        )

        assert (
            row["observation_gap_seconds"]
            is None
        )

        assert row["retry_count"] == 2
        assert row["resolution_sequence"] == 4

    finally:
        connection.close()


def test_saxo_underlying_observation(
    tmp_path,
):
    _, connection = (
        make_v6_database(
            tmp_path
        )
    )

    try:
        snapshot_id, _ = (
            create_source_quote(
                connection
            )
        )

        observation_id = (
            create_saxo_underlying_observation(
                research_snapshot_id=(
                    snapshot_id
                ),
                underlying="AAPL",
                quote=(
                    make_underlying_quote()
                ),
                source_snapshot_captured_at=(
                    "2026-08-27"
                    "T21:50:00Z"
                ),
                ingested_at=(
                    "2026-08-27"
                    "T21:56:00Z"
                ),
                retry_count=1,
                conn=connection,
            )
        )

        row = connection.execute(
            """
            SELECT *
            FROM saxo_underlying_observations
            WHERE id = ?;
            """,
            (
                observation_id,
            ),
        ).fetchone()

        assert (
            row["reference_price"]
            == pytest.approx(
                314.545
            )
        )

        assert (
            row["quote_quality"]
            == "STALE"
        )

        assert row["is_stale"] == 1
        assert row["is_indicative"] == 1
        assert row["is_delayed"] == 1
        assert row["is_executable"] == 0

        assert (
            row["ingestion_gap_seconds"]
            == pytest.approx(
                360.0
            )
        )

        assert (
            row["observation_gap_seconds"]
            is None
        )

        assert row["retry_count"] == 1

    finally:
        connection.close()


def test_resolution_failure_is_persisted(
    tmp_path,
):
    _, connection = (
        make_v6_database(
            tmp_path
        )
    )

    try:
        (
            snapshot_id,
            quote_id,
        ) = create_source_quote(
            connection
        )

        failure_id = (
            create_saxo_resolution_failure(
                research_snapshot_id=(
                    snapshot_id
                ),
                option_quote_id=(
                    quote_id
                ),
                underlying="AAPL",
                provider_contract_id=(
                    "O:AAPL260918"
                    "C00320000"
                ),
                option_symbol=(
                    "O:AAPL260918"
                    "C00320000"
                ),
                right="C",
                strike=320,
                expiration="2026-09-18",
                shares_per_contract=100,
                failure_stage=(
                    "CONTRACT_RESOLUTION"
                ),
                failure_code=(
                    "NO_MATCH"
                ),
                failure_reason=(
                    "No matching Saxo "
                    "contract."
                ),
                attempted_at=(
                    "2026-08-27"
                    "T21:51:00Z"
                ),
                retry_count=3,
                resolution_sequence=7,
                conn=connection,
            )
        )

        row = connection.execute(
            """
            SELECT *
            FROM saxo_resolution_failures
            WHERE id = ?;
            """,
            (
                failure_id,
            ),
        ).fetchone()

        assert (
            row["failure_stage"]
            == "CONTRACT_RESOLUTION"
        )

        assert row["retry_count"] == 3
        assert row["resolution_sequence"] == 7

    finally:
        connection.close()


def test_saxo_option_identity_mismatch_is_rejected(
    tmp_path,
):
    _, connection = (
        make_v6_database(
            tmp_path
        )
    )

    try:
        _, quote_id = (
            create_source_quote(
                connection
            )
        )

        bad_contract = (
            SaxoOptionContract(
                uic=999,
                option_root_id=309,
                underlying_uic=211,
                underlying="AAPL",
                put_call="Call",
                strike=321.0,
                expiration="2026-09-18",
                trading_status="Tradable",
                contract_size=100.0,
            )
        )

        with pytest.raises(
            sqlite3.IntegrityError,
            match=(
                "contract identity "
                "does not match"
            ),
        ):
            create_saxo_option_observation(
                option_quote_id=quote_id,
                contract=bad_contract,
                quote=(
                    make_option_quote()
                ),
                source_snapshot_captured_at=(
                    "2026-08-27"
                    "T21:50:00Z"
                ),
                conn=connection,
            )

    finally:
        connection.close()


def test_provider_evidence_is_immutable(
    tmp_path,
):
    _, connection = (
        make_v6_database(
            tmp_path
        )
    )

    try:
        _, quote_id = (
            create_source_quote(
                connection
            )
        )

        observation_id = (
            create_provider_model_observation(
                option_quote_id=quote_id,
                provider="MASSIVE",
                delta=0.41,
                conn=connection,
            )
        )

        with pytest.raises(
            sqlite3.IntegrityError,
            match="immutable",
        ):
            connection.execute(
                """
                UPDATE provider_model_observations
                SET delta = 0.99
                WHERE id = ?;
                """,
                (
                    observation_id,
                ),
            )

    finally:
        connection.close()



def test_provider_model_observation_batch_matches_single_semantics(
    tmp_path,
):
    _, connection = make_v6_database(
        tmp_path
    )

    try:
        _, quote_id = create_source_quote(
            connection
        )

        written = create_provider_model_observations(
            [
                {
                    "option_quote_id": quote_id,
                    "provider": "THETADATA",
                    "implied_volatility": 0.25,
                    "delta": 0.41,
                    "theta": -0.20,
                    "vega": 0.30,
                    "ingested_at": "2026-08-27T21:50:40Z",
                    "observed_at": "2026-08-27T21:50:35Z",
                    "model_name": "ThetaData first_order snapshot",
                },
                {
                    "option_quote_id": quote_id,
                    "provider": "THETADATA",
                    "implied_volatility": 0.26,
                    "delta": 0.42,
                    "theta": -0.21,
                    "vega": 0.31,
                    "ingested_at": "2026-08-27T21:50:41Z",
                    "observed_at": "2026-08-27T21:50:36Z",
                    "model_name": "ThetaData first_order snapshot",
                },
            ],
            conn=connection,
        )

        assert written == 2

        rows = connection.execute(
            """
            SELECT provider, source, implied_volatility, delta,
                   theta, vega, observed_at, model_name
            FROM provider_model_observations
            WHERE option_quote_id = ?
              AND provider = 'THETADATA'
            ORDER BY id;
            """,
            (quote_id,),
        ).fetchall()

        assert len(rows) == 2
        assert rows[0]["source"] == "PROVIDER_DERIVED"
        assert rows[0]["implied_volatility"] == 0.25
        assert rows[1]["implied_volatility"] == 0.26
        assert rows[1]["delta"] == 0.42
    finally:
        connection.close()


def test_provider_model_observation_batch_rejects_empty_model_values(
    tmp_path,
):
    _, connection = make_v6_database(
        tmp_path
    )

    try:
        _, quote_id = create_source_quote(
            connection
        )

        with pytest.raises(
            ValueError,
            match="requires at least one model value",
        ):
            create_provider_model_observations(
                [
                    {
                        "option_quote_id": quote_id,
                        "provider": "THETADATA",
                    }
                ],
                conn=connection,
            )
    finally:
        connection.close()


def test_provider_model_observation_batch_uses_one_transaction(
    monkeypatch,
):
    from contextlib import contextmanager

    import src.database.provider_evidence as provider_module

    calls = {
        "transactions": 0,
        "executemany": 0,
        "row_count": 0,
    }

    class FakeConnection:
        def executemany(self, sql, rows):
            calls["executemany"] += 1
            calls["row_count"] = len(rows)

    @contextmanager
    def fake_transaction(*, db_path=None, conn=None):
        calls["transactions"] += 1
        yield FakeConnection()

    monkeypatch.setattr(
        provider_module,
        "transaction",
        fake_transaction,
    )

    rows = [
        {
            "option_quote_id": index + 1,
            "provider": "THETADATA",
            "implied_volatility": 0.25,
            "delta": 0.5,
        }
        for index in range(1000)
    ]

    assert create_provider_model_observations(
        rows
    ) == 1000
    assert calls == {
        "transactions": 1,
        "executemany": 1,
        "row_count": 1000,
    }


def test_provider_model_observation_persists_v18_timing_fields(db_path):
    from src.database.repository import get_connection

    conn = get_connection(db_path)
    try:
        run_id = int(conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id, started_at, code_git_sha, preregistration_hash,
                us_session_date, us_session_state, status
            ) VALUES ('TIMING_TEST', '2026-09-03T18:00:00Z', 'sha', 'hash',
                      '2026-09-03', 'INTRADAY', 'STARTED');
            """
        ).lastrowid)
        snapshot_id = int(conn.execute(
            """
            INSERT INTO market_snapshots (
                captured_at, underlying, provider, underlying_source,
                fx_source, research_run_id, us_session_date, us_session_state
            ) VALUES ('2026-09-03T18:00:00Z', 'AAPL', 'THETADATA', 'UNKNOWN',
                      'UNKNOWN', ?, '2026-09-03', 'INTRADAY');
            """,
            (run_id,),
        ).lastrowid)
        quote_id = int(conn.execute(
            """
            INSERT INTO option_quotes (
                snapshot_id, right, strike, expiration,
                bid_source, ask_source, last_source, iv_source, delta_source,
                gamma_source, theta_source, vega_source, volume_source,
                open_interest_source
            ) VALUES (?, 'C', 250, '2026-09-11', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN',
                      'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN',
                      'UNKNOWN', 'UNKNOWN');
            """,
            (snapshot_id,),
        ).lastrowid)

        observation_id = create_provider_model_observation(
            option_quote_id=quote_id,
            provider="THETADATA",
            delta=0.5,
            timing_diagnostic_version="THETADATA_TIMING_DIAGNOSTIC_V1",
            greek_age_seconds=1.5,
            quote_greek_skew_seconds=-0.25,
            underlying_greek_skew_seconds=0.75,
            conn=conn,
        )
        row = conn.execute(
            "SELECT * FROM provider_model_observations WHERE id = ?;",
            (observation_id,),
        ).fetchone()
        assert row["greek_age_seconds"] == 1.5
        assert row["quote_greek_skew_seconds"] == -0.25
        assert row["underlying_greek_skew_seconds"] == 0.75
    finally:
        conn.close()
