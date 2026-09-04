from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.database.repository import (
    get_connection,
)
from src.providers.massive import MassiveNetworkError
from src.research.independent_runner import (
    classify_us_session,
    config_hash,
    normalized_run_config,
    run_independent_research,
)

NY = ZoneInfo("America/New_York")


class FakeMassive:
    def get_option_contracts_reference(
        self,
        underlying,
        **kwargs,
    ):
        return {
            "results": [
                {
                    "ticker":
                        f"O:{underlying}260918C00100000",
                    "underlying_ticker":
                        underlying,
                    "expiration_date":
                        "2026-09-18",
                    "strike_price":
                        100.0,
                    "contract_type":
                        "call",
                    "exercise_style":
                        "american",
                    "shares_per_contract":
                        100,
                }
            ],
            "pages_fetched": 1,
            "truncated": False,
        }

    def get_option_chain(
        self,
        underlying,
        **kwargs,
    ):
        return {
            "results": [
                {
                    "details": {
                        "ticker":
                            f"O:{underlying}260918C00100000",
                        "expiration_date":
                            "2026-09-18",
                        "strike_price":
                            100.0,
                        "contract_type":
                            "call",
                    }
                }
            ],
            "pages_fetched": 1,
            "truncated": False,
        }


class FakeTheta:
    def _get_payload(
        self,
        path,
        params,
    ):
        symbol = params["symbol"]

        if path.endswith("/quote"):
            return {
                "response": [
                    {
                        "contract": {
                            "symbol":
                                symbol,
                            "expiration":
                                "2026-09-18",
                            "strike":
                                100.0,
                            "right":
                                "CALL",
                        },
                        "data": [
                            {
                                "bid":
                                    5.0,
                                "ask":
                                    5.2,
                                "timestamp":
                                    "2026-08-31T14:00:00",
                            }
                        ],
                    }
                ]
            }

        return {
            "response": [
                {
                    "contract": {
                        "symbol":
                            symbol,
                        "expiration":
                            "2026-09-18",
                        "strike":
                            100.0,
                        "right":
                            "CALL",
                    },
                    "data": [
                        {
                            "delta":
                                0.50,
                            "theta":
                                -0.05,
                            "vega":
                                0.10,
                            "implied_vol":
                                0.25,
                            "iv_error":
                                0.001,
                            "timestamp":
                                "2026-08-31T14:00:00",
                            "underlying_price":
                                101.0,
                        }
                    ],
                }
            ]
        }


def test_session_classifier():
    assert classify_us_session(
        datetime(
            2026, 8, 31, 8, 0,
            tzinfo=NY,
        )
    ) == "PRE_OPEN"

    assert classify_us_session(
        datetime(
            2026, 8, 31, 14, 0,
            tzinfo=NY,
        )
    ) == "INTRADAY"

    assert classify_us_session(
        datetime(
            2026, 8, 31, 17, 0,
            tzinfo=NY,
        )
    ) == "POST_CLOSE"


def test_run_config_is_deterministic():
    first = normalized_run_config(
        symbols=["XOM", "AAPL", "AAPL"],
        min_dte=7,
        max_dte=45,
    )

    second = normalized_run_config(
        symbols=["AAPL", "XOM"],
        min_dte=7,
        max_dte=45,
    )

    assert first == second
    assert config_hash(first) == (
        config_hash(second)
    )


def test_independent_runner_persists_research_evidence(
    db_path,
):
    result = run_independent_research(
        symbols=["AAPL"],
        massive_client=FakeMassive(),
        theta_client=FakeTheta(),
        min_dte=7,
        max_dte=45,
        observed_at=datetime(
            2026,
            8,
            31,
            14,
            0,
            5,
            tzinfo=NY,
        ),
        observation_clock=lambda: datetime(
            2026,
            8,
            31,
            14,
            0,
            5,
            tzinfo=NY,
        ),
        repo_root=Path("."),
        code_git_sha="test-sha",
        db_path=db_path,
    )

    assert result.status == "COMPLETED"
    assert len(result.summaries) == 1

    summary = result.summaries[0]

    assert summary.reference_contracts == 1
    assert summary.theta_quote_rows == 1
    assert summary.theta_greek_rows == 1
    assert summary.structurally_ready == 1

    conn = get_connection(db_path)
    try:
        run = conn.execute(
            """
            SELECT *
            FROM research_runs
            WHERE id = ?;
            """,
            (result.run_id,),
        ).fetchone()

        assert run["status"] == "COMPLETED"
        assert run["attempted_underlyings"] == 1
        assert run["succeeded_underlyings"] == 1

        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM listing_reference_contracts
            WHERE research_run_id = ?;
            """,
            (result.run_id,),
        ).fetchone()[0] == 1

        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM provider_observation_availability
            WHERE reference_contract_id IN (
                SELECT id
                FROM listing_reference_contracts
                WHERE research_run_id = ?
            );
            """,
            (result.run_id,),
        ).fetchone()[0] == 3

        snapshot = conn.execute(
            """
            SELECT id
            FROM market_snapshots
            WHERE research_run_id = ?
              AND provider = 'THETADATA';
            """,
            (result.run_id,),
        ).fetchone()

        assert snapshot is not None

        quote = conn.execute(
            """
            SELECT id, bid, ask
            FROM option_quotes
            WHERE snapshot_id = ?;
            """,
            (snapshot["id"],),
        ).fetchone()

        assert quote["bid"] == 5.0
        assert quote["ask"] == 5.2

        model = conn.execute(
            """
            SELECT *
            FROM provider_model_observations
            WHERE option_quote_id = ?;
            """,
            (quote["id"],),
        ).fetchone()

        assert model["delta"] == 0.50
        assert model["implied_volatility"] == 0.25
    finally:
        conn.close()


def test_runner_failure_is_recorded(
    db_path,
):
    class BrokenMassive(FakeMassive):
        def get_option_chain(
            self,
            underlying,
            **kwargs,
        ):
            raise RuntimeError(
                "synthetic provider failure"
            )

    import pytest

    with pytest.raises(
        RuntimeError,
        match="synthetic provider failure",
    ):
        run_independent_research(
            symbols=["AAPL"],
            massive_client=BrokenMassive(),
            theta_client=FakeTheta(),
            observed_at=datetime(
                2026,
                8,
                31,
                14,
                0,
                5,
                tzinfo=NY,
            ),
            code_git_sha="test-sha",
            db_path=db_path,
        )

    conn = get_connection(db_path)
    try:
        run = conn.execute(
            """
            SELECT *
            FROM research_runs
            ORDER BY id DESC
            LIMIT 1;
            """
        ).fetchone()

        assert run["status"] == "FAILED"
        assert run["failed_underlyings"] == 1
    finally:
        conn.close()



def test_transient_massive_failure_recovers_same_underlying(db_path):
    class FlakyMassive(FakeMassive):
        def __init__(self):
            self.chain_calls = 0
        def get_option_chain(self, underlying, **kwargs):
            self.chain_calls += 1
            if self.chain_calls == 1:
                raise MassiveNetworkError("Could not reach Massive after retries.")
            return super().get_option_chain(underlying, **kwargs)

    massive = FlakyMassive()
    result = run_independent_research(
        symbols=["AAPL"],
        massive_client=massive,
        theta_client=FakeTheta(),
        observed_at=datetime(2026, 9, 4, 10, 0, 5, tzinfo=NY),
        observation_clock=lambda: datetime(2026, 9, 4, 10, 0, 5, tzinfo=NY),
        code_git_sha="test-sha",
        db_path=db_path,
        underlying_recovery_delay_seconds=0,
    )
    assert result.status == "COMPLETED"
    assert massive.chain_calls == 2

    conn = get_connection(db_path)
    try:
        run_row = conn.execute(
            "SELECT * FROM research_runs WHERE id = ?;", (result.run_id,)
        ).fetchone()
        child = conn.execute(
            "SELECT * FROM research_run_underlyings WHERE run_id = ? AND underlying = 'AAPL';",
            (result.run_id,),
        ).fetchone()
        assert run_row["attempted_underlyings"] == 1
        assert run_row["succeeded_underlyings"] == 1
        assert run_row["failed_underlyings"] == 0
        assert child["status"] == "SUCCESS"
        assert child["retry_count"] == 1
        assert "immediate recovery after MassiveNetworkError" in run_row["notes"]
        assert "recovered successfully after 1" in run_row["notes"]
        assert conn.execute(
            "SELECT COUNT(*) FROM listing_reference_contracts WHERE research_run_id = ?;",
            (result.run_id,),
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_non_transient_failure_is_not_retried(db_path):
    class BrokenMassive(FakeMassive):
        def __init__(self):
            self.chain_calls = 0
        def get_option_chain(self, underlying, **kwargs):
            self.chain_calls += 1
            raise RuntimeError("synthetic programming failure")

    import pytest
    massive = BrokenMassive()
    with pytest.raises(RuntimeError, match="synthetic programming failure"):
        run_independent_research(
            symbols=["AAPL"],
            massive_client=massive,
            theta_client=FakeTheta(),
            observed_at=datetime(2026, 9, 4, 10, 0, 5, tzinfo=NY),
            code_git_sha="test-sha",
            db_path=db_path,
            underlying_recovery_delay_seconds=0,
        )
    assert massive.chain_calls == 1
