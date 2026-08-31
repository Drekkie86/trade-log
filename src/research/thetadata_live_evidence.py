from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.database.repository import (
    record_provider_observation_availability,
    record_unmatched_provider_contract_observation,
)
from src.research.shadow_lifecycle import (
    FreshnessClass,
    GreekQuality,
    classify_freshness,
    classify_greek_quality,
)


class ThetaLiveEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class ThetaJoinedEvidence:
    reference_contract_id: int
    canonical_identity: tuple[str, str, float, str]
    quote_state: str
    greek_state: str
    quote_freshness: FreshnessClass
    greek_quality: GreekQuality
    quote_row: Mapping[str, Any] | None
    greek_row: Mapping[str, Any] | None


def canonical_option_identity(
    row: Mapping[str, Any],
) -> tuple[str, str, float, str]:
    """
    Normalize an option identity to:
    (UNDERLYING, YYYY-MM-DD, strike, C|P).
    """

    try:
        underlying = str(row["underlying"]).strip().upper()
        expiration = str(row["expiration"]).strip()
        strike = float(row["strike"])
        raw_right = str(row["right"]).strip().upper()
    except (KeyError, TypeError, ValueError) as exc:
        raise ThetaLiveEvidenceError(
            f"Cannot build canonical option identity from row: {row}"
        ) from exc

    if raw_right in {"C", "CALL"}:
        right = "C"
    elif raw_right in {"P", "PUT"}:
        right = "P"
    else:
        raise ThetaLiveEvidenceError(
            f"Unexpected option right: {raw_right}"
        )

    if not underlying:
        raise ThetaLiveEvidenceError(
            "Underlying cannot be blank."
        )

    return underlying, expiration, strike, right


def _unique_by_identity(
    rows: list[Mapping[str, Any]],
    *,
    label: str,
) -> dict[tuple[str, str, float, str], Mapping[str, Any]]:
    result: dict[
        tuple[str, str, float, str],
        Mapping[str, Any],
    ] = {}

    for row in rows:
        identity = canonical_option_identity(row)
        if identity in result:
            raise ThetaLiveEvidenceError(
                f"Duplicate {label} identity: {identity}"
            )
        result[identity] = row

    return result


def join_thetadata_live_evidence(
    *,
    reference_contracts: list[Mapping[str, Any]],
    quote_rows: list[Mapping[str, Any]],
    greek_rows: list[Mapping[str, Any]],
) -> tuple[ThetaJoinedEvidence, ...]:
    """
    Join ThetaData quote and Greek evidence onto persisted
    listing-reference contracts.

    Freshness is derived only from an explicit
    `quote_age_seconds` value already calculated by a caller
    whose timestamp semantics are verified.

    Greek snapshot recency is deliberately ignored.
    """

    quotes = _unique_by_identity(
        quote_rows,
        label="ThetaData quote",
    )
    greeks = _unique_by_identity(
        greek_rows,
        label="ThetaData Greek",
    )

    joined: list[ThetaJoinedEvidence] = []

    seen_reference: set[
        tuple[str, str, float, str]
    ] = set()

    for reference in reference_contracts:
        identity = canonical_option_identity(reference)

        if identity in seen_reference:
            raise ThetaLiveEvidenceError(
                f"Duplicate reference identity: {identity}"
            )
        seen_reference.add(identity)

        try:
            reference_id = int(reference["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ThetaLiveEvidenceError(
                "Reference contract requires integer id."
            ) from exc

        quote = quotes.get(identity)
        greek = greeks.get(identity)

        if quote is None:
            quote_state = "ABSENT"
            quote_freshness = FreshnessClass.UNKNOWN
        else:
            quote_state = "PRESENT"
            quote_freshness = classify_freshness(
                quote.get("quote_age_seconds")
            )

        if greek is None:
            greek_state = "ABSENT"
            greek_quality = GreekQuality.UNKNOWN
        else:
            greek_state = "PRESENT"
            greek_quality = classify_greek_quality(
                greek.get("iv_error")
            )

        joined.append(
            ThetaJoinedEvidence(
                reference_contract_id=reference_id,
                canonical_identity=identity,
                quote_state=quote_state,
                greek_state=greek_state,
                quote_freshness=quote_freshness,
                greek_quality=greek_quality,
                quote_row=quote,
                greek_row=greek,
            )
        )

    return tuple(joined)


def persist_thetadata_live_availability(
    *,
    joined: tuple[ThetaJoinedEvidence, ...],
    observed_at: str,
    db_path=None,
) -> dict[str, int]:
    """
    Persist quote/Greek PRESENT or ABSENT states.

    This stores observation availability only.
    Full quote/Greek payload persistence remains separate.
    """

    counts = {
        "quote_present": 0,
        "quote_absent": 0,
        "greek_present": 0,
        "greek_absent": 0,
    }

    for item in joined:
        quote_reason = (
            None
            if item.quote_state == "PRESENT"
            else "QUOTE_OBSERVATION_ABSENT"
        )

        record_provider_observation_availability(
            {
                "reference_contract_id":
                    item.reference_contract_id,
                "provider":
                    "THETADATA",
                "evidence_family":
                    "THETADATA_QUOTE",
                "state":
                    item.quote_state,
                "reason_code":
                    quote_reason,
                "reason_detail":
                    f"freshness={item.quote_freshness.value}",
                "observed_at":
                    observed_at,
                "raw_timestamp":
                    None
                    if item.quote_row is None
                    else item.quote_row.get("raw_timestamp"),
            },
            db_path=db_path,
        )

        counts[
            "quote_present"
            if item.quote_state == "PRESENT"
            else "quote_absent"
        ] += 1

        greek_reason = (
            None
            if item.greek_state == "PRESENT"
            else "MODEL_OBSERVATION_ABSENT"
        )

        record_provider_observation_availability(
            {
                "reference_contract_id":
                    item.reference_contract_id,
                "provider":
                    "THETADATA",
                "evidence_family":
                    "THETADATA_GREEKS",
                "state":
                    item.greek_state,
                "reason_code":
                    greek_reason,
                "reason_detail":
                    f"greek_quality={item.greek_quality.value}",
                "observed_at":
                    observed_at,
                "raw_timestamp":
                    None
                    if item.greek_row is None
                    else item.greek_row.get("raw_timestamp"),
            },
            db_path=db_path,
        )

        counts[
            "greek_present"
            if item.greek_state == "PRESENT"
            else "greek_absent"
        ] += 1

    return counts


@dataclass(frozen=True)
class ThetaUnmatchedEvidence:
    canonical_identity: tuple[str, str, float, str]
    evidence_family: str
    anomaly_type: str
    row: Mapping[str, Any]


def find_thetadata_unmatched_evidence(
    *,
    reference_contracts: list[Mapping[str, Any]],
    quote_rows: list[Mapping[str, Any]],
    greek_rows: list[Mapping[str, Any]],
) -> tuple[ThetaUnmatchedEvidence, ...]:
    reference_ids = {
        canonical_option_identity(row)
        for row in reference_contracts
    }
    quotes = _unique_by_identity(
        quote_rows,
        label="ThetaData quote",
    )
    greeks = _unique_by_identity(
        greek_rows,
        label="ThetaData Greek",
    )

    unmatched: list[ThetaUnmatchedEvidence] = []

    for identity, row in quotes.items():
        if identity not in reference_ids:
            unmatched.append(
                ThetaUnmatchedEvidence(
                    canonical_identity=identity,
                    evidence_family="THETADATA_QUOTE",
                    anomaly_type="THETA_QUOTE_ONLY",
                    row=row,
                )
            )

    for identity, row in greeks.items():
        if identity not in reference_ids:
            unmatched.append(
                ThetaUnmatchedEvidence(
                    canonical_identity=identity,
                    evidence_family="THETADATA_GREEKS",
                    anomaly_type="THETA_GREEK_ONLY",
                    row=row,
                )
            )

    return tuple(unmatched)


def persist_thetadata_unmatched_evidence(
    *,
    research_run_id: int,
    unmatched: tuple[ThetaUnmatchedEvidence, ...],
    observed_at: str,
    db_path=None,
) -> int:
    count = 0

    for item in unmatched:
        underlying, expiration, strike, right = item.canonical_identity

        record_unmatched_provider_contract_observation(
            {
                "research_run_id": research_run_id,
                "provider": "THETADATA",
                "evidence_family": item.evidence_family,
                "anomaly_type": item.anomaly_type,
                "underlying": underlying,
                "provider_contract_id": "|".join(
                    [underlying, expiration, str(strike), right]
                ),
                "expiration": expiration,
                "strike": strike,
                "right": right,
                "reason_code": "THETADATA_IDENTITY_NOT_IN_REFERENCE_FRAME",
                "observed_at": observed_at,
                "raw_timestamp": item.row.get("raw_timestamp"),
                "raw_payload_json": __import__("json").dumps(
                    dict(item.row),
                    sort_keys=True,
                    default=str,
                ),
            },
            db_path=db_path,
        )
        count += 1

    return count
