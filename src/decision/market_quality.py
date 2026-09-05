from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

MAX_LIVE_QUOTE_AGE_SECONDS = 60.0
MAX_SPREAD_TO_MID = 0.05


def _f(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


@dataclass(frozen=True)
class MarketQualityAssessment:
    state: str
    quote_age_seconds: float | None
    spread_to_mid: float | None
    live_quote_fresh: bool
    liquidity_pass: bool
    data_quality_pass: bool
    recovered_sample: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def assess_market_quality(candidate: dict[str, Any], *, now: datetime | None = None) -> MarketQualityAssessment:
    now = now or datetime.now(UTC)
    bid = _f(candidate.get("target_bid"))
    ask = _f(candidate.get("target_ask"))
    quote_at = _parse(candidate.get("target_quote_at"))
    age = None if quote_at is None else max(0.0, (now - quote_at.astimezone(UTC)).total_seconds())
    mid = None if bid is None or ask is None else (bid + ask) / 2.0
    spread = None if mid is None or mid <= 0 or ask < bid else (ask - bid) / mid
    fresh = age is not None and age <= MAX_LIVE_QUOTE_AGE_SECONDS
    liquid = spread is not None and spread <= MAX_SPREAD_TO_MID
    collection_ok = str(candidate.get("collection_status") or "").upper() == "SUCCESS"
    recovered = bool(candidate.get("was_recovered")) or int(candidate.get("retry_count") or 0) > 0

    blockers: list[str] = []
    warnings: list[str] = []
    if not fresh:
        blockers.append("LIVE_QUOTE_NOT_FRESH")
    if not liquid:
        blockers.append("BID_ASK_TOO_WIDE_OR_UNAVAILABLE")
    if not collection_ok:
        blockers.append("COLLECTION_QUALITY_NOT_SUCCESS")
    if recovered:
        warnings.append("RECOVERED_PROVIDER_SAMPLE")

    return MarketQualityAssessment(
        state="PASS" if not blockers else "BLOCKED",
        quote_age_seconds=age,
        spread_to_mid=spread,
        live_quote_fresh=fresh,
        liquidity_pass=liquid,
        data_quality_pass=collection_ok,
        recovered_sample=recovered,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )
