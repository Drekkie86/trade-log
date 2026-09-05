from datetime import datetime
from zoneinfo import ZoneInfo

from src.research.cash_settled_market_contract import (
    assess_live_quote_row,
    resolve_contract_semantics,
    settlement_reference_at,
)


NY = ZoneInfo("America/New_York")


def test_xsp_contract_semantics_are_exact_cash_european_pm():
    semantics = resolve_contract_semantics("XSP")
    assert semantics.state == "VERIFIED_PRODUCT_CONTRACT"
    assert semantics.settlement_type == "CASH"
    assert semantics.exercise_style == "EUROPEAN"
    assert semantics.multiplier == 100.0
    assert semantics.settlement_style == "PM"
    assert semantics.exact_series_identity is True
    assert settlement_reference_at("2026-09-08", semantics).isoformat() == "2026-09-08T16:00:00-04:00"


def test_spx_requires_exact_series_root_before_settlement_convention_is_used():
    unknown = resolve_contract_semantics("SPX")
    assert unknown.exact_series_identity is False
    assert unknown.state == "SERIES_ROOT_REQUIRED"
    assert resolve_contract_semantics("SPX", series_root="SPX").settlement_style == "AM"
    assert resolve_contract_semantics("SPX", series_root="SPXW").settlement_style == "PM"


def test_live_xsp_quote_requires_fresh_timestamp_and_valid_nbbo():
    row = {
        "symbol": "XSP",
        "expiration": "2026-09-08",
        "strike": 650.0,
        "right": "C",
        "bid": 1.20,
        "ask": 1.25,
        "raw_timestamp": "2026-09-08T10:00:00.000",
    }
    result = assess_live_quote_row(
        "XSP", row, observed_at=datetime(2026, 9, 8, 10, 0, 30, tzinfo=NY)
    )
    assert result["state"] == "LIVE_VALIDATED"
    assert result["quote_age_seconds"] == 30.0
    assert result["settlement_reference_at_et"] == "2026-09-08T16:00:00-04:00"


def test_stale_quote_fails_closed():
    row = {
        "symbol": "XSP", "expiration": "2026-09-08", "strike": 650,
        "right": "P", "bid": 1.0, "ask": 1.1,
        "raw_timestamp": "2026-09-08T09:50:00.000",
    }
    result = assess_live_quote_row(
        "XSP", row, observed_at=datetime(2026, 9, 8, 10, 0, 0, tzinfo=NY)
    )
    assert result["state"] == "LIVE_BLOCKED"
    assert "QUOTE_STALE" in result["blockers"]
