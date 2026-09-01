from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.research.shadow_lifecycle import (
    FreshnessClass,
    GreekQuality,
)
from src.research.thetadata_live_evidence import (
    ThetaJoinedEvidence,
    join_thetadata_live_evidence,
)

NEW_YORK = ZoneInfo("America/New_York")


class LivePipelineError(ValueError):
    pass


@dataclass(frozen=True)
class AdmissionDiagnostic:
    reference_contract_id: int
    canonical_identity: tuple[str, str, float, str]
    quote_state: str
    greek_state: str
    quote_freshness: FreshnessClass
    greek_quality: GreekQuality
    structurally_ready: bool
    blocking_reasons: tuple[str, ...]


def parse_thetadata_market_timestamp(
    raw_timestamp: str,
) -> datetime:
    """
    Parse ThetaData's naive market timestamp as America/New_York.

    ThetaData's option documentation describes snapshot-cache reset and
    time-of-day semantics in ET. We still retain the provider's raw timestamp
    separately in persisted evidence; this conversion is only for quote-age
    calculation.
    """

    if not raw_timestamp:
        raise LivePipelineError(
            "ThetaData quote timestamp is blank."
        )

    try:
        parsed = datetime.fromisoformat(
            str(raw_timestamp)
        )
    except ValueError as exc:
        raise LivePipelineError(
            f"Invalid ThetaData timestamp: {raw_timestamp}"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=NEW_YORK)
    else:
        parsed = parsed.astimezone(NEW_YORK)

    return parsed


def attach_quote_ages(
    quote_rows: tuple[dict[str, Any], ...],
    *,
    observed_at: datetime,
) -> tuple[dict[str, Any], ...]:
    """
    Add `quote_age_seconds` to normalized ThetaData quote rows.

    Negative ages fail closed rather than being silently clamped.
    """

    if observed_at.tzinfo is None:
        raise LivePipelineError(
            "observed_at must be timezone-aware."
        )

    observed_ny = observed_at.astimezone(
        NEW_YORK
    )

    enriched: list[dict[str, Any]] = []

    for row in quote_rows:
        raw_timestamp = row.get(
            "raw_timestamp"
        )

        item = dict(row)

        if raw_timestamp in {None, ""}:
            item["quote_age_seconds"] = None
            enriched.append(item)
            continue

        quote_time = (
            parse_thetadata_market_timestamp(
                str(raw_timestamp)
            )
        )

        age = (
            observed_ny - quote_time
        ).total_seconds()

        if age < -90.0:
            raise LivePipelineError(
                "ThetaData quote timestamp is materially "
                "in the future relative to observation time: "
                f"{raw_timestamp}"
            )

        item["quote_age_seconds"] = max(
            0.0,
            age,
        )
        enriched.append(item)

    return tuple(enriched)


def build_live_join(
    *,
    reference_contracts: list[Mapping[str, Any]],
    quote_rows: tuple[dict[str, Any], ...],
    greek_rows: tuple[dict[str, Any], ...],
    observed_at: datetime,
) -> tuple[ThetaJoinedEvidence, ...]:
    aged_quotes = attach_quote_ages(
        quote_rows,
        observed_at=observed_at,
    )

    return join_thetadata_live_evidence(
        reference_contracts=
            reference_contracts,
        quote_rows=list(aged_quotes),
        greek_rows=list(greek_rows),
    )


def diagnose_admission(
    joined: tuple[ThetaJoinedEvidence, ...],
) -> tuple[AdmissionDiagnostic, ...]:
    """
    Structural admission diagnostic only.

    This does NOT claim candidate quality or edge. It answers only whether
    the minimum quote/Greek plumbing is present and the quote is FRESH.

    GreekQuality is reported but does not promote admission on its own.
    """

    result: list[AdmissionDiagnostic] = []

    for item in joined:
        reasons: list[str] = []

        if item.quote_state != "PRESENT":
            reasons.append(
                "QUOTE_OBSERVATION_ABSENT"
            )

        if (
            item.quote_state == "PRESENT"
            and item.quote_freshness
            is not FreshnessClass.FRESH
        ):
            reasons.append(
                "QUOTE_NOT_FRESH"
            )

        if item.greek_state != "PRESENT":
            reasons.append(
                "MODEL_OBSERVATION_ABSENT"
            )

        if (
            item.greek_state == "PRESENT"
            and item.greek_quality
            in {
                GreekQuality.BAD,
                GreekQuality.UNKNOWN,
            }
        ):
            reasons.append(
                "GREEK_QUALITY_NOT_ACCEPTABLE"
            )

        result.append(
            AdmissionDiagnostic(
                reference_contract_id=
                    item.reference_contract_id,
                canonical_identity=
                    item.canonical_identity,
                quote_state=
                    item.quote_state,
                greek_state=
                    item.greek_state,
                quote_freshness=
                    item.quote_freshness,
                greek_quality=
                    item.greek_quality,
                structurally_ready=
                    not reasons,
                blocking_reasons=
                    tuple(reasons),
            )
        )

    return tuple(result)
