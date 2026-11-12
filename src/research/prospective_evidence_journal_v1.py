"""Append-only prospectively acquired price-evidence event journal (staged).

Works only on a caller-supplied SQLite connection with explicit reference
schema preinstalled. NO migrations, production setup or broker interactions.
Never sets outcome_eligible, score, win rate or P&L.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

ZERO_HASH = "0" * 64
MAX_REASONS = 12
MAX_AUDIT_ROWS = 1000
ALLOWED_PHASES = frozenset(("NONE","ENTRY","EXIT"))
ALLOWED_EVENTS = frozenset((
    "OPPORTUNITY","PRICE_REQUEST","MARKET_REFERENCE","NO_TRADE",
    "SOURCE_FAILURE","REJECTION",
))
ALLOWED_STATES = frozenset((
    "RECORDED","UNAVAILABLE","REJECTED","OBSERVED_ONLY","NO_TRADE",
))
ALLOWED_SOURCES = frozenset((
    "NONE","SAXO_LEG","SAXO_MULTILEG","THETADATA",
    "BROKER_PAPER_RECEIPT_REFERENCE",
))
ALLOWED_TRANSITIONS = {
    "MARKET_REFERENCE":"OBSERVED_ONLY",
    "NO_TRADE":"NO_TRADE",
    "SOURCE_FAILURE":"UNAVAILABLE",
    "REJECTION":"REJECTED",
}
SAFE_KEY = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")
SAFE_REASON = re.compile(r"^[A-Z0-9_]{2,90}$")
SHA = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class EvidenceEvent:
    event_key: str
    opportunity_key: str
    strategy_id: str
    phase: str
    event_type: str
    event_state: str
    event_at: str
    source_family: str
    source_evidence_sha256: str | None
    reason_codes: tuple[str, ...] = ()
    candidate_id: int | None = None
    research_run_id: int | None = None


def _utc(value: str) -> str:
    try:
        v=datetime.fromisoformat(value.replace("Z","+00:00"))
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("NAIVE_TIME")
        return v.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    except (AttributeError,TypeError,ValueError) as exc:
        raise ValueError("EVENT_TIMESTAMP_MUST_BE_EXPLICITLY_OFFSET_AWARE") from exc


def _canonical(v: dict[str, Any]) -> str:
    return json.dumps(v,sort_keys=True, separators=(",",":"),ensure_ascii=True,
                      allow_nan=False)


def _fields(event: EvidenceEvent) -> dict[str, Any]:
    """Strict allowlist: no raw account keys, broker tokens, or free text."""
    for field_name in ("event_key","opportunity_key","strategy_id"):
        v=getattr(event,field_name)
        if not isinstance(v,str) or not SAFE_KEY.fullmatch(v):
            raise ValueError("UNSAFE_OR_MISSING_"+field_name.upper())
    if (event.phase not in ALLOWED_PHASES or
            event.event_type not in ALLOWED_EVENTS or
            event.event_state not in ALLOWED_STATES or
            event.source_family not in ALLOWED_SOURCES):
        raise ValueError("UNKNOWN_PHASE_TYPE_STATE_OR_SOURCE")
    mandatory=ALLOWED_TRANSITIONS.get(event.event_type)
    if mandatory and event.event_state!=mandatory:
        raise ValueError("EVENT_TYPE_STATE_MISMATCH")
    for k in ("candidate_id","research_run_id"):
        n=getattr(event,k)
        if n is not None and (type(n) is not int or n<=0):
            raise ValueError("INVALID_"+k.upper())
    if (type(event.reason_codes) is not tuple or
            len(event.reason_codes)>MAX_REASONS or
            len(set(event.reason_codes))!=len(event.reason_codes) or
            any(not isinstance(v,str) or not SAFE_REASON.fullmatch(v)
                for v in event.reason_codes)):
        raise ValueError("INVALID_REASON_CODES")
    if event.source_evidence_sha256 is not None and (
            not isinstance(event.source_evidence_sha256,str) or
            not SHA.fullmatch(event.source_evidence_sha256)):
        raise ValueError("SOURCE_DIGEST_NOT_SHA256")
    if event.event_type=="MARKET_REFERENCE" and (
            event.source_evidence_sha256 is None or
            event.source_family=="NONE" or event.phase=="NONE"):
        raise ValueError("MARKET_REFERENCE_REQUIRES_VERIFIABLE_SOURCE_AND_PHASE")
    if event.event_type=="NO_TRADE" and not event.reason_codes:
        raise ValueError("NO_TRADE_REQUIRES_EXPLICIT_REASON")
    return {
        "event_key":event.event_key,
        "opportunity_key":event.opportunity_key,
        "candidate_id":event.candidate_id,
        "research_run_id":event.research_run_id,
        "strategy_id":event.strategy_id,
        "phase":event.phase,
        "event_type":event.event_type,
        "event_state":event.event_state,
        "event_at":_utc(event.event_at),
        "source_family":event.source_family,
        "source_evidence_sha256":event.source_evidence_sha256,
        "reason_codes_json":_canonical(list(event.reason_codes)),
    }


def _digest(fields: dict[str,Any],previous_hash: str) -> str:
    return hashlib.sha256(_canonical({
        "event":fields,
        "previous_hash_sha256":previous_hash
    }).encode("utf-8")).hexdigest()


def append_evidence_event(conn: sqlite3.Connection,event: EvidenceEvent) -> int:
    """Append atomically with predecessor; fail on duplicate, no hidden overwrite.

    The caller must explicitly initialize a staging DB using the reference
    SQL. No schema is installed automatically on production.
    """
    if conn.in_transaction:
        raise ValueError("JOURNAL_WRITER_REQUIRES_OWN_TRANSACTION")
    fields=_fields(event)
    conn.execute("BEGIN IMMEDIATE")
    try:
        current=conn.execute(
            "SELECT event_hash_sha256 FROM prospective_evidence_events_v1 "
            "ORDER BY id DESC LIMIT 1").fetchone()
        predecessor=ZERO_HASH if current is None else str(current[0])
        digest=_digest(fields,predecessor)
        cursor=conn.execute(
            """INSERT INTO prospective_evidence_events_v1 (
                event_key,opportunity_key,candidate_id,research_run_id,
                strategy_id,phase,event_type,event_state,event_at,
                source_family,source_evidence_sha256,reason_codes_json,
                previous_hash_sha256,event_hash_sha256
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*fields.values(),predecessor,digest),
        )
        conn.commit()
        return int(cursor.lastrowid)
    except BaseException:
        conn.rollback()
        raise




def record_quote_request(
    conn: sqlite3.Connection, *,
    attempt_key: str, opportunity_key: str, strategy_id: str,
    phase: str, event_at: str, source_family: str,
    candidate_id: int | None = None, research_run_id: int | None = None,
) -> int:
    """Record intent BEFORE a source call; no provider access here."""
    if source_family not in ("SAXO_LEG","SAXO_MULTILEG"):
        raise ValueError("UNSUPPORTED_BROKER_SOURCE_FAMILY")
    if phase not in ("ENTRY","EXIT"):
        raise ValueError("QUOTE_REQUEST_NEEDS_ENTRY_OR_EXIT_PHASE")
    return append_evidence_event(conn,EvidenceEvent(
        event_key=attempt_key+":request",
        opportunity_key=opportunity_key,
        strategy_id=strategy_id,
        phase=phase,
        event_type="PRICE_REQUEST",
        event_state="RECORDED",
        event_at=event_at,
        source_family=source_family,
        source_evidence_sha256=None,
        candidate_id=candidate_id,
        research_run_id=research_run_id,
    ))


def record_quote_result(
    conn: sqlite3.Connection, *,
    attempt_key: str,
    probe_result: Any,
    event_at: str,
) -> int:
    """Persist only allowlisted fields from source probes, NEVER fills.

    Accepts previous Saxo per-leg/native package probe result shape via
    read-only typed access. A result must follow a pre-existing PRICE_REQUEST.
    A source error always remains an explicit failure in the denominator.
    """
    if not isinstance(attempt_key,str) or not SAFE_KEY.fullmatch(attempt_key):
        raise ValueError("UNSAFE_ATTEMPT_KEY")
    request=conn.execute(
        """SELECT opportunity_key,strategy_id,phase,source_family,
                  candidate_id,research_run_id,event_at
           FROM prospective_evidence_events_v1
           WHERE event_key=? AND event_type='PRICE_REQUEST' LIMIT 1""",
        (attempt_key+":request",),
    ).fetchone()
    if request is None:
        raise ValueError("QUOTE_RESULT_WITHOUT_REQUEST")
    (
        opportunity_key,strategy_id,phase,source_family,
        candidate_id,research_run_id,request_at
    )=request
    if _utc(event_at)<request_at:
        raise ValueError("QUOTE_RESULT_BACKDATED_BEFORE_REQUEST")
    if any(getattr(probe_result,name,None) is not False for name in
           ("outcome_eligible","trading_enabled")):
        raise ValueError("PROBE_OUTCOME_OR_TRADING_NOT_EXPLICITLY_DISABLED")
    if source_family=="SAXO_LEG":
        qualified_state="LEG_SAXO_DEPTH_OBSERVED_NOT_PACKAGE_EXECUTION"
        if getattr(probe_result,"independent_package_execution_verified",None) is not False:
            raise ValueError("SOURCE_PROBE_PACKAGE_VERIFICATION_NOT_DISABLED")
        reason_tuple=getattr(probe_result,"reason_codes",None)
    elif source_family=="SAXO_MULTILEG":
        qualified_state="BROKER_PACKAGE_PRICE_REFERENCE_ONLY"
        if getattr(probe_result,"broker_package_fill_verified",None) is not False:
            raise ValueError("SOURCE_PROBE_PACKAGE_VERIFICATION_NOT_DISABLED")
        reason_tuple=getattr(probe_result,"reasons",None)
    else:
        raise ValueError("QUOTE_RESULT_UNSUPPORTED_SOURCE")
    if not isinstance(reason_tuple,tuple):
        raise ValueError("QUOTE_PROBE_REASON_CODES_INVALID")
    status=getattr(probe_result,"status",None)
    digest=getattr(probe_result,"evidence_sha256",None)
    if not isinstance(digest,str) or not SHA.fullmatch(digest):
        raise ValueError("QUOTE_PROBE_SOURCE_DIGEST_MISSING")
    is_observed=(status==qualified_state and not reason_tuple)
    if is_observed:
        event_type="MARKET_REFERENCE"
        state="OBSERVED_ONLY"
        reasons=()
    else:
        event_type="SOURCE_FAILURE"
        state="UNAVAILABLE"
        reasons=reason_tuple or ("PROBE_NOT_QUALIFIED",)
    return append_evidence_event(conn,EvidenceEvent(
        event_key=attempt_key+":result",
        opportunity_key=str(opportunity_key),
        strategy_id=str(strategy_id),
        phase=str(phase),
        event_type=event_type,
        event_state=state,
        event_at=event_at,
        source_family=str(source_family),
        source_evidence_sha256=digest,
        reason_codes=reasons,
        candidate_id=candidate_id,
        research_run_id=research_run_id,
    ))

def verify_journal_chain(conn: sqlite3.Connection, *, max_rows: int=MAX_AUDIT_ROWS) -> dict[str,Any]:
    """Bounded consistency check; hash chains do not authenticate the provider."""
    if type(max_rows) is not int or not 1<=max_rows<=MAX_AUDIT_ROWS:
        raise ValueError("JOURNAL_AUDIT_BOUND_INVALID")
    rows=conn.execute(
        """SELECT event_key,opportunity_key,candidate_id,research_run_id,
                  strategy_id,phase,event_type,event_state,event_at,
                  source_family,source_evidence_sha256,reason_codes_json,
                  previous_hash_sha256,event_hash_sha256
           FROM prospective_evidence_events_v1
           ORDER BY id ASC LIMIT ?""",(max_rows+1,),
    ).fetchall()
    if len(rows)>max_rows:
        return {"status":"AUDIT_LIMIT_REACHED","checked":0,"limit":max_rows}
    previous=ZERO_HASH
    keys=("event_key","opportunity_key","candidate_id","research_run_id",
          "strategy_id","phase","event_type","event_state","event_at",
          "source_family","source_evidence_sha256","reason_codes_json")
    for i,row in enumerate(rows):
        event_fields=dict(zip(keys,row[:12]))
        expected=_digest(event_fields,previous)
        if row[12]!=previous or row[13]!=expected:
            return {"status":"INTEGRITY_MISMATCH","row_number":i+1}
        previous=str(row[13])
    return {"status":"HASH_CHAIN_CONSISTENT_ONLY_NOT_EXTERNALLY_VERIFIED",
            "checked":len(rows),"head_sha256":previous}
