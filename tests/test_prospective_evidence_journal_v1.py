from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from pathlib import Path
import pytest

from src.research.prospective_evidence_journal_v1 import (
    EvidenceEvent,append_evidence_event,verify_journal_chain,ZERO_HASH,
    record_quote_request,record_quote_result
)

SCHEMA=(Path(__file__).resolve().parents[1] /
        "docs/research/PROSPECTIVE_EVIDENCE_JOURNAL_REFERENCE_V1.sql")


@pytest.fixture
def db(tmp_path):
    c=sqlite3.connect(tmp_path/"journal.db")
    c.executescript(SCHEMA.read_text(encoding="utf8"))
    yield c
    c.close()


def event(i, *, et="OPPORTUNITY",state="RECORDED",source="NONE",digest=None,
          reasons=(),when="2026-10-12T14:00:00Z", candidate=None):
    return EvidenceEvent(
        event_key=f"cohortA:event:{i}",
        opportunity_key="cohortA:opp:0001",
        strategy_id="S03",
        phase="ENTRY" if et not in ("OPPORTUNITY","NO_TRADE") else "NONE",
        event_type=et,
        event_state=state,
        event_at=when,
        source_family=source,
        source_evidence_sha256=digest,
        reason_codes=reasons,
        candidate_id=candidate,
        research_run_id=15,
    )


def rows(db):
    return db.execute(
        "SELECT id,event_key,event_type,event_state,previous_hash_sha256,"
        "event_hash_sha256 FROM prospective_evidence_events_v1 ORDER BY id"
    ).fetchall()


def test_journal_preserves_opportunity_request_quote_and_no_trade(db):
    ids=[
        append_evidence_event(db,event(1)),
        append_evidence_event(db,event(2,et="PRICE_REQUEST")),
        append_evidence_event(db,event(3,et="MARKET_REFERENCE",
                                      state="OBSERVED_ONLY",source="SAXO_MULTILEG",
                                      digest="a"*64,candidate=12)),
        append_evidence_event(db,event(4,et="NO_TRADE",state="NO_TRADE",
                                      reasons=("NOT_EXECUTABLE_PACKAGE",))),
    ]
    assert ids==[1,2,3,4]
    r=rows(db)
    assert len(r)==4
    assert r[0][4]==ZERO_HASH
    assert r[1][4]==r[0][5]
    check=verify_journal_chain(db)
    assert check["status"]=="HASH_CHAIN_CONSISTENT_ONLY_NOT_EXTERNALLY_VERIFIED"
    assert check["checked"]==4
    assert check["head_sha256"]==r[-1][5]
    assert not any("OUTCOME" in x[2] for x in r)


def test_same_event_key_cannot_silently_overwrite(db):
    append_evidence_event(db,event(1))
    with pytest.raises(sqlite3.IntegrityError):
        append_evidence_event(db,event(1))
    assert len(rows(db))==1
    assert verify_journal_chain(db)["checked"]==1


def test_table_forbids_update_and_delete(db):
    append_evidence_event(db,event(1))
    with pytest.raises(sqlite3.IntegrityError,match="cannot be updated"):
        db.execute("UPDATE prospective_evidence_events_v1 SET event_state='REJECTED'")
    with pytest.raises(sqlite3.IntegrityError,match="cannot be deleted"):
        db.execute("DELETE FROM prospective_evidence_events_v1")
    assert len(rows(db))==1


def test_insert_cannot_override_chain_predecessor(db):
    with pytest.raises(sqlite3.IntegrityError,match="predecessor"):
        db.execute(
            """INSERT INTO prospective_evidence_events_v1 (
              event_key, opportunity_key,strategy_id,phase,event_type,event_state,
              event_at,source_family,reason_codes_json,previous_hash_sha256,
              event_hash_sha256
            ) VALUES ('a','b','S03','NONE','OPPORTUNITY','RECORDED',
              '2026-10-12T14:00:00Z','NONE','[]',?,?)""",
            ("f"*64,"a"*64)
        )


def test_no_trade_rejection_and_failed_quote_retained(db):
    append_evidence_event(db,event(1))
    append_evidence_event(db,event(
        2,et="SOURCE_FAILURE",state="UNAVAILABLE",
        reasons=("PROVIDER_AUTH_FAILURE",)))
    append_evidence_event(db,event(
        3,et="REJECTION",state="REJECTED",
        reasons=("STALENESS_UNVERIFIED",)))
    append_evidence_event(db,event(
        4,et="NO_TRADE",state="NO_TRADE",
        reasons=("MARKET_CLOSED",)))
    states=db.execute(
        "SELECT event_state,COUNT(*) FROM prospective_evidence_events_v1 "
        "GROUP BY event_state"
    ).fetchall()
    assert dict(states)=={
        "RECORDED":1,"UNAVAILABLE":1,"REJECTED":1,"NO_TRADE":1
    }
    assert verify_journal_chain(db)["checked"]==4


@pytest.mark.parametrize("bad",[
    {"event_key":"danger secret token with spaces"},
    {"phase":"MIDDLE"},
    {"event_type":"VALIDATED_PACKAGE_OUTCOME"},
    {"event_state":"EXECUTED"},
    {"source_evidence_sha256":"abc"},
    {"candidate_id":0},
    {"research_run_id":True},
    {"reason_codes":("token=secret",)},
    {"reason_codes":("OK","OK")},
    {"event_at":"2026-10-12T14:00:00"},
])
def test_bad_fields_rejected_before_db_write(db,bad):
    from dataclasses import replace
    original=event(1)
    modified=replace(original,**bad)
    with pytest.raises(ValueError):
        append_evidence_event(db,modified)
    assert len(rows(db))==0


def test_market_reference_requires_source_evidence_hash(db):
    with pytest.raises(ValueError,match="MARKET_REFERENCE_REQUIRES"):
        append_evidence_event(db,event(1,et="MARKET_REFERENCE",
                                       state="OBSERVED_ONLY",source="SAXO_MULTILEG"))
    assert len(rows(db))==0


def test_reproducible_hash_chain_over_same_events(tmp_path):
    def build(name):
        c=sqlite3.connect(tmp_path/name)
        c.executescript(SCHEMA.read_text(encoding="utf8"))
        append_evidence_event(c,event(1))
        append_evidence_event(c,event(2,et="NO_TRADE",state="NO_TRADE",reasons=("NOT_EXECUTABLE",)))
        res=verify_journal_chain(c)
        c.close()
        return res["head_sha256"]
    assert build("one.db")==build("two.db")


def test_producer_transaction_failure_keeps_existing_chain_intact(db):
    append_evidence_event(db,event(1))
    with pytest.raises(sqlite3.IntegrityError):
        append_evidence_event(db,event(1))
    assert db.in_transaction is False
    append_evidence_event(db,event(2,et="NO_TRADE",state="NO_TRADE",reasons=("NOT_EXECUTABLE",)))
    assert verify_journal_chain(db)["checked"]==2


def test_audit_is_bounded_and_explicitly_incomplete(db):
    append_evidence_event(db,event(1))
    append_evidence_event(db,event(2,et="PRICE_REQUEST"))
    append_evidence_event(db,event(3,et="NO_TRADE",state="NO_TRADE",
                                   reasons=("INSUFFICIENT_DEPTH",)))
    result=verify_journal_chain(db,max_rows=2)
    assert result=={"status":"AUDIT_LIMIT_REACHED","checked":0,"limit":2}
    with pytest.raises(ValueError):
        verify_journal_chain(db,max_rows=1001)




def test_cannot_record_quote_success_without_prior_opportunity(db):
    with pytest.raises(sqlite3.IntegrityError,match="follow a recorded opportunity"):
        append_evidence_event(db,event(
            8,et="MARKET_REFERENCE",state="OBSERVED_ONLY",
            source="SAXO_MULTILEG",digest="a"*64))
    assert len(rows(db))==0


def test_cannot_backdate_quote_before_opportunity(db):
    from dataclasses import replace
    append_evidence_event(db,event(1,when="2026-10-12T14:00:10Z"))
    q=event(2,et="MARKET_REFERENCE",state="OBSERVED_ONLY",
            source="SAXO_MULTILEG",digest="b"*64,
            when="2026-10-12T14:00:09Z")
    with pytest.raises(sqlite3.IntegrityError,match="follow a recorded opportunity"):
        append_evidence_event(db,q)
    assert verify_journal_chain(db)["checked"]==1


def test_cannot_open_same_opportunity_twice(db):
    from dataclasses import replace
    append_evidence_event(db,event(1))
    with pytest.raises(sqlite3.IntegrityError):
        append_evidence_event(db,event(2))
    assert verify_journal_chain(db)["checked"]==1


def test_no_trade_requires_explanation_and_not_a_win(db):
    append_evidence_event(db,event(1))
    with pytest.raises(ValueError,match="NO_TRADE_REQUIRES"):
        append_evidence_event(db,event(2,et="NO_TRADE",state="NO_TRADE"))
    assert len(rows(db))==1



def _fake_probe(*, status="BROKER_PACKAGE_PRICE_REFERENCE_ONLY",
                reasons=(), outcome_eligible=False, trading_enabled=False,
                broker_package_fill_verified=False):
    return SimpleNamespace(
        status=status,
        reasons=reasons,
        outcome_eligible=outcome_eligible,
        trading_enabled=trading_enabled,
        broker_package_fill_verified=broker_package_fill_verified,
        evidence_sha256="b"*64,
    )


def test_native_package_quote_result_requires_prior_request(db):
    append_evidence_event(db,event(1))
    with pytest.raises(ValueError,match="QUOTE_RESULT_WITHOUT_REQUEST"):
        record_quote_result(
            db,attempt_key="a1",probe_result=_fake_probe(),
            event_at="2026-10-12T14:00:03Z")
    assert len(rows(db))==1
    record_quote_request(
        db,attempt_key="a1",opportunity_key="cohortA:opp:0001",
        strategy_id="S03", phase="ENTRY",event_at="2026-10-12T14:00:01Z",
        source_family="SAXO_MULTILEG",candidate_id=12,research_run_id=15)
    record_quote_result(
        db,attempt_key="a1",probe_result=_fake_probe(),
        event_at="2026-10-12T14:00:03Z")
    es=rows(db)
    assert [x[2] for x in es]==[
        "OPPORTUNITY","PRICE_REQUEST","MARKET_REFERENCE"]
    assert es[-1][3]=="OBSERVED_ONLY"
    assert verify_journal_chain(db)["checked"]==3


def test_native_quote_failure_included_not_silently_dropped(db):
    append_evidence_event(db,event(1))
    record_quote_request(
        db,attempt_key="b1",opportunity_key="cohortA:opp:0001",
        strategy_id="S03",phase="EXIT",
        event_at="2026-10-12T14:00:01Z",source_family="SAXO_MULTILEG")
    record_quote_result(db,attempt_key="b1",
        probe_result=_fake_probe(
            status="UNVERIFIED_OR_UNAVAILABLE_PACKAGE_PRICE",
            reasons=("PACKAGE_SIZE_OR_DEPTH_NOT_PROVEN",)),
        event_at="2026-10-12T14:00:02Z")
    assert rows(db)[-1][2:4]==("SOURCE_FAILURE","UNAVAILABLE")
    assert verify_journal_chain(db)["checked"]==3


def test_denies_fake_verified_package_fill_flag(db):
    append_evidence_event(db,event(1))
    record_quote_request(
        db,attempt_key="c1",opportunity_key="cohortA:opp:0001",
        strategy_id="S03",phase="ENTRY",event_at="2026-10-12T14:00:01Z",
        source_family="SAXO_MULTILEG")
    with pytest.raises(ValueError,match="SOURCE_PROBE_PACKAGE_VERIFICATION"):
        record_quote_result(db,attempt_key="c1",
            probe_result=_fake_probe(broker_package_fill_verified=True),
            event_at="2026-10-12T14:00:02Z")
    with pytest.raises(ValueError,match="PROBE_OUTCOME_OR_TRADING"):
        record_quote_result(db,attempt_key="c1",
            probe_result=_fake_probe(outcome_eligible=True),
            event_at="2026-10-12T14:00:02Z")
    assert len(rows(db))==2


def test_readonly_saxo_leg_probe_is_observed_only(db):
    append_evidence_event(db,event(1))
    record_quote_request(
        db,attempt_key="leg1",opportunity_key="cohortA:opp:0001",
        strategy_id="S03",phase="ENTRY",event_at="2026-10-12T14:00:01Z",
        source_family="SAXO_LEG")
    p=SimpleNamespace(
        status="LEG_SAXO_DEPTH_OBSERVED_NOT_PACKAGE_EXECUTION",
        reason_codes=(),outcome_eligible=False,trading_enabled=False,
        independent_package_execution_verified=False,
        evidence_sha256="d"*64)
    record_quote_result(
        db,attempt_key="leg1",probe_result=p,
        event_at="2026-10-12T14:00:02Z")
    assert rows(db)[-1][3]=="OBSERVED_ONLY"
    assert verify_journal_chain(db)["checked"]==3


def test_quote_result_time_cannot_precede_quote_request(db):
    append_evidence_event(db,event(1))
    record_quote_request(
        db,attempt_key="d1",opportunity_key="cohortA:opp:0001",
        strategy_id="S03",phase="ENTRY",event_at="2026-10-12T14:00:05Z",
        source_family="SAXO_MULTILEG")
    with pytest.raises(ValueError,match="QUOTE_RESULT_BACKDATED"):
        record_quote_result(db,attempt_key="d1",
            probe_result=_fake_probe(),event_at="2026-10-12T14:00:04Z")
    assert len(rows(db))==2


def test_not_a_production_migration(db):
    assert "prospective_evidence_events_v1" in {
        r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert not any("outcome_eligible" in r[1] for r in db.execute(
        "PRAGMA table_info('prospective_evidence_events_v1')"))
    assert not any("broker_account_key" in r[1] for r in db.execute(
        "PRAGMA table_info('prospective_evidence_events_v1')"))
