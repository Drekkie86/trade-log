import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.research.cash_settled_market_contract import (
    assess_live_quote_row,
    read_probe_evidence,
    resolve_contract_semantics,
    settlement_reference_at,
    write_probe_evidence,
)

NY = ZoneInfo("America/New_York")


def test_xsp_contract_semantics_use_official_calendar_close():
    semantics = resolve_contract_semantics("XSP")
    assert semantics.settlement_type == "CASH"
    assert semantics.exercise_style == "EUROPEAN"
    assert semantics.multiplier == 100.0
    assert semantics.settlement_style == "PM"
    assert semantics.settlement_reference_event == "OFFICIAL_INDEX_CLOSE"
    assert settlement_reference_at("2026-09-08", semantics).isoformat() == "2026-09-08T16:00:00-04:00"
    assert settlement_reference_at("2026-11-27", semantics).isoformat() == "2026-11-27T13:00:00-05:00"


def test_spx_requires_exact_series_root_before_settlement_convention_is_used():
    unknown = resolve_contract_semantics("SPX")
    assert unknown.exact_series_identity is False
    assert unknown.state == "SERIES_ROOT_REQUIRED"
    am = resolve_contract_semantics("SPX", series_root="SPX")
    assert am.settlement_reference_event == "SPECIAL_OPENING_QUOTATION"
    assert settlement_reference_at("2026-09-18", am) is None
    assert resolve_contract_semantics("SPX", series_root="SPXW").settlement_reference_event == "OFFICIAL_INDEX_CLOSE"


def test_unexpected_xsp_root_fails_closed():
    semantics = resolve_contract_semantics("XSP", series_root="SPXW")
    assert semantics.exact_series_identity is False
    assert semantics.state == "SERIES_IDENTITY_CONFLICT"


def test_live_xsp_quote_requires_fresh_timestamp_and_valid_nbbo():
    row = {"symbol":"XSP","expiration":"2026-09-08","strike":650.0,"right":"C","bid":1.20,"ask":1.25,"raw_timestamp":"2026-09-08T10:00:00.000"}
    result = assess_live_quote_row("XSP", row, observed_at=datetime(2026,9,8,10,0,30,tzinfo=NY))
    assert result["state"] == "LIVE_DATA_CONTRACT_VALIDATED"
    assert result["quote_age_seconds"] == 30.0
    assert result["settlement_reference_at_et"] == "2026-09-08T16:00:00-04:00"


def test_stale_quote_fails_closed():
    row = {"symbol":"XSP","expiration":"2026-09-08","strike":650,"right":"P","bid":1.0,"ask":1.1,"raw_timestamp":"2026-09-08T09:50:00.000"}
    result = assess_live_quote_row("XSP", row, observed_at=datetime(2026,9,8,10,0,0,tzinfo=NY))
    assert result["state"] == "LIVE_BLOCKED"
    assert "QUOTE_STALE" in result["blockers"]


def _live_evidence(now):
    return {
      "contract_version":"CASH_SETTLED_MARKET_CONTRACT_V1",
      "probe_mode":"live",
      "generated_at":now.isoformat(timespec="milliseconds").replace("+00:00","Z"),
      "provider":"THETADATA",
      "provider_base_url":"http://127.0.0.1:25503/v3",
      "overall_state":"LIVE_DATA_CONTRACT_VALIDATED_XSP_ONLY",
      "live_symbols":["XSP"],
      "symbols":{},
      "decision_enabled":False,
      "broker_order_path":False,
    }


def test_provider_evidence_is_hash_verified_and_tamper_fails_closed(tmp_path):
    now = datetime(2026,9,8,15,0,tzinfo=UTC)
    path = write_probe_evidence(_live_evidence(now), tmp_path/"proof.json")
    assert read_probe_evidence(path, now=now) is not None
    payload = json.loads(path.read_text())
    payload["live_symbols"] = ["XSP","SPX"]
    path.write_text(json.dumps(payload))
    assert read_probe_evidence(path, now=now) is None


def test_live_provider_evidence_expires(tmp_path):
    generated = datetime(2026,9,1,15,0,tzinfo=UTC)
    path = write_probe_evidence(_live_evidence(generated), tmp_path/"proof.json")
    assert read_probe_evidence(path, now=generated + timedelta(days=6)) is not None
    assert read_probe_evidence(path, now=generated + timedelta(days=8)) is None
