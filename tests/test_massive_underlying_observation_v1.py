"""Protect independent real-market spot lineage from model-input leakage."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.database.repository import get_connection
from src.research.independent_runner import run_independent_research
from src.research.massive_underlying_observation_v1 import (
    MAX_AGE_SECONDS, extract_massive_underlying_observation,
)
from tests.test_independent_runner import FakeMassive, FakeTheta

CUT = datetime(2026, 8, 31, 18, 0, 5, tzinfo=timezone.utc)


def row(symbol: str, price: float, at: datetime) -> dict:
    return {"underlying_asset": {
        "ticker": symbol, "price": price,
        "last_updated": int(at.timestamp() * 1_000_000_000),
    }}


def test_asof_source_uses_latest_real_provider_underlying_observation():
    rows = [row("AAPL", 100, CUT-timedelta(seconds=19)),
            row("AAPL", 101, CUT-timedelta(seconds=3)),
            row("AAPL", 101, CUT-timedelta(seconds=3))]
    found = extract_massive_underlying_observation(
        rows, underlying="AAPL", decision_at=CUT
    )
    assert found.price == 101
    assert found.source == "MASSIVE_OPTION_CHAIN_UNDERLYING_ASSET_LAST"
    assert found.measurement_role == "ASOF_STOCK_PRICE_REFERENCE_NOT_SETTLEMENT"
    assert found.observed_at.endswith("Z")


def test_missing_future_stale_wrong_ticker_and_ambiguous_observations_fail_closed():
    wrong = [row("MSFT", 200, CUT-timedelta(seconds=1))]
    assert extract_massive_underlying_observation(
        wrong, underlying="AAPL", decision_at=CUT
    ) is None
    assert extract_massive_underlying_observation(
        [row("AAPL", 100, CUT+timedelta(microseconds=1))],
        underlying="AAPL", decision_at=CUT
    ) is None
    assert extract_massive_underlying_observation(
        [row("AAPL", 100, CUT-timedelta(seconds=MAX_AGE_SECONDS+1))],
        underlying="AAPL", decision_at=CUT
    ) is None
    assert extract_massive_underlying_observation(
        [row("AAPL", 100, CUT-timedelta(seconds=1)),
         row("AAPL", 101, CUT-timedelta(seconds=1))],
        underlying="AAPL", decision_at=CUT
    ) is None
    assert extract_massive_underlying_observation(
        [{"underlying_asset":{"ticker":"AAPL","price":100}},
         {"underlying_asset":{"ticker":"AAPL","price":-1,
          "last_updated":int(CUT.timestamp()*1e9)}},
         {"underlying_asset":{"ticker":"AAPL","price":float("nan"),
          "last_updated":int(CUT.timestamp()*1e9)}}],
        underlying="AAPL", decision_at=CUT
    ) is None
    with pytest.raises(ValueError, match="TIMEZONE"):
        extract_massive_underlying_observation(
            [], underlying="AAPL", decision_at=CUT.replace(tzinfo=None)
        )


def test_all_rows_without_real_price_keep_snapshot_spot_unknown(db_path):
    result = run_independent_research(
        symbols=["AAPL"],
        massive_client=FakeMassive(), theta_client=FakeTheta(),
        min_dte=7, max_dte=45,
        observed_at=CUT,
        observation_clock=lambda: CUT,
        repo_root=Path("."), code_git_sha="spot-negative-fixture",
        db_path=db_path,
    )
    assert result.status == "COMPLETED"
    conn = get_connection(db_path)
    try:
        snap = conn.execute(
            "SELECT underlying_price,underlying_at,underlying_source FROM market_snapshots "
            "WHERE research_run_id=? AND provider='THETADATA'",
            (result.run_id,),
        ).fetchone()
        assert snap["underlying_price"] is None
        assert snap["underlying_at"] is None
        assert snap["underlying_source"] == "UNKNOWN"
    finally:
        conn.close()


def test_runner_persists_independent_massive_stock_reference_without_extra_requests(db_path):
    calls = {"chain": 0}
    class WithUnderlying(FakeMassive):
        def get_option_chain(self, underlying, **kwargs):
            calls["chain"] += 1
            source = super().get_option_chain(underlying, **kwargs)
            source["results"][0]["underlying_asset"] = row(
                underlying, 101.25, CUT-timedelta(seconds=2)
            )["underlying_asset"]
            return source

    result = run_independent_research(
        symbols=["AAPL"],
        massive_client=WithUnderlying(), theta_client=FakeTheta(),
        min_dte=7, max_dte=45,
        observed_at=CUT,
        observation_clock=lambda: CUT,
        repo_root=Path("."), code_git_sha="spot-positive-fixture",
        db_path=db_path,
    )
    assert result.status == "COMPLETED"
    assert calls["chain"] == 1
    conn = get_connection(db_path)
    try:
        snap = conn.execute(
            "SELECT underlying_price,underlying_at,underlying_source,provider,notes "
            "FROM market_snapshots WHERE research_run_id=? AND provider='THETADATA'",
            (result.run_id,),
        ).fetchone()
        assert snap["underlying_price"] == 101.25
        assert snap["underlying_source"] == "FETCHED"
        assert snap["underlying_at"] == "2026-08-31T18:00:03.000000Z"
        assert "MASSIVE_OPTION_CHAIN_UNDERLYING_ASSET_LAST" in snap["notes"]
        assert "not an exchange close or option settlement" in snap["notes"]
        assert snap["provider"] == "THETADATA"
    finally:
        conn.close()
