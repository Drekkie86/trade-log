from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SCANNER_GOVERNANCE_MAP = {
    "LOCAL_IV_RESIDUAL_V1": {
        "primary_model": "LOCAL_SURFACE_QUADRATIC_V2",
        "challenger_models": ("NEAREST_BRACKET_LINEAR_V1",),
        "required_hypotheses": (
            "H1_DTE_14_20_TRANSFER_STABILITY",
            "H2_MODEL_FORM_GENERALIZATION",
            "H3_MARKET_QUALITY_CONDITIONING",
            "H4_PERSISTENT_EPISODE_RECURRENCE",
        ),
    },
}


@dataclass(frozen=True)
class CandidateGovernance:
    scanner_family_id: str
    primary_model: str | None
    challenger_models: tuple[str, ...]
    required_hypotheses: tuple[str, ...]
    resolved: bool
    decision_enabled: bool
    admission_enabled: bool
    blockers: tuple[str, ...]
    note: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_candidate_governance(
    candidate: dict[str, Any],
    *,
    models: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
) -> CandidateGovernance:
    scanner = str(candidate.get("scanner_family_id") or "").strip().upper()
    mapping = SCANNER_GOVERNANCE_MAP.get(scanner)
    if mapping is None:
        return CandidateGovernance(
            scanner_family_id=scanner or "UNKNOWN",
            primary_model=None,
            challenger_models=(),
            required_hypotheses=(),
            resolved=False,
            decision_enabled=False,
            admission_enabled=False,
            blockers=("UNMAPPED_CANDIDATE_GOVERNANCE",),
            note="Unknown scanner families fail closed; Christiania never borrows permission from an unrelated model or hypothesis.",
        )

    model_map = {str(row.get("model_key") or "").upper(): row for row in models}
    hypothesis_map = {str(row.get("hypothesis_key") or "").upper(): row for row in hypotheses}
    blockers: list[str] = []

    required_models = (mapping["primary_model"], *mapping["challenger_models"])
    for model_id in required_models:
        row = model_map.get(model_id)
        if row is None:
            blockers.append(f"MODEL_GOVERNANCE_MISSING:{model_id}")
        elif not bool(row.get("decision_enabled")):
            blockers.append(f"MODEL_DECISION_DISABLED:{model_id}")

    for hypothesis_id in mapping["required_hypotheses"]:
        row = hypothesis_map.get(hypothesis_id)
        if row is None:
            blockers.append(f"HYPOTHESIS_GOVERNANCE_MISSING:{hypothesis_id}")
        elif not bool(row.get("decision_enabled")):
            blockers.append(f"HYPOTHESIS_DECISION_DISABLED:{hypothesis_id}")

    decision_enabled = not blockers
    admission_enabled = all(
        bool(model_map.get(model_id, {}).get("admission_enabled"))
        for model_id in required_models
    )
    return CandidateGovernance(
        scanner_family_id=scanner,
        primary_model=mapping["primary_model"],
        challenger_models=tuple(mapping["challenger_models"]),
        required_hypotheses=tuple(mapping["required_hypotheses"]),
        resolved=True,
        decision_enabled=decision_enabled,
        admission_enabled=admission_enabled,
        blockers=tuple(blockers),
        note=(
            "Permission is resolved for this candidate's exact scanner family and its preregistered model/hypothesis set. "
            "Unrelated enabled records cannot grant decision permission."
        ),
    )
