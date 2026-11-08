"""Candidate-linked retrospective EOD study never changes validated populations."""
from datetime import UTC, date, datetime

import pytest

from src.database.repository import get_connection
from src.providers.thetadata import ThetaDataResponseError
from src.research.shadow_expiry_eod_reference_v1 import (
    load_expiry_eod_reference_report,
)
from src.research.stock_eod_reference_v1 import (
    parse_stock_eod_reference,
)
from tests.test_shadow_outcome_collector import seed_active_candidate

DAY=date(2026, 9, 18)


def reference(symbol="AAPL", day=DAY, after_hours=True):
    return parse_stock_eod_reference(
        {"response": [{
            "created": "2026-09-18T17:15:46",
            "last_trade": "2026-09-18T17:15:42" if after_hours
                          else "2026-09-18T15:59:58",
            "close": 108.0,
        }]}, symbol=symbol,session_date=day,
        fetched_at=datetime(2026, 9, 21, 12, tzinfo=UTC),
    )


def test_eod_reference_is_candidate_linked_not_a_validated_outcome(db_path):
    cid, _ = seed_active_candidate(db_path)
    observed = []
    def fetch(symbol, day):
        observed.append((symbol,day))
        return reference(symbol,day)
    out=load_expiry_eod_reference_report(
        db_path=db_path,as_of_day="2026-09-21",fetcher=fetch
    )
    assert observed==[("AAPL",DAY)]
    assert out["total_expired_admitted"]==1
    assert out["reference_estimate_count"]==1
    assert out["unresolved_count"]==0
    assert out["independent_expiry_dates"]==1
    assert out["unique_symbol_expiry_requests"]==1
    result=out["rows"][0]
    assert result["candidate_id"]==cid
    assert result["source_row_sha256"]
    assert result["outcome_state"]=="EOD_REFERENCE_MODEL_NOT_VALIDATED"
    assert result["verified_trading_outcome"] is False
    assert result["source_last_trade_after_1600_ny"] is True
    assert result["reason_code"]=="AFTER_HOURS_EOD_REFERENCE_NOT_EXPIRY_PRICE"
    assert isinstance(result["indicative_net_usd_minor"],int)
    assert "not the option-expiry" in out["disclaimer"]
    # Never creates a real outcome or reclassifies earlier missing market spots.
    conn=get_connection(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM shadow_expiry_outcomes_v1").fetchone()[0]==0
        assert conn.execute("SELECT COUNT(*) FROM opportunity_outcomes_v1").fetchone()[0]==0
    finally:
        conn.close()


def test_missing_vendor_evidence_stays_unresolved(db_path):
    cid,_=seed_active_candidate(db_path)
    def unavailable(*args):
        raise ThetaDataResponseError("HTTP 403")
    out=load_expiry_eod_reference_report(
        db_path=db_path,as_of_day="2026-09-21",fetcher=unavailable,
    )
    assert out["reference_estimate_count"]==0
    assert out["unresolved_count"]==1
    assert out["rows"][0]["candidate_id"]==cid
    assert out["rows"][0]["reason_code"]=="SOURCE_UNAVAILABLE"
    assert "indicative_net_usd_minor" not in out["rows"][0]


def test_wrong_provider_identity_must_never_price_a_candidate(db_path):
    seed_active_candidate(db_path)
    out=load_expiry_eod_reference_report(
        db_path=db_path,as_of_day="2026-09-21",
        fetcher=lambda symbol,day:reference(symbol="TSLA",day=day),
    )
    assert out["reference_estimate_count"]==0
    assert out["rows"][0]["reason_code"]=="INVALID_SOURCE_REPORT"


def test_request_cap_fails_entire_population_before_contacting_vendor(db_path):
    seed_active_candidate(db_path)
    def forbidden(*args):
        raise AssertionError("must not contact provider")
    with pytest.raises(ValueError,match="INVALID_BOUNDED"):
        load_expiry_eod_reference_report(
            db_path=db_path,as_of_day="2026-09-21",
            fetcher=forbidden,max_unique_requests=0,
        )
    out=load_expiry_eod_reference_report(
        db_path=db_path,as_of_day="2026-09-18",
        fetcher=forbidden,
    )
    assert out["total_expired_admitted"]==0


def test_same_vendor_price_remains_only_a_postsession_reference(db_path):
    seed_active_candidate(db_path)
    out=load_expiry_eod_reference_report(
        db_path=db_path,as_of_day="2026-09-21",
        fetcher=lambda symbol,day:reference(symbol,day,after_hours=False),
    )
    row=out["rows"][0]
    assert row["outcome_state"]=="EOD_REFERENCE_MODEL_NOT_VALIDATED"
    assert row["reason_code"]=="EOD_REFERENCE_NOT_SETTLEMENT"
    assert row["verified_trading_outcome"] is False
