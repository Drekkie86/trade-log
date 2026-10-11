"""Fail-closed per-leg quote-time admission gate, research-only.

Existing immutable proposals are never rewritten. Quote identity, snapshot
coherence, raw provider clock semantics and admission-time as-of are verified
before any new intrinsic-risk shadow candidate can be labelled FRESH.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from src.database.repository import get_connection
from src.research.live_pipeline import parse_thetadata_market_timestamp

QUALITY_POLICY_VERSION = "SHADOW_ENTRY_PER_LEG_ASOF_15S_V1"
# Existing first-cohort 'FRESH' contract; NOT an empirical profitability filter.
MAX_LEG_AGE_SECONDS = 15.0
MAX_SNAPSHOT_AGE_SECONDS = 15.0
MAX_LEG_QUOTE_SKEW_SECONDS = 15.0
MAX_STRUCTURE_LEGS = 8


@dataclass(frozen=True)
class EntryQuoteQuality:
    reason_code: str | None
    freshness_class: str
    evidence: dict[str, Any]


def _parse_aware(value: Any) -> datetime:
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("EXPECTED_OFFSET_AWARE_UTC_TIMESTAMP")
    return d.astimezone(timezone.utc)


def _blocked(reason: str, summary: Mapping[str, Any], legs: list[dict[str, Any]] | None = None) -> EntryQuoteQuality:
    return EntryQuoteQuality(reason, "UNKNOWN", {
        **summary, "reason_code": reason, "leg_evidence": list(legs or []),
        "eligible": False,
    })


def evaluate_entry_quote_quality(
    *,
    proposal: Mapping[str, Any],
    admission_at: str,
    db_path=None,
) -> EntryQuoteQuality:
    """Read only; indexed by exact quote IDs; no historical backfill admission."""
    summary: dict[str, Any] = {
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "max_leg_age_seconds": MAX_LEG_AGE_SECONDS,
        "max_snapshot_age_seconds": MAX_SNAPSHOT_AGE_SECONDS,
        "max_leg_quote_skew_seconds": MAX_LEG_QUOTE_SKEW_SECONDS,
        "admission_at": admission_at,
        "provider_timestamp_interpretation": "THETADATA_AMERICA_NEW_YORK_VIA_VERIFIED_PROBE",
    }
    try:
        decision = _parse_aware(admission_at)
        data = json.loads(str(proposal["structure_json"]))
        legs = data["legs"]
        if (not isinstance(legs, list) or not 1 <= len(legs) <= MAX_STRUCTURE_LEGS):
            return _blocked("ENTRY_LEG_COUNT_INVALID", summary)
        ids = []
        for leg in legs:
            ids.append(int(leg["option_quote_id"]))
        if len(set(ids)) != len(ids):
            return _blocked("ENTRY_LEG_QUOTE_IDS_REUSED", summary)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return _blocked("ENTRY_STRUCTURE_TIMESTAMP_OR_LEGS_INVALID", summary)

    conn = get_connection(db_path)
    try:
        # A documented parser alone is not proof of the provider's live
        # timestamp semantics. Most recent validation must have passed LIVE.
        semantics = conn.execute(
            """SELECT id,validated_at,confidence_state,live_probe_state,
                      aware_conversion_pass,dst_contract_pass,
                      documentation_contract_pass,documented_market_timezone
               FROM thetadata_timestamp_semantics_v1_runs
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        if semantics is None:
            return _blocked("ENTRY_PROVIDER_CLOCK_UNVERIFIED", summary)
        summary["timestamp_semantics_validation_id"] = int(semantics["id"])
        try:
            validation_at = _parse_aware(semantics["validated_at"])
        except ValueError:
            return _blocked("ENTRY_PROVIDER_CLOCK_UNVERIFIED", summary)
        if (validation_at > decision or
                semantics["confidence_state"] != "DOCUMENTED_AND_LIVE_VALIDATED" or
                semantics["live_probe_state"] != "PASSED" or
                int(semantics["aware_conversion_pass"]) != 1 or
                int(semantics["dst_contract_pass"]) != 1 or
                int(semantics["documentation_contract_pass"]) != 1 or
                semantics["documented_market_timezone"] != "America/New_York"):
            return _blocked("ENTRY_PROVIDER_CLOCK_UNVERIFIED", summary)

        # Exact key lookups only; no scan of millions of option observations.
        # The row's snapshot is constrained to the candidate's research run.
        rows = {}
        for qid in ids:
            row = conn.execute(
                """SELECT oq.id,oq.snapshot_id,oq.right,oq.strike,oq.expiration,
                          oq.quote_at,oq.bid,oq.ask,oq.bid_at,oq.ask_at,
                          oq.bid_source,oq.ask_source,
                          ms.captured_at,ms.research_run_id,
                          ms.underlying,ms.provider
                   FROM option_quotes AS oq
                   JOIN market_snapshots AS ms ON ms.id=oq.snapshot_id
                   WHERE oq.id=? LIMIT 1""",
                (qid,),
            ).fetchone()
            if row is None:
                return _blocked("ENTRY_LEG_SOURCE_QUOTE_MISSING", summary)
            rows[qid] = dict(row)
    finally:
        conn.close()

    evidence = []
    snapshots = set()
    quote_times: list[datetime] = []
    for leg in legs:
        row = rows[int(leg["option_quote_id"])]
        if (row["provider"] != "THETADATA" or
                row["research_run_id"] != int(proposal["research_run_id"]) or
                row["underlying"] != str(proposal["underlying"])):
            return _blocked("ENTRY_LEG_QUOTE_SNAPSHOT_OR_RUN_MISMATCH", summary, evidence)
        try:
            if (str(row["right"]) != str(leg["right"]) or
                    str(row["expiration"]) != str(proposal["expiration"]) or
                    not math.isclose(float(row["strike"]), float(leg["strike"]),abs_tol=1e-6,rel_tol=0)):
                return _blocked("ENTRY_LEG_OPTION_IDENTITY_MISMATCH",summary,evidence)
            if (int(leg["quantity"]) < 1 or str(leg["side"]) not in ("BUY","SELL")):
                return _blocked("ENTRY_LEG_CONTRACT_QUANTITY_OR_SIDE_INVALID",summary,evidence)
            if (row["bid"] is None or row["ask"] is None or
                    not (math.isfinite(float(row["bid"])) and math.isfinite(float(row["ask"]))) or
                    float(row["bid"]) < 0 or float(row["ask"]) < float(row["bid"]) or
                    row["bid_source"] != "FETCHED" or row["ask_source"] != "FETCHED"):
                return _blocked("ENTRY_LEG_BID_ASK_UNVERIFIED",summary,evidence)
            # Source quote timestamp AND side-specific quote timestamps must
            # each be present; never use a fresh snapshot timestamp to bless
            # old individual bid/ask values.
            quote_time = parse_thetadata_market_timestamp(str(row["quote_at"])).astimezone(timezone.utc)
            bid_time = parse_thetadata_market_timestamp(str(row["bid_at"])).astimezone(timezone.utc)
            ask_time = parse_thetadata_market_timestamp(str(row["ask_at"])).astimezone(timezone.utc)
            capture_time = _parse_aware(row["captured_at"])
        except (ValueError, KeyError, TypeError, OverflowError):
            return _blocked("ENTRY_LEG_TIMESTAMP_OR_PRICE_UNPARSEABLE",summary,evidence)
        snapshots.add(int(row["snapshot_id"]))
        ages = {
            "quote_age_seconds": round((decision-quote_time).total_seconds(),3),
            "bid_age_seconds": round((decision-bid_time).total_seconds(),3),
            "ask_age_seconds": round((decision-ask_time).total_seconds(),3),
            "snapshot_age_seconds": round((decision-capture_time).total_seconds(),3),
        }
        evidence.append({"quote_id":int(row["id"]),"snapshot_id":int(row["snapshot_id"]),
                         "side":str(leg["side"]),**ages})
        quote_times.extend((quote_time,bid_time,ask_time))
        if any(age < 0 for age in ages.values()):
            return _blocked("ENTRY_LEG_FUTURE_SOURCE_TIMESTAMP",summary,evidence)
        if ages["snapshot_age_seconds"]>MAX_SNAPSHOT_AGE_SECONDS:
            return _blocked("ENTRY_SNAPSHOT_STALE_AT_ADMISSION",summary,evidence)
        if max(ages[k] for k in ("quote_age_seconds","bid_age_seconds","ask_age_seconds"))>MAX_LEG_AGE_SECONDS:
            return _blocked("ENTRY_LEG_STALE_AT_ADMISSION",summary,evidence)
        if max(quote_time,bid_time,ask_time) > capture_time:
            return _blocked("ENTRY_LEG_SOURCE_AFTER_CAPTURE",summary,evidence)
    if len(snapshots) != 1:
        return _blocked("ENTRY_LEG_MULTIPLE_SNAPSHOTS",summary,evidence)
    if ((max(quote_times)-min(quote_times)).total_seconds() >
            MAX_LEG_QUOTE_SKEW_SECONDS):
        return _blocked("ENTRY_LEG_ASYNCHRONOUS_TIMESTAMPS",summary,evidence)
    return EntryQuoteQuality(None, "FRESH", {
        **summary, "eligible": True,"reason_code": None,"leg_evidence": evidence,
        "same_snapshot": True,"leg_count": len(evidence),
    })
