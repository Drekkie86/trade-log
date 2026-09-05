from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

PREREG_REVIEW_DATES = 20
DESCRIPTIVE_REVIEW_DATES = 5


@dataclass(frozen=True)
class ProspectiveEvidenceAssessment:
    state: str
    independent_dates: int
    candidate_count: int
    validated_outcomes: int
    profitable_outcomes: int
    unprofitable_outcomes: int
    mean_net_pnl_eur: float | None
    decision_eligible: bool
    note: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_prospective_evidence(candidate: dict[str, Any]) -> ProspectiveEvidenceAssessment:
    dates = int(candidate.get("similar_independent_dates") or 0)
    count = int(candidate.get("similar_candidate_count") or 0)
    validated = int(candidate.get("similar_validated_outcomes") or 0)
    profitable = int(candidate.get("similar_profitable_outcomes") or 0)
    unprofitable = int(candidate.get("similar_unprofitable_outcomes") or 0)
    mean_minor = candidate.get("similar_mean_net_pnl_eur_minor")
    mean_eur = None if mean_minor is None else float(mean_minor) / 100.0
    if dates < DESCRIPTIVE_REVIEW_DATES:
        state = "INSUFFICIENT_FOR_DESCRIPTIVE_REVIEW"
    elif dates < PREREG_REVIEW_DATES:
        state = "DESCRIPTIVE_ONLY"
    else:
        state = "PREREG_REVIEW_THRESHOLD_REACHED"
    # Reaching 20 dates is a review trigger, never automatic permission.
    return ProspectiveEvidenceAssessment(
        state=state,
        independent_dates=dates,
        candidate_count=count,
        validated_outcomes=validated,
        profitable_outcomes=profitable,
        unprofitable_outcomes=unprofitable,
        mean_net_pnl_eur=mean_eur,
        decision_eligible=False,
        note="Prospective history is descriptive evidence only. Twenty independent dates triggers review; it does not prove edge or enable trading.",
    )
