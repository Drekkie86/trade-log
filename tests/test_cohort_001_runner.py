from pathlib import Path
from types import SimpleNamespace
import sqlite3

from src.providers.saxo import (
    QuoteQuality,
)
from src.research.cohort_001_runner import (
    run_cohort_001_collection,
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


def build_database(
    tmp_path,
):
    db_path = (
        tmp_path
        / "cohort_runner.db"
    )

    schema = (
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
        schema
    )

    version = connection.execute(
        """
        SELECT version
        FROM schema_version;
        """
    ).fetchone()[0]

    if version == 6:
        migration = (
            PROJECT_ROOT
            / "migrations"
            / "007_selection_universe_integrity.sql"
        ).read_text(
            encoding="utf-8"
        )

        connection.executescript(
            migration
        )

    assert connection.execute(
        """
        SELECT version
        FROM schema_version;
        """
    ).fetchone()[0] == 7

    return connection


def make_payload():
    return {
        "request_id": "massive-1",
        "request_ids": [
            "massive-1",
        ],
        "reference_date": "2026-08-28",
        "pages_fetched": 1,
        "truncated": False,
        "results": [
            {
                "details": {
                    "ticker":
                        "O:AAPL260911C00340000",
                    "contract_type":
                        "call",
                    "strike_price":
                        340,
                    "expiration_date":
                        "2026-09-11",
                    "shares_per_contract":
                        100,
                },
                "implied_volatility":
                    0.24,
                "greeks": {
                    "gamma": 0.01,
                    "theta": -0.1,
                    "vega": 0.2,
                },
                "day": {
                    "volume": 4,
                },
                "open_interest":
                    100,
            },
            {
                "details": {
                    "ticker":
                        "O:AAPL260911C00320000",
                    "contract_type":
                        "call",
                    "strike_price":
                        320,
                    "expiration_date":
                        "2026-09-11",
                    "shares_per_contract":
                        100,
                },
                "implied_volatility":
                    0.25,
                "greeks": {
                    "delta": 0.15,
                    "gamma": 0.01,
                    "theta": -0.2,
                    "vega": 0.3,
                },
                "day": {
                    "volume": 10,
                },
                "open_interest":
                    1000,
            },
            {
                "details": {
                    "ticker":
                        "O:AAPL260911P00300000",
                    "contract_type":
                        "put",
                    "strike_price":
                        300,
                    "expiration_date":
                        "2026-09-11",
                    "shares_per_contract":
                        100,
                },
                "implied_volatility":
                    0.26,
                "greeks": {
                    "delta": -0.15,
                    "gamma": 0.01,
                    "theta": -0.2,
                    "vega": 0.3,
                },
                "day": {
                    "volume": 11,
                },
                "open_interest":
                    900,
            },
        ],
    }


class FakeMassiveClient:
    def __init__(
        self,
        payload=None,
        error=None,
    ):
        self.payload = (
            payload
            if payload is not None
            else make_payload()
        )
        self.error = error
        self.calls = []

    def get_option_chain(
        self,
        underlying,
        **kwargs,
    ):
        self.calls.append(
            (
                underlying,
                kwargs,
            )
        )

        if self.error is not None:
            raise self.error

        return self.payload


class FakeQuote:
    bid = 5.0
    ask = 5.2
    mid = 5.1
    computed_mid = 5.1
    bid_size = 10.0
    ask_size = 11.0
    delayed_by_minutes = 15
    market_state = "Open"
    price_source = "TEST"
    price_source_type = "Firm"
    price_type_bid = "Delayed"
    price_type_ask = "Delayed"
    last_updated = (
        "2026-08-28T13:30:00Z"
    )

    quality = QuoteQuality.DELAYED
    is_executable = False
    is_stale = False
    is_indicative = False
    is_delayed = True
    is_locked = False
    is_crossed = False


class FakeUnderlyingQuote:
    uic = 211
    asset_type = "Stock"
    bid = 314.5
    ask = 314.6
    mid = 314.55
    computed_mid = 314.55
    reference_price = 314.55
    bid_size = 100.0
    ask_size = 100.0
    delayed_by_minutes = 15
    market_state = "Open"
    price_source = "TEST"
    price_source_type = "Firm"
    price_type_bid = "Delayed"
    price_type_ask = "Delayed"
    last_updated = (
        "2026-08-28T13:30:00Z"
    )

    quality = QuoteQuality.DELAYED
    is_executable = False
    is_stale = False
    is_indicative = False
    is_delayed = True
    is_locked = False
    is_crossed = False


class FakeSaxoClient:
    def __init__(self):
        self.underlying_calls = 0
        self.underlying_symbols = []

    def get_underlying_quote_for_symbol(
        self,
        symbol,
    ):
        self.underlying_calls += 1
        self.underlying_symbols.append(
            symbol
        )
        return FakeUnderlyingQuote()


def fake_bridge(
    saxo_client,
    underlying,
    massive_quote,
):
    right = massive_quote["right"]

    contract = SimpleNamespace(
        uic=(
            1001
            if right == "C"
            else 1002
        ),
        option_root_id=309,
        underlying_uic=211,
        underlying=underlying,
        put_call=(
            "Call"
            if right == "C"
            else "Put"
        ),
        strike=(
            massive_quote["strike"]
        ),
        expiration=(
            massive_quote["expiration"]
        ),
        trading_status="Tradable",
        contract_size=100.0,
    )

    return SimpleNamespace(
        saxo_contract=contract,
        saxo_quote=FakeQuote(),
    )


def test_runner_freezes_before_saxo_and_completes(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    massive = FakeMassiveClient()
    saxo = FakeSaxoClient()

    try:
        result = (
            run_cohort_001_collection(
                conn=connection,
                massive_client=massive,
                saxo_client=saxo,
                preregistration_hash="hash",
                code_git_sha="sha",
                us_session_date="2026-08-28",
                us_session_state="INTRADAY",
                started_at=(
                    "2026-08-28T13:31:00Z"
                ),
                bridge_func=fake_bridge,
            )
        )

        assert result.status == "COMPLETED"
        assert (
            result.selected_contract_count
            == 2
        )
        exclusions = connection.execute(
            """
            SELECT *
            FROM selection_exclusions
            WHERE run_id = ?;
            """,
            (result.run_id,),
        ).fetchall()

        assert len(exclusions) == 1
        assert (
            exclusions[0]["reason_code"]
            == "MISSING_DELTA"
        )
        assert (
            result.saxo_resolution_success_count
            == 2
        )
        assert (
            result.saxo_resolution_failure_count
            == 0
        )

        run = connection.execute(
            """
            SELECT *
            FROM research_runs
            WHERE id = ?;
            """,
            (result.run_id,),
        ).fetchone()

        assert run["status"] == "COMPLETED"
        assert (
            run["selected_contract_count"]
            == 2
        )
        assert (
            run["massive_normalized_contracts"]
            == 3
        )
        assert (
            run["selection_eligible_count"]
            == 2
        )
        assert (
            run["selection_exclusion_count"]
            == 1
        )
        assert (
            run["underlying_observation_status"]
            == "SUCCESS"
        )
        assert saxo.underlying_calls == 1
        assert saxo.underlying_symbols == [
            "AAPL"
        ]

        selections = connection.execute(
            """
            SELECT *
            FROM research_selections
            WHERE run_id = ?
            ORDER BY resolution_sequence;
            """,
            (result.run_id,),
        ).fetchall()

        assert len(selections) == 2

        observations = connection.execute(
            """
            SELECT *
            FROM saxo_option_observations
            ORDER BY resolution_sequence;
            """
        ).fetchall()

        assert len(observations) == 2

        assert {
            row["resolution_sequence"]
            for row in observations
        } == {
            1,
            2,
        }

        model_rows = connection.execute(
            """
            SELECT *
            FROM provider_model_observations;
            """
        ).fetchall()

        assert len(model_rows) == 3

        quote_model_values = connection.execute(
            """
            SELECT
                implied_volatility,
                delta,
                gamma,
                theta,
                vega,
                iv_source,
                delta_source
            FROM option_quotes;
            """
        ).fetchall()

        assert all(
            row["implied_volatility"]
            is None
            for row in quote_model_values
        )

        assert all(
            row["delta"] is None
            for row in quote_model_values
        )

        assert all(
            row["iv_source"] == "UNKNOWN"
            for row in quote_model_values
        )

        assert all(
            row["delta_source"] == "UNKNOWN"
            for row in quote_model_values
        )

    finally:
        connection.close()


def test_massive_failure_terminalizes_without_saxo(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    massive = FakeMassiveClient(
        error=RuntimeError(
            "Massive unavailable"
        )
    )

    saxo = FakeSaxoClient()

    bridge_calls = []

    def should_not_bridge(
        *args,
        **kwargs,
    ):
        bridge_calls.append(
            (args, kwargs)
        )
        raise AssertionError(
            "Saxo should not be reached."
        )

    try:
        result = (
            run_cohort_001_collection(
                conn=connection,
                massive_client=massive,
                saxo_client=saxo,
                preregistration_hash="hash",
                code_git_sha="sha",
                us_session_date="2026-08-28",
                us_session_state="INTRADAY",
                started_at=(
                    "2026-08-28T13:31:00Z"
                ),
                bridge_func=(
                    should_not_bridge
                ),
            )
        )

        assert result.status == "FAILED"
        assert bridge_calls == []

        run = connection.execute(
            """
            SELECT *
            FROM research_runs
            WHERE id = ?;
            """,
            (result.run_id,),
        ).fetchone()

        assert run["status"] == "FAILED"
        assert (
            run["failed_underlyings"]
            == 1
        )
        assert (
            run["provider_requests_failed"]
            == 1
        )

    finally:
        connection.close()


def test_saxo_failure_stays_in_denominator(
    tmp_path,
):
    connection = build_database(
        tmp_path
    )

    massive = FakeMassiveClient()
    saxo = FakeSaxoClient()

    calls = 0

    def one_fails(
        saxo_client,
        underlying,
        massive_quote,
    ):
        nonlocal calls
        calls += 1

        if calls == 1:
            raise RuntimeError(
                "resolution failed"
            )

        return fake_bridge(
            saxo_client,
            underlying,
            massive_quote,
        )

    try:
        result = (
            run_cohort_001_collection(
                conn=connection,
                massive_client=massive,
                saxo_client=saxo,
                preregistration_hash="hash",
                code_git_sha="sha",
                us_session_date="2026-08-28",
                us_session_state="INTRADAY",
                started_at=(
                    "2026-08-28T13:31:00Z"
                ),
                bridge_func=one_fails,
            )
        )

        assert (
            result.selected_contract_count
            == 2
        )
        assert (
            result.saxo_resolution_success_count
            == 1
        )
        assert (
            result.saxo_resolution_failure_count
            == 1
        )

        selections = connection.execute(
            """
            SELECT COUNT(*)
            FROM research_selections
            WHERE run_id = ?;
            """,
            (result.run_id,),
        ).fetchone()[0]

        failures = connection.execute(
            """
            SELECT COUNT(*)
            FROM saxo_resolution_failures;
            """
        ).fetchone()[0]

        successes = connection.execute(
            """
            SELECT COUNT(*)
            FROM saxo_option_observations;
            """
        ).fetchone()[0]

        assert selections == 2
        assert failures == 1
        assert successes == 1

    finally:
        connection.close()
