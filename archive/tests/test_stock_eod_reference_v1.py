"""Strict vendor EOD provenance: no trade or settlement assertions."""
from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from src.providers.thetadata import ThetaDataClient
from src.research.stock_eod_reference_v1 import (
    MEASUREMENT_ROLE, StockEodReferenceError, fetch_stock_eod_reference,
    parse_stock_eod_reference,
)

DAY = date(2026, 10, 16)
FETCH = datetime(2026, 10, 18, 18, 0, tzinfo=UTC)
ROW = {
    "created": "2026-10-16T17:15:45.169",
    "last_trade": "2026-10-16T17:15:41.347",
    "close": 343.46, "open": 345.78,
    "high": 347.82, "low": 340.46, "volume": 59865338,
}


def parse(row=None, *, payload=None, when=FETCH):
    return parse_stock_eod_reference(
        {"response": [ROW if row is None else row]} if payload is None else payload,
        symbol="AAPL", session_date=DAY, fetched_at=when,
    )


def test_eod_v3_is_explicitly_not_regular_close_or_validated_settlement():
    record = parse()
    assert record.symbol == "AAPL"
    assert record.session_date == DAY.isoformat()
    assert record.reported_close == 343.46
    assert record.report_generated_at.endswith("-04:00")
    assert record.last_trade_at.endswith("-04:00")
    assert record.last_trade_after_1600_ny is True
    assert record.measurement_role == MEASUREMENT_ROLE
    assert "NOT_SETTLEMENT" in record.measurement_role
    assert len(record.row_sha256) == 64


@pytest.mark.parametrize("bad", [
    {"response": []}, {"response": [ROW, ROW]}, {"response": {}},
    {"something_else": [ROW]}, [],
])
def test_missing_or_ambiguous_eod_fails_closed(bad):
    with pytest.raises(StockEodReferenceError, match="NO_UNAMBIGUOUS"):
        parse(payload=bad)


@pytest.mark.parametrize("alter,reason", [
    ({"close": None}, "INVALID_EOD_CLOSE"),
    ({"close": float("nan")}, "INVALID_EOD_CLOSE"),
    ({"close": -0.5}, "INVALID_EOD_CLOSE"),
    ({"close": True}, "INVALID_EOD_CLOSE"),
    ({"created": "2026-10-15T17:15:45"}, "WRONG_TIMEZONE_OR_SESSION"),
    ({"last_trade": "2026-10-17T17:15:45"}, "WRONG_TIMEZONE_OR_SESSION"),
    ({"created": "2026-10-16T17:15:45Z"}, "WRONG_TIMEZONE_OR_SESSION"),
    ({"created": "2026-10-16T15:55:00"}, "INCOHERENT_EOD_REPORT_CLOCK"),
    ({"last_trade": "2026-10-16T17:15:46"}, "INCOHERENT_EOD_REPORT_CLOCK"),
])
def test_corrupt_or_wrong_session_reports_are_not_usable(alter, reason):
    r={**ROW,**alter}
    with pytest.raises(StockEodReferenceError,match=reason):
        parse(r)


def test_future_report_and_naive_fetch_time_are_rejected():
    with pytest.raises(StockEodReferenceError,match="REPORT_FROM_FUTURE"):
        parse(when=datetime(2026,10,16,19,0,tzinfo=UTC))
    with pytest.raises(StockEodReferenceError,match="FETCH_TIMEZONE_UNKNOWN"):
        parse(when=datetime(2026,10,18,18))


def test_transport_uses_one_exact_session_request_and_no_writes():
    calls = []
    def transport(url, timeout):
        calls.append((url,timeout))
        return json.dumps({"response":[ROW]}).encode()
    client=ThetaDataClient(transport=transport,timeout_seconds=4)
    result=fetch_stock_eod_reference("aapl",DAY,client=client,fetched_at=FETCH)
    assert result.reported_close==343.46
    assert len(calls)==1
    u=urlsplit(calls[0][0])
    assert u.path=="/v3/stock/history/eod"
    assert parse_qs(u.query)=={
        "symbol":["AAPL"],"start_date":["20261016"],
        "end_date":["20261016"],"format":["json"],
    }
    assert calls[0][1]==4


def test_last_trade_before_close_does_not_change_evidence_role():
    r={**ROW,"last_trade":"2026-10-16T15:59:58"}
    record=parse(r)
    assert record.last_trade_after_1600_ny is False
    assert record.measurement_role==MEASUREMENT_ROLE
