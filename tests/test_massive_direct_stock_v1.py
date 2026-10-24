from datetime import UTC, datetime, timedelta

import pytest

from src.research.massive_direct_stock_v1 import (
    SOURCE, parse_stock_ticker_snapshot,
)
from src.research.massive_underlying_observation_v1 import (
    verified_stock_source_from_notes,
)


CUT=datetime(2026,10,23,15,0,tzinfo=UTC)


def response(price=100.0,at=None,ticker="SPY"):
    t=at or CUT-timedelta(seconds=4)
    return {"status":"OK","ticker":{"ticker":ticker,"lastTrade":{
        "p":price,"t":int(t.timestamp()*1_000_000_000),
    }}}


def test_actual_stock_trade_qualifies_as_independent_not_model_source():
    result=parse_stock_ticker_snapshot(
        response(),underlying="SPY",decision_at=CUT,
    )
    assert result.reason=="QUALIFIED_STOCK_LAST_TRADE"
    assert result.observation.price==100.0
    assert result.observation.source==SOURCE
    assert result.observation.observed_at.endswith("Z")
    assert verified_stock_source_from_notes(
        f"stock price source={SOURCE}; role=ASOF_STOCK_PRICE_REFERENCE_NOT_SETTLEMENT"
    )==SOURCE


@pytest.mark.parametrize("payload,reason",[
    ({"status":"NOT_ENTITLED"},"STOCK_TRADE_NOT_ENTITLED"),
    ({"status":"OK","ticker":{"ticker":"SPY"}},"STOCK_LAST_TRADE_NOT_IN_PLAN_OR_RESPONSE"),
    (response(ticker="IWM"),"STOCK_TICKER_IDENTITY_MISMATCH"),
    (response(price=-5),"STOCK_LAST_TRADE_PRICE_INVALID"),
    (response(at=CUT-timedelta(minutes=15)),"STOCK_TRADE_STALE_AT_OPTION_CUT"),
    (response(at=CUT+timedelta(seconds=1)),"STOCK_TRADE_AFTER_OPTION_CUT"),
    ({"status":"OK","ticker":{"ticker":"SPY","lastTrade":{
        "p":101,"t":1600
    }}},"STOCK_TRADE_STALE_AT_OPTION_CUT"),
])
def test_entitlement_and_timestamp_failures_never_turn_into_trade_idea(
    payload,reason,
):
    result=parse_stock_ticker_snapshot(payload,underlying="SPY",decision_at=CUT)
    assert result.observation is None
    assert result.reason==reason


def test_ambiguous_and_model_sources_are_not_accepted():
    notes=(
        "stock price source=MASSIVE_OPTION_CHAIN_UNDERLYING_ASSET_LAST; "
        "stock price source=MASSIVE_STOCK_SNAPSHOT_LAST_TRADE;"
    )
    assert verified_stock_source_from_notes(notes) is None
    assert verified_stock_source_from_notes(
        "stock price source=THETADATA_GREEKS_MODEL_PRICE;"
    ) is None


def test_unknown_timezone_and_ticker_are_rejected():
    with pytest.raises(ValueError,match="TIMEZONE"):
        parse_stock_ticker_snapshot(response(),underlying="SPY",
                                    decision_at=CUT.replace(tzinfo=None))
    with pytest.raises(ValueError,match="TICKER"):
        parse_stock_ticker_snapshot(response(),underlying="/",decision_at=CUT)


def test_client_requests_only_known_stocks_snapshot_endpoint(monkeypatch):
    from src.providers.massive import MassiveClient

    seen=[]
    def fake_get(self,path,params=None):
        seen.append((path,params))
        return response()
    monkeypatch.setattr(MassiveClient,"_get_json",fake_get)
    client=MassiveClient(api_key="TEST_NOT_SECRET")
    assert client.get_stock_ticker_snapshot("spy")["status"]=="OK"
    assert seen==[
        ("/v2/snapshot/locale/us/markets/stocks/tickers/SPY",None)
    ]
    with pytest.raises(ValueError,match="TICKER"):
        client.get_stock_ticker_snapshot("../../secrets")


def test_opt_in_direct_stock_source_persists_fetched_receipt(
    db_path,monkeypatch,
):
    from zoneinfo import ZoneInfo
    from src.database.repository import get_connection
    from src.research.independent_runner import run_independent_research
    from tests.test_independent_runner import FakeMassive,FakeTheta

    cut=datetime(2026,8,31,14,0,tzinfo=ZoneInfo("America/New_York"))
    monkeypatch.setenv("CHRISTIANIA_DIRECT_STOCK_SNAPSHOT_ENABLED","1")

    class FakeStocks(FakeMassive):
        calls=0
        def get_stock_ticker_snapshot(self, underlying):
            self.calls+=1
            assert underlying=="AAPL"
            return response(
                ticker="AAPL",at=cut.astimezone(UTC)-timedelta(seconds=3),
            )

    provider=FakeStocks()
    result=run_independent_research(
        symbols=["AAPL"],massive_client=provider,theta_client=FakeTheta(),
        observed_at=cut,observation_clock=lambda:cut,
        db_path=db_path,code_git_sha="NO_SECRET_TEST_COMMIT",
        max_underlying_recovery_retries=0,
    )
    assert provider.calls==1
    with get_connection(db_path) as conn:
        snapshot=conn.execute(
            """SELECT underlying_price,underlying_source,underlying_at,notes
               FROM market_snapshots
               WHERE research_run_id=? AND provider='THETADATA'""",
            (result.run_id,),
        ).fetchone()
        assert snapshot["underlying_source"]=="FETCHED"
        assert snapshot["underlying_price"]==100.0
        assert f"stock price source={SOURCE};" in snapshot["notes"]
        assert "role=ASOF_STOCK_PRICE_REFERENCE_NOT_SETTLEMENT" in snapshot["notes"]


def test_direct_stock_provenance_reaches_same_trade_desk_evidence_gate(tmp_path):
    import sqlite3
    from src.decision.operator_profit_desk_v1 import load_underlying_source_coverage
    from src.research.independent_family_read_model_v1 import inspect_latest_run
    from tests.test_independent_family_read_model_v1 import seed
    path=tmp_path/"model.sqlite"
    seed(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """UPDATE market_snapshots SET notes=?
               WHERE underlying='XYZ'""",
            (f"stock price source={SOURCE}; "
             "role=ASOF_STOCK_PRICE_REFERENCE_NOT_SETTLEMENT",),
        )
    coverage=load_underlying_source_coverage(db_path=path)
    assert coverage.independent_fresh_prices==1
    result=inspect_latest_run(db_path=path)
    assert result.snapshots_with_independent_spot==1
    assert result.families_constructed==7
    assert result.live_trades_authorized==0


def test_disabled_direct_source_does_not_make_paid_provider_requests(
    db_path,monkeypatch,
):
    from zoneinfo import ZoneInfo
    from src.research.independent_runner import run_independent_research
    from tests.test_independent_runner import FakeMassive, FakeTheta

    cut=datetime(2026,8,31,14,0,tzinfo=ZoneInfo("America/New_York"))
    monkeypatch.delenv("CHRISTIANIA_DIRECT_STOCK_SNAPSHOT_ENABLED",raising=False)
    class FakeStocks(FakeMassive):
        def get_stock_ticker_snapshot(self, underlying):
            raise AssertionError("OPTIONAL_STOCK_API_CALLED_WITHOUT_OPT_IN")

    result=run_independent_research(
        symbols=["AAPL"],massive_client=FakeStocks(),theta_client=FakeTheta(),
        observed_at=cut,observation_clock=lambda:cut,
        db_path=db_path,code_git_sha="NO_STOCK_PAID_API",
        max_underlying_recovery_retries=0,
    )
    assert result.status=="COMPLETED"
