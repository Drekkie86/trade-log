from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.database.repository import get_connection
from src.research.live_pipeline import (
    parse_thetadata_market_timestamp,
)
from src.research.shadow_lifecycle import (
    FreshnessClass,
    GreekQuality,
    classify_freshness,
    classify_greek_quality,
)

UTC = ZoneInfo("UTC")
NY = ZoneInfo("America/New_York")

SCANNER_FAMILY_ID = "BASIC_TRADABILITY_V1"
SCANNER_VERSION = "1.0.0"
RULE_VERSION = "BASIC_TRADABILITY_RULES_V1"

DEFAULT_MAX_SPREAD_TO_MID = 0.20


class DeterministicScannerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScannerObservation:
    option_quote_id: int
    underlying: str
    expiration: str
    strike: float
    right: str
    bid: float | None
    ask: float | None
    mid: float | None
    spread: float | None
    spread_to_mid: float | None
    quote_age_seconds: float | None
    quote_freshness: FreshnessClass
    iv_error: float | None
    greek_quality: GreekQuality
    delta: float | None
    structurally_eligible: bool
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True)
class ScannerRunSummary:
    research_run_id: int
    scanner_family_id: str
    scanner_version: str
    rule_version: str
    total_quotes: int
    eligible: int
    blocked: int
    blocker_counts: dict[str, int]
    observations: tuple[ScannerObservation, ...]


def _parse_captured_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise DeterministicScannerError(
            f"Invalid snapshot captured_at: {value}"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    return parsed.astimezone(UTC)


def _quote_age_seconds(
    *,
    captured_at: str,
    quote_at: str | None,
) -> float | None:
    if not quote_at:
        return None

    captured = _parse_captured_at(
        captured_at
    )
    quote_time = (
        parse_thetadata_market_timestamp(
            quote_at
        )
        .astimezone(UTC)
    )

    age = (
        captured - quote_time
    ).total_seconds()

    if age < -90.0:
        raise DeterministicScannerError(
            "Persisted quote timestamp is materially "
            "in the future relative to snapshot capture."
        )

    return max(0.0, age)


def _extract_iv_error(
    model_input_notes: str | None,
) -> float | None:
    if not model_input_notes:
        return None

    try:
        payload = json.loads(
            model_input_notes
        )
    except json.JSONDecodeError:
        return None

    value = payload.get(
        "iv_error"
    )

    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _spread_metrics(
    bid: float | None,
    ask: float | None,
) -> tuple[
    float | None,
    float | None,
    float | None,
]:
    if bid is None or ask is None:
        return None, None, None

    bid = float(bid)
    ask = float(ask)

    mid = (bid + ask) / 2.0
    spread = ask - bid

    if mid <= 0:
        return mid, spread, None

    return (
        mid,
        spread,
        spread / mid,
    )


def scan_research_run(
    *,
    research_run_id: int,
    max_spread_to_mid: float =
        DEFAULT_MAX_SPREAD_TO_MID,
    db_path=None,
) -> ScannerRunSummary:
    if max_spread_to_mid <= 0:
        raise ValueError(
            "max_spread_to_mid must be positive."
        )

    conn = get_connection(db_path)

    try:
        run = conn.execute(
            """
            SELECT id, status
            FROM research_runs
            WHERE id = ?;
            """,
            (research_run_id,),
        ).fetchone()

        if run is None:
            raise DeterministicScannerError(
                f"Research run {research_run_id} not found."
            )

        if run["status"] != "COMPLETED":
            raise DeterministicScannerError(
                "Scanner only evaluates COMPLETED research runs."
            )

        rows = conn.execute(
            """
            SELECT
                oq.id AS option_quote_id,
                ms.underlying,
                oq.expiration,
                oq.strike,
                oq.right,
                oq.bid,
                oq.ask,
                oq.quote_at,
                ms.captured_at,
                pmo.delta,
                pmo.model_input_notes
            FROM market_snapshots AS ms
            JOIN option_quotes AS oq
              ON oq.snapshot_id = ms.id
            LEFT JOIN provider_model_observations AS pmo
              ON pmo.option_quote_id = oq.id
             AND pmo.provider = 'THETADATA'
            WHERE ms.research_run_id = ?
              AND ms.provider = 'THETADATA'
            ORDER BY
                ms.underlying,
                oq.expiration,
                oq.strike,
                oq.right;
            """,
            (research_run_id,),
        ).fetchall()
    finally:
        conn.close()

    observations: list[
        ScannerObservation
    ] = []

    blocker_counts: dict[
        str,
        int,
    ] = {}

    for row in rows:
        bid = (
            None
            if row["bid"] is None
            else float(row["bid"])
        )
        ask = (
            None
            if row["ask"] is None
            else float(row["ask"])
        )

        (
            mid,
            spread,
            spread_to_mid,
        ) = _spread_metrics(
            bid,
            ask,
        )

        quote_age = _quote_age_seconds(
            captured_at=
                row["captured_at"],
            quote_at=
                row["quote_at"],
        )

        freshness = classify_freshness(
            quote_age
        )

        iv_error = _extract_iv_error(
            row["model_input_notes"]
        )

        greek_quality = (
            classify_greek_quality(
                iv_error
            )
        )

        reasons: list[str] = []

        if bid is None or ask is None:
            reasons.append(
                "BID_ASK_MISSING"
            )
        elif bid < 0 or ask < 0:
            reasons.append(
                "NEGATIVE_QUOTE"
            )
        elif ask < bid:
            reasons.append(
                "CROSSED_MARKET"
            )
        elif mid is None or mid <= 0:
            reasons.append(
                "NON_POSITIVE_MID"
            )

        if freshness is not FreshnessClass.FRESH:
            reasons.append(
                "QUOTE_NOT_FRESH"
            )

        if (
            spread_to_mid is None
            or spread_to_mid
            > max_spread_to_mid
        ):
            reasons.append(
                "SPREAD_TOO_WIDE"
            )

        if greek_quality in {
            GreekQuality.BAD,
            GreekQuality.UNKNOWN,
        }:
            reasons.append(
                "GREEK_QUALITY_NOT_ACCEPTABLE"
            )

        if row["delta"] is None:
            reasons.append(
                "DELTA_MISSING"
            )

        for reason in reasons:
            blocker_counts[reason] = (
                blocker_counts.get(
                    reason,
                    0,
                )
                + 1
            )

        observations.append(
            ScannerObservation(
                option_quote_id=
                    int(
                        row[
                            "option_quote_id"
                        ]
                    ),
                underlying=
                    str(
                        row["underlying"]
                    ),
                expiration=
                    str(
                        row["expiration"]
                    ),
                strike=
                    float(
                        row["strike"]
                    ),
                right=
                    str(
                        row["right"]
                    ),
                bid=
                    bid,
                ask=
                    ask,
                mid=
                    mid,
                spread=
                    spread,
                spread_to_mid=
                    spread_to_mid,
                quote_age_seconds=
                    quote_age,
                quote_freshness=
                    freshness,
                iv_error=
                    iv_error,
                greek_quality=
                    greek_quality,
                delta=
                    (
                        None
                        if row["delta"]
                        is None
                        else float(
                            row["delta"]
                        )
                    ),
                structurally_eligible=
                    not reasons,
                blocking_reasons=
                    tuple(reasons),
            )
        )

    eligible = sum(
        item.structurally_eligible
        for item in observations
    )

    return ScannerRunSummary(
        research_run_id=
            research_run_id,
        scanner_family_id=
            SCANNER_FAMILY_ID,
        scanner_version=
            SCANNER_VERSION,
        rule_version=
            RULE_VERSION,
        total_quotes=
            len(observations),
        eligible=
            eligible,
        blocked=
            len(observations)
            - eligible,
        blocker_counts=
            blocker_counts,
        observations=
            tuple(observations),
    )
