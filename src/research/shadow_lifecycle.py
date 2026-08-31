from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ShadowState(StrEnum):
    SURFACED = "SURFACED"
    INVESTIGATED = "INVESTIGATED"
    DECIDED = "DECIDED"
    SHADOW_TRACKED = "SHADOW_TRACKED"
    CLOSED_OR_EXPIRED = "CLOSED_OR_EXPIRED"
    SCORED = "SCORED"
    REJECTED = "REJECTED"


class ShadowDecision(StrEnum):
    REJECT = "REJECT"
    SHADOW_TRACK = "SHADOW_TRACK"


class FreshnessClass(StrEnum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class GreekQuality(StrEnum):
    GOOD = "GOOD"
    REVIEW = "REVIEW"
    BAD = "BAD"
    UNKNOWN = "UNKNOWN"


class UniverseStatus(StrEnum):
    CONSISTENT = "CONSISTENT"
    DISAGREEMENT_RECORDED = "DISAGREEMENT_RECORDED"
    UNUSABLE = "UNUSABLE"


_ALLOWED_TRANSITIONS: dict[ShadowState, frozenset[ShadowState]] = {
    ShadowState.SURFACED: frozenset({ShadowState.INVESTIGATED}),
    ShadowState.INVESTIGATED: frozenset({ShadowState.DECIDED}),
    ShadowState.DECIDED: frozenset(
        {ShadowState.SHADOW_TRACKED, ShadowState.REJECTED}
    ),
    ShadowState.SHADOW_TRACKED: frozenset({ShadowState.CLOSED_OR_EXPIRED}),
    ShadowState.CLOSED_OR_EXPIRED: frozenset({ShadowState.SCORED}),
    ShadowState.SCORED: frozenset(),
    ShadowState.REJECTED: frozenset(),
}


def can_transition(current: ShadowState, target: ShadowState) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


def require_transition(current: ShadowState, target: ShadowState) -> None:
    if not can_transition(current, target):
        raise ValueError(f"Invalid shadow lifecycle transition: {current} -> {target}")


def classify_freshness(age_seconds: float | None) -> FreshnessClass:
    if age_seconds is None or age_seconds < 0:
        return FreshnessClass.UNKNOWN
    if age_seconds <= 15:
        return FreshnessClass.FRESH
    if age_seconds <= 60:
        return FreshnessClass.AGING
    return FreshnessClass.STALE


def classify_greek_quality(iv_error: float | None) -> GreekQuality:
    if iv_error is None:
        return GreekQuality.UNKNOWN
    value = abs(iv_error)
    if value <= 0.005:
        return GreekQuality.GOOD
    if value <= 0.02:
        return GreekQuality.REVIEW
    return GreekQuality.BAD


@dataclass(frozen=True)
class ShadowAdmissionQuality:
    quote_freshness: FreshnessClass
    greek_quality: GreekQuality
    greek_dependent_rule: bool = True
    quote_row_present: bool = True
    greek_row_present: bool = True
    universe_status: UniverseStatus = UniverseStatus.CONSISTENT

    @property
    def eligible_for_first_shadow_cohort(self) -> bool:
        if self.universe_status is UniverseStatus.UNUSABLE:
            return False
        if not self.quote_row_present:
            return False
        if self.quote_freshness is not FreshnessClass.FRESH:
            return False
        if self.greek_dependent_rule:
            if not self.greek_row_present:
                return False
            if self.greek_quality is not GreekQuality.GOOD:
                return False
        return True
