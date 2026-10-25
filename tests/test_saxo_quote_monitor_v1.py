"""Saxo quote-monitor evidence is tiny, redacted, stale-aware, and no-order."""
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path

from src.operations.saxo_live_quote_evidence_v1 import (
    SaxoFeedProof, QuoteProof,
)
from src.operations.saxo_quote_monitor_v1 import (
    persist_quote_status, read_quote_status, run_market_data_heartbeat,
)
from src.ui.home_pages import system_checks

NOW = datetime(2026,10,26,15,0,tzinfo=UTC)


def sample(state="LIVE_TWO_SIDED_REFERENCE", checked_at=NOW):
    quote=QuoteProof(
        "REALTIME_FIRM_REFERENCE","Firm InfoPrice only",0,"Open",
        checked_at.isoformat(),True,True,
    )
    return SaxoFeedProof(
        state=state, detail="Market evidence only: no broker order.",
        symbol="AAPL",checked_at=checked_at.isoformat(),
        stock=quote,option=quote,sampled_expiry="2026-11-20",
        option_contract_size=100,
    )


def test_persisted_live_info_price_does_not_claim_broker_fill(tmp_path):
    path=tmp_path/"feed.json"
    persist_quote_status(sample(),path=path)
    saved=json.loads(path.read_text())
    assert saved["order_authority"] is False
    assert saved["broker_fill_verified"] is False
    assert saved["environment"] == "LIVE"
    if os.name!="nt":
        assert path.stat().st_mode & 0o077 == 0
    data=read_quote_status(path=path,now=NOW+timedelta(minutes=5))
    assert data["state"]=="LIVE_TWO_SIDED_REFERENCE"
    assert data["stock_state"]=="REALTIME_FIRM_REFERENCE"
    assert "token" not in str(data).lower()


def test_stale_report_never_reappears_as_real_time(tmp_path):
    path=tmp_path/"feed.json"
    persist_quote_status(sample(),path=path)
    assert read_quote_status(path=path,now=NOW+timedelta(hours=2))["state"]=="STALE"


def test_missing_future_and_tampered_reports_are_unverified(tmp_path):
    path=tmp_path/"feed.json"
    assert read_quote_status(path=path,now=NOW)["state"]=="UNVERIFIED"
    persist_quote_status(sample(),path=path)
    data=json.loads(path.read_text())
    data["order_authority"]=True
    path.write_text(json.dumps(data))
    assert read_quote_status(path=path,now=NOW)["state"]=="UNVERIFIED"
    data["order_authority"]=False
    data["environment"]="SIM"
    path.write_text(json.dumps(data))
    assert read_quote_status(path=path,now=NOW)["state"]=="UNVERIFIED"
    data["environment"]="LIVE"
    data["checked_at"]=(NOW+timedelta(days=1)).isoformat()
    path.write_text(json.dumps(data))
    assert read_quote_status(path=path,now=NOW)["state"]=="UNVERIFIED"


def test_one_heartbeat_call_stores_only_an_allowed_state(tmp_path):
    path=tmp_path/"feed.json"
    calls=[]
    def probe():
        calls.append(True)
        return sample(state="MARKET_CLOSED_UNVERIFIED")
    state=run_market_data_heartbeat(probe=probe,path=path)
    assert state=="MARKET_CLOSED_UNVERIFIED"
    assert calls==[True]
    assert path.exists()


def test_system_health_explains_quotes_not_equal_executable_strategy():
    feed=sample().as_dict()
    out={
        "state":feed["state"],
        "detail":feed["detail"],
        "stock_state":"REALTIME_FIRM_REFERENCE",
        "option_state":"REALTIME_FIRM_REFERENCE",
    }
    rows=system_checks({}, {}, {}, feed=out)
    assert {label:ok for label,ok,_ in rows}["Saxo stock/OPRA sample"] is True
    combined=" ".join(detail for _,_,detail in rows)
    assert "NOT verified" in combined
    denied=system_checks({}, {}, {}, feed={
        "state":"PARTIAL_OR_UNVERIFIED","option_state":"NO_ACCESS",
        "detail":"no rights",
    })
    assert {label:ok for label,ok,_ in denied}["Saxo stock/OPRA sample"] is False


def test_systemd_job_has_no_order_routing_and_keeps_token_store_separate():
    root=Path(__file__).resolve().parents[1]
    unit=(root/"deploy/systemd/christiania-saxo-market-data.service").read_text()
    timer=(root/"deploy/systemd/christiania-saxo-market-data.timer").read_text()
    assert "User=christiania" in unit
    assert "ProtectSystem=strict" in unit
    assert "CHRISTIANIA_SAXO_TOKEN_STORE=" in unit
    assert "ReadWritePaths=/var/lib/christiania/data" in unit
    assert "ReadWritePaths=-/var/lib/christiania/secure" in unit
    assert "src.operations.saxo_quote_monitor_v1" in unit
    assert "OnUnitActiveSec=1h" in timer
    assert "order" not in unit.lower()
