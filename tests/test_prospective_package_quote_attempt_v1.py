"""Staging-only synthetic end-to-end prospectively recorded broker pricing."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import replace

import pytest

from src.research.prospective_package_quote_attempt_v1 import (
    record_prospective_package_quote_attempt,
)
from src.research.prospective_evidence_journal_v1 import verify_journal_chain
from src.research.saxo_native_multileg_price_v1 import NativePackageQuote

SCHEMA=(Path(__file__).resolve().parents[1]/
        "docs/research/PROSPECTIVE_EVIDENCE_JOURNAL_REFERENCE_V1.sql")
NOW=datetime(2026,10,12,14,0,0,tzinfo=timezone.utc)


@pytest.fixture
def staging(tmp_path):
    c=sqlite3.connect(tmp_path/"offline-paper-evidence.db")
    c.executescript(SCHEMA.read_text(encoding="utf-8"))
    yield c
    c.close()


def quote(**changes):
    args=dict(
        status="BROKER_PACKAGE_PRICE_REFERENCE_ONLY",
        reasons=(),observed_at=NOW.isoformat(),
        request_completed_at=NOW.isoformat(),
        strategy_bid=-1.8,strategy_ask=-1.5,
        strategy_bid_size=2,strategy_ask_size=2,
        quote_age_seconds=2,strategy_price_source="SYNTHETIC_OPRA",
        quoted_legs=2,source_model="SYNTHETIC_TEST_MODEL",
        price_only=True,broker_package_fill_verified=False,
        outcome_eligible=False,trading_enabled=False,
        evidence_sha256="e"*64,
    )
    args.update(changes)
    return NativePackageQuote(**args)


def run(staging, observer, *, enabled=True, key="SESSION_20261012_SYN_001"):
    return record_prospective_package_quote_attempt(
        journal_conn=staging,opportunity_key=key,attempt_key=key+":price",
        strategy_id="S03",research_run_id=17,candidate_id=19,
        phase="ENTRY",price_observer=observer,
        allow_provider_observation=enabled,clock=lambda:NOW,
    )


def get_events(conn):
    return conn.execute(
        "SELECT event_type,event_state,reason_codes_json,source_family "
        "FROM prospective_evidence_events_v1 ORDER BY id"
    ).fetchall()


def test_default_off_counts_no_trade_without_provider_invocation(staging):
    called=[]
    result=run(staging,lambda:called.append("SHOULD_NOT_CALL"),enabled=False)
    assert called==[]
    assert result.status=="NO_TRADE"
    assert result.outcome_eligible is False
    assert result.trading_enabled is False
    assert [x[0] for x in get_events(staging)]==["OPPORTUNITY","NO_TRADE"]
    assert verify_journal_chain(staging)["checked"]==2


def test_native_quote_reference_still_finishes_no_trade(staging):
    called=[]
    def fake():
        called.append(True)
        return quote()
    r=run(staging,fake)
    assert called==[True]
    assert r.quote_observed_only is True
    assert r.status=="NO_TRADE"
    assert not r.outcome_eligible and not r.trading_enabled
    events=get_events(staging)
    assert [(x[0],x[1]) for x in events]==[
        ("OPPORTUNITY","RECORDED"),
        ("PRICE_REQUEST","RECORDED"),
        ("MARKET_REFERENCE","OBSERVED_ONLY"),
        ("NO_TRADE","NO_TRADE"),
    ]
    assert "NO_INDEPENDENT_PACKAGE_EXECUTION_RECEIPT" in events[-1][2]
    assert verify_journal_chain(staging)["checked"]==4


def test_unavailable_quote_does_not_disappear_from_denominator(staging):
    result=run(staging,lambda:quote(
        status="UNVERIFIED_OR_UNAVAILABLE_PACKAGE_PRICE",
        reasons=("PACKAGE_SIZE_OR_DEPTH_NOT_PROVEN",),
        strategy_bid_size=None,strategy_ask_size=None))
    assert result.quote_observed_only is False
    assert [x[0] for x in get_events(staging)]==[
        "OPPORTUNITY","PRICE_REQUEST","SOURCE_FAILURE","NO_TRADE"]
    assert verify_journal_chain(staging)["checked"]==4


def test_provider_exception_is_redacted_and_still_no_trade(staging):
    def fails():
        raise RuntimeError("ACCESS_TOKEN_AND_SECRET_SHOULD_NEVER_APPEAR")
    r=run(staging,fails)
    assert r.status=="NO_TRADE"
    events=get_events(staging)
    assert [x[0] for x in events]==[
        "OPPORTUNITY","PRICE_REQUEST","SOURCE_FAILURE","NO_TRADE"]
    assert "ACCESS_TOKEN" not in str(events)
    assert verify_journal_chain(staging)["checked"]==4


def test_fake_outcome_promotion_is_rejected_and_logged_as_failure(staging):
    fraud=quote(broker_package_fill_verified=True)
    decision=run(staging,lambda:fraud)
    assert decision.status=="NO_TRADE"
    assert not decision.quote_observed_only
    events=get_events(staging)
    assert [x[0] for x in events]==[
        "OPPORTUNITY","PRICE_REQUEST","SOURCE_FAILURE","NO_TRADE"]
    assert "SOURCE_PROBE_OR_EVIDENCE_VALIDATION_FAILED" in events[-1][2]
    assert verify_journal_chain(staging)["checked"]==4


def test_duplicate_opportunity_does_not_call_provider_twice(staging):
    run(staging,lambda:quote())
    spy=[]
    with pytest.raises(sqlite3.IntegrityError):
        run(staging,lambda:spy.append("NOT_ALLOWED"))
    assert spy==[]
    assert verify_journal_chain(staging)["checked"]==4


def test_no_validated_outcome_or_pnl_columns_in_the_journal(staging):
    cols={x[1] for x in staging.execute(
        "PRAGMA table_info('prospective_evidence_events_v1')")}
    assert "outcome_eligible" not in cols
    assert "pnl_minor" not in cols
    assert "broker_account_key" not in cols
