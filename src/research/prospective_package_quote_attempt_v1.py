"""One prospective Saxo native package PRICE attempt, journaled end-to-end.

Research staging only. Requires explicit caller-provisioned staging SQLite
connection; does NOT create a production schema, run the daemon, place
orders, enable Saxo access, or score outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
import sqlite3

from src.research.prospective_evidence_journal_v1 import (
    EvidenceEvent, append_evidence_event, record_quote_request,
    record_quote_result,
)
from src.research.saxo_native_multileg_price_v1 import NativePackageQuote


@dataclass(frozen=True)
class PaperQuoteAttemptResult:
    opportunity_key: str
    attempt_key: str | None
    status: str
    quote_observed_only: bool
    outcome_eligible: bool = False
    trading_enabled: bool = False
    reason_codes: tuple[str, ...] = ()


def _now_iso(clock: Callable[[], datetime]) -> str:
    value=clock()
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("PROSPECTIVE_JOURNAL_CLOCK_NOT_AWARE")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def record_prospective_package_quote_attempt(
    *,
    journal_conn: sqlite3.Connection,
    opportunity_key: str,
    attempt_key: str,
    strategy_id: str,
    research_run_id: int,
    candidate_id: int,
    phase: str,
    price_observer: Callable[[], NativePackageQuote],
    allow_provider_observation: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> PaperQuoteAttemptResult:
    """Count the opportunity FIRST; do not hide unfillable / failed quotes.

    The caller must provide the exact source observer configured for
    PRICE-ONLY Saxo calls and the trusted observed candidate identity.
    No raw account keys, token, prices, or arbitrary exception text is
    persisted in this staging journal.
    """
    now_fn=clock or (lambda:datetime.now(timezone.utc))
    opening_at=_now_iso(now_fn)
    if phase not in ("ENTRY","EXIT"):
        raise ValueError("PROSPECTIVE_PRICE_PHASE_INVALID")
    if type(research_run_id) is not int or research_run_id<=0 or \
       type(candidate_id) is not int or candidate_id<=0:
        raise ValueError("PROSPECTIVE_CANONICAL_IDS_REQUIRED")
    if not callable(price_observer):
        raise ValueError("PROSPECTIVE_PRICE_OBSERVER_REQUIRED")
    append_evidence_event(journal_conn,EvidenceEvent(
        event_key=opportunity_key+":opened",
        opportunity_key=opportunity_key,
        strategy_id=strategy_id,phase="NONE",
        event_type="OPPORTUNITY",event_state="RECORDED",
        event_at=opening_at,source_family="NONE",
        source_evidence_sha256=None,
        candidate_id=candidate_id,research_run_id=research_run_id,
    ))
    if not allow_provider_observation:
        append_evidence_event(journal_conn,EvidenceEvent(
            event_key=opportunity_key+":not_authorized",
            opportunity_key=opportunity_key,
            strategy_id=strategy_id,phase="NONE",
            event_type="NO_TRADE",event_state="NO_TRADE",
            event_at=_now_iso(now_fn),source_family="NONE",
            source_evidence_sha256=None,
            reason_codes=("SOURCE_OBSERVATION_NOT_AUTHORIZED",),
            candidate_id=candidate_id,research_run_id=research_run_id,
        ))
        return PaperQuoteAttemptResult(
            opportunity_key=opportunity_key,attempt_key=None,
            status="NO_TRADE",quote_observed_only=False,
            reason_codes=("SOURCE_OBSERVATION_NOT_AUTHORIZED",),
        )

    record_quote_request(
        journal_conn,
        attempt_key=attempt_key,opportunity_key=opportunity_key,
        strategy_id=strategy_id,phase=phase,
        event_at=_now_iso(now_fn),source_family="SAXO_MULTILEG",
        candidate_id=candidate_id,research_run_id=research_run_id,
    )
    status="NO_TRADE"
    observed=False
    reasons: tuple[str,...]=()
    try:
        price=price_observer()
    except Exception:
        # Provider errors may contain secrets. Never copy exception payloads.
        price=None
    invalid_probe=(price is None or type(price) is not NativePackageQuote)
    if not invalid_probe:
        invalid_probe=(
            price.price_only is not True or
            price.broker_package_fill_verified is not False or
            price.outcome_eligible is not False or
            price.trading_enabled is not False or
            not isinstance(price.reasons,tuple)
        )
    if invalid_probe:
        # Record malformed / falsely verified responses as failure, instead
        # of dropping them or allowing outcome/trading flags into research.
        append_evidence_event(journal_conn,EvidenceEvent(
            event_key=attempt_key+":failed",
            opportunity_key=opportunity_key,
            strategy_id=strategy_id,phase=phase,
            event_type="SOURCE_FAILURE",event_state="UNAVAILABLE",
            event_at=_now_iso(now_fn),source_family="SAXO_MULTILEG",
            source_evidence_sha256=None,
            reason_codes=("SOURCE_PROBE_OR_EVIDENCE_VALIDATION_FAILED",),
            candidate_id=candidate_id,research_run_id=research_run_id,
        ))
        reasons=("SOURCE_PROBE_OR_EVIDENCE_VALIDATION_FAILED",)
    else:
        # A journal write or provenance contract failure MUST propagate.
        # Never reclassify a DB integrity failure as a provider-side error.
        record_quote_result(
            journal_conn,attempt_key=attempt_key,
            probe_result=price,event_at=_now_iso(now_fn),
        )
        observed=(price.status=="BROKER_PACKAGE_PRICE_REFERENCE_ONLY"
                  and price.reasons==())
        reasons=("NO_INDEPENDENT_PACKAGE_EXECUTION_RECEIPT",) if observed else (
            "NATIVE_PRICE_NOT_EXECUTABLE_QUALITY",)

    append_evidence_event(journal_conn,EvidenceEvent(
        event_key=opportunity_key+":no_trade",
        opportunity_key=opportunity_key,
        strategy_id=strategy_id,phase="NONE",
        event_type="NO_TRADE",event_state="NO_TRADE",
        event_at=_now_iso(now_fn),source_family="NONE",
        source_evidence_sha256=None,
        reason_codes=reasons,
        candidate_id=candidate_id,research_run_id=research_run_id,
    ))
    return PaperQuoteAttemptResult(
        opportunity_key=opportunity_key,attempt_key=attempt_key,
        status=status,quote_observed_only=observed,
        reason_codes=reasons,
    )
