"""Bounded, read-only Saxo option-depth observation for a single shadow candidate.

Acquires independent leg prices only. Never submits orders, writes to SQLite,
or emits a VALIDATED_PACKAGE_OUTCOME; no trade outcome can be inferred.
The caller must explicitly enable provider GET requests.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote as urlquote
from zoneinfo import ZoneInfo

from src.operations.market_calendar import get_market_session
from src.providers.saxo import QuoteQuality

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
VERSION = "BOUNDED_SAXO_CANDIDATE_LEG_SAMPLE_V1"
MAX_LEGS = 4
MAX_SOURCE_AGE_SECONDS = 15
MAX_CROSS_LEG_SKEW_SECONDS = 15
MAX_SQL_TIME_SECONDS = 1.0


def _parse_aware(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("MISSING_PROVIDER_TIMESTAMP")
    val = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if val.tzinfo is None or val.utcoffset() is None:
        raise ValueError("AMBIGUOUS_PROVIDER_TIMESTAMP")
    return val.astimezone(UTC)


@dataclass(frozen=True)
class FrozenLeg:
    option_quote_id: int
    underlying: str
    right: str
    strike: float
    expiration: str
    shares_per_contract: float
    quantity: int
    side: str


@dataclass(frozen=True)
class SaxoLegEvidence:
    option_quote_id: int
    saxo_uic: int
    underlying: str
    right: str
    strike: float
    expiration: str
    provider_quote_at: str
    request_started_at: str
    request_completed_at: str
    bid: float | None
    ask: float | None
    bid_size: float | None
    ask_size: float | None
    quote_quality: str
    declared_is_executable: bool
    quote_age_seconds: float | None
    provider_quote_source: str | None
    quote_source_type: str | None
    market_state: str | None


@dataclass(frozen=True)
class CandidateSaxoSample:
    candidate_id: int
    captured_at: str
    status: str
    reason_codes: tuple[str, ...]
    legs_requested: int
    legs_observed: int
    leg_evidence: tuple[SaxoLegEvidence, ...]
    source_contract: str
    observation_only: bool
    independent_package_execution_verified: bool
    outcome_eligible: bool
    trading_enabled: bool
    evidence_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finish(
    candidate_id: int,
    when: datetime,
    legs_requested: int,
    observations: list[SaxoLegEvidence],
    reasons: set[str],
) -> CandidateSaxoSample:
    # Calculated only after sampling: source evidence is a *leg* reference.
    status = (
        "LEG_SAXO_DEPTH_OBSERVED_NOT_PACKAGE_EXECUTION"
        if not reasons and len(observations) == legs_requested
        else "BLOCKED_OR_INCOMPLETE_SAXO_EVIDENCE"
    )
    payload = {
        "candidate_id": candidate_id,
        "captured_at": when.isoformat(),
        "status": status,
        "reasons": sorted(reasons),
        "legs_requested": legs_requested,
        "legs_observed": len(observations),
        "leg_evidence": [asdict(v) for v in observations],
        "source_contract": VERSION,
    }
    digest = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return CandidateSaxoSample(
        candidate_id=candidate_id,
        captured_at=when.isoformat(),
        status=status,
        reason_codes=tuple(sorted(reasons)),
        legs_requested=legs_requested,
        legs_observed=len(observations),
        leg_evidence=tuple(observations),
        source_contract=VERSION,
        observation_only=True,
        independent_package_execution_verified=False,
        outcome_eligible=False,
        trading_enabled=False,
        evidence_sha256=digest,
    )


def _candidate_legs(candidate_id: int, db_path: str | Path) -> tuple[list[FrozenLeg], str | None]:
    """Read immutable source and latest lifecycle; no table scans or writes."""
    path = Path(db_path).resolve()
    if not path.is_file():
        raise ValueError("READ_ONLY_DATABASE_NOT_FOUND")
    conn = sqlite3.connect(
        "file:" + urlquote(path.as_posix(), safe="/:") + "?mode=ro",
        uri=True, timeout=0.5,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    start = time.monotonic()
    conn.set_progress_handler(
        lambda: int(time.monotonic() - start > MAX_SQL_TIME_SECONDS), 1000)
    try:
        row = conn.execute(
            """SELECT sc.id,sc.underlying,sc.structure_json,sc.research_run_id,
                      lrc.expiration,
                      (SELECT se.to_state FROM shadow_state_events AS se
                       WHERE se.candidate_id=sc.id ORDER BY se.id DESC LIMIT 1)
                       AS lifecycle_state
               FROM shadow_candidates AS sc
               JOIN listing_reference_contracts AS lrc
                 ON lrc.id=sc.reference_contract_id
               WHERE sc.id=? LIMIT 1""",
            (candidate_id,),
        ).fetchone()
        if row is None:
            return [], "CANDIDATE_NOT_FOUND"
        if row["lifecycle_state"] != "SHADOW_TRACKED":
            return [], "CANDIDATE_NOT_ACTIVE_SHADOW_TRACKED"
        structure = json.loads(row["structure_json"])
        raw_legs = structure["legs"]
        if not isinstance(raw_legs, list) or not 2 <= len(raw_legs) <= MAX_LEGS:
            return [], "CANDIDATE_LEG_COUNT_UNSUPPORTED"
        legs: list[FrozenLeg] = []
        ids: set[int] = set()
        for raw in raw_legs:
            qid = int(raw["option_quote_id"])
            right = str(raw["right"])
            strike = float(raw["strike"])
            qty = raw["quantity"]
            multiplier = float(raw["shares_per_contract"])
            side = str(raw["side"])
            if (qid <= 0 or qid in ids or right not in ("C", "P")
                    or not math.isfinite(strike) or strike <= 0
                    or not math.isfinite(multiplier) or multiplier <= 0
                    or type(qty) is not int or qty <= 0 or qty > 10
                    or side not in ("BUY", "SELL")):
                return [], "FROZEN_CANDIDATE_LEG_INVALID_OR_DUPLICATE"
            ids.add(qid)
            legs.append(FrozenLeg(
                option_quote_id=qid,
                underlying=str(row["underlying"]),
                right=right,
                strike=strike,
                expiration=str(row["expiration"]),
                shares_per_contract=multiplier,
                quantity=qty,
                side=side,
            ))
        if len({(leg.right, leg.strike, leg.expiration) for leg in legs}) != len(legs):
            return [], "FROZEN_LEG_INSTRUMENT_DUPLICATED"
        return legs, None
    except (ValueError, KeyError, TypeError, sqlite3.Error, OverflowError):
        return [], "FROZEN_CANDIDATE_SOURCE_UNPARSEABLE"
    finally:
        conn.close()


def capture_candidate_saxo_depth(
    *,
    candidate_id: int,
    db_path: str | Path,
    saxo_client: Any,
    allow_provider_get: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> CandidateSaxoSample:
    """Saxo read-only API calls, explicitly opt-in. No persisted evidence.

    This is an *observation experiment*, never a simulated fill or order.
    A successful source check cannot independently validate a complex order.
    """
    now_fn = clock or (lambda: datetime.now(UTC))
    now = now_fn()
    if type(candidate_id) is not int or candidate_id <= 0:
        raise ValueError("INVALID_CANDIDATE_ID")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("SAMPLING_CLOCK_MUST_HAVE_TIMEZONE")
    now = now.astimezone(UTC)
    if not allow_provider_get:
        return _finish(candidate_id, now, 0, [], {"PROVIDER_READS_NOT_AUTHORIZED"})

    market_day = now.astimezone(NY).date()
    session = get_market_session(market_day)
    if session is None:
        return _finish(candidate_id, now, 0, [], {"XNYS_MARKET_CLOSED"})
    window_open = _parse_aware(session.sample_window_start)
    window_close = _parse_aware(session.sample_window_end)
    if not (window_open <= now <= window_close):
        return _finish(candidate_id, now, 0, [], {"OUTSIDE_XNYS_SAMPLE_WINDOW"})

    legs, load_error = _candidate_legs(candidate_id, db_path)
    if load_error:
        return _finish(candidate_id, now, 0, [], {load_error})
    if any(l.expiration < market_day.isoformat() for l in legs):
        return _finish(candidate_id, now, len(legs), [], {"CONTRACT_ALREADY_EXPIRED"})

    evidence: list[SaxoLegEvidence] = []
    reasons: set[str] = set()
    quote_moments: list[datetime] = []
    for leg in legs:
        began = now_fn()
        if began.tzinfo is None or began.utcoffset() is None:
            reasons.add("SAMPLING_CLOCK_UNVERIFIED")
            break
        began = began.astimezone(UTC)
        try:
            contract, quote = saxo_client.get_option_contract_and_quote(
                underlying=leg.underlying,
                expiration=leg.expiration,
                strike=leg.strike,
                put_call="Call" if leg.right == "C" else "Put",
            )
        except Exception:
            # Failure type only: exception bodies may contain provider secrets.
            reasons.add("SAXO_PROVIDER_READ_OR_RESOLUTION_FAILED")
            break
        completed = now_fn()
        if completed.tzinfo is None or completed.utcoffset() is None:
            reasons.add("SAMPLING_CLOCK_UNVERIFIED")
            break
        completed = completed.astimezone(UTC)
        try:
            contract_right = str(contract.put_call).strip().upper()
            if (completed < began or
                    completed < now or
                    completed > window_close or
                    contract.underlying.upper() != leg.underlying.upper() or
                    contract.expiration != leg.expiration or
                    contract_right not in ("CALL", "C", "PUT", "P") or
                    ("C" if contract_right in ("CALL", "C") else "P")
                    != leg.right or
                    not math.isclose(float(contract.strike), leg.strike, abs_tol=1e-6)
                    or not math.isclose(float(contract.contract_size),
                                        leg.shares_per_contract, abs_tol=1e-6)
                    or quote.uic != contract.uic):
                reasons.add("SAXO_CONTRACT_OR_ACQUISITION_IDENTITY_INVALID")
                break
            observed_at = _parse_aware(quote.last_updated)
            age = (completed - observed_at).total_seconds()
            if age < 0 or age > MAX_SOURCE_AGE_SECONDS:
                reasons.add("SAXO_QUOTE_SOURCE_TIMESTAMP_STALE_OR_FUTURE")
            if observed_at < began and (began-observed_at).total_seconds() > MAX_SOURCE_AGE_SECONDS:
                reasons.add("SAXO_QUOTE_STALE_AT_FETCH_START")
            if (quote.quality != QuoteQuality.EXECUTABLE or
                    not quote.is_executable or
                    contract.trading_status is None or
                    str(contract.trading_status).strip().upper() not in
                    ("TRADABLE", "TRADEABLE")):
                reasons.add("SAXO_QUOTE_NOT_EXECUTABLE_QUALITY")
            vals = (quote.bid, quote.ask, quote.bid_size, quote.ask_size)
            if any(v is None or not math.isfinite(float(v)) for v in vals):
                reasons.add("SAXO_BID_ASK_SIZE_MISSING")
            else:
                bid, ask, bid_size, ask_size = [float(v) for v in vals]
                if bid <= 0 or ask < bid or bid_size < leg.quantity or ask_size < leg.quantity:
                    reasons.add("SAXO_BID_ASK_OR_DEPTH_INSUFFICIENT")
            if age >= 0:
                quote_moments.append(observed_at)
            evidence.append(SaxoLegEvidence(
                option_quote_id=leg.option_quote_id,
                saxo_uic=int(contract.uic),
                underlying=leg.underlying,
                right=leg.right,
                strike=leg.strike,
                expiration=leg.expiration,
                provider_quote_at=observed_at.isoformat(),
                request_started_at=began.isoformat(),
                request_completed_at=completed.isoformat(),
                bid=quote.bid, ask=quote.ask,
                bid_size=quote.bid_size, ask_size=quote.ask_size,
                quote_quality=quote.quality.value,
                declared_is_executable=quote.is_executable,
                quote_age_seconds=round(age, 3),
                provider_quote_source=quote.price_source,
                quote_source_type=quote.price_source_type,
                market_state=quote.market_state,
            ))
            if reasons:
                break  # fail fast: do not generate expensive secondary reads
        except (ValueError, TypeError, AttributeError, OverflowError):
            reasons.add("SAXO_PROVIDER_RESPONSE_UNVERIFIABLE")
            break
    if quote_moments and (
        max(quote_moments) - min(quote_moments)
    ).total_seconds() > MAX_CROSS_LEG_SKEW_SECONDS:
        reasons.add("SAXO_LEG_TIMESTAMPS_NOT_SYNCHRONIZED")
    if len(evidence) != len(legs):
        reasons.add("SAXO_LEG_POPULATION_INCOMPLETE")
    return _finish(candidate_id, now, len(legs), evidence, reasons)
