"""A failing market-data symbol cannot abort independent evidence from others."""
from datetime import datetime
from zoneinfo import ZoneInfo

from src.database.repository import get_connection
from src.research import independent_runner as runner
from src.research.deterministic_scanner import scan_research_run
from tests.test_independent_runner import FakeMassive, FakeTheta

NY = ZoneInfo("America/New_York")


def test_failed_underlying_partial_quotes_never_enter_scanner(db_path, monkeypatch):
    original = runner.collect_underlying

    def after_persist_failure(**kwargs):
        result = original(**kwargs)
        if kwargs["underlying"] == "AAPL":
            raise RuntimeError("synthetic failure after persisting some evidence")
        return result

    monkeypatch.setattr(runner, "collect_underlying", after_persist_failure)
    result = runner.run_independent_research(
        symbols=["AAPL", "MSFT"], massive_client=FakeMassive(),
        theta_client=FakeTheta(),
        observed_at=datetime(2026, 9, 4, 10, 0, 5, tzinfo=NY),
        observation_clock=lambda: datetime(2026, 9, 4, 10, 0, 5, tzinfo=NY),
        code_git_sha="test-sha", db_path=db_path,
        underlying_recovery_delay_seconds=0,
    )
    assert result.status == "COMPLETED"
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT succeeded_underlyings,failed_underlyings "
            "FROM research_runs WHERE id=?", (result.run_id,)
        ).fetchone()
        assert (row["succeeded_underlyings"], row["failed_underlyings"]) == (1, 1)
        # Immutable partial AAPL quotes exist but remain excluded downstream.
        assert conn.execute(
            "SELECT COUNT(*) FROM market_snapshots WHERE research_run_id=? "
            "AND underlying='AAPL'", (result.run_id,)
        ).fetchone()[0] > 0
    finally:
        conn.close()
    scan = scan_research_run(research_run_id=result.run_id, db_path=db_path)
    assert {obs.underlying for obs in scan.observations} == {"MSFT"}


def test_bare_timeout_is_safe_to_retry_once(db_path):
    class TimeoutOnce(FakeMassive):
        def __init__(self):
            self.calls = 0

        def get_option_chain(self, underlying, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("synthetic socket timeout")
            return super().get_option_chain(underlying, **kwargs)

    client = TimeoutOnce()
    result = runner.run_independent_research(
        symbols=["AAPL"], massive_client=client, theta_client=FakeTheta(),
        observed_at=datetime(2026, 9, 4, 10, 0, 5, tzinfo=NY),
        observation_clock=lambda: datetime(2026, 9, 4, 10, 0, 5, tzinfo=NY),
        code_git_sha="test-sha", db_path=db_path,
        underlying_recovery_delay_seconds=0,
    )
    assert result.status == "COMPLETED"
    assert client.calls == 2
