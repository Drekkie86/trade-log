"""Compatibility import for Christiania shadow research admission.

The active policy is account-independent intrinsic risk. Historical decisions
created by the former fixed-EUR-500 policy remain immutable in the database for
auditability, but the application no longer exposes that policy as an active
research-admission path.
"""

from src.research.shadow_intrinsic_admission_v1 import (
    ADMISSION_LABEL,
    COST_MODEL_VERSION,
    COST_PROVENANCE,
    RISK_POLICY_VERSION,
    SIZING_POLICY_VERSION,
    ShadowAdmissionDecision,
    ShadowAdmissionError,
    ShadowAdmissionResult,
    USD_COST_PER_CONTRACT_SIDE_MINOR,
    _load_proposals,
    admit_shadow_proposals,
)

__all__ = [
    "ADMISSION_LABEL",
    "COST_MODEL_VERSION",
    "COST_PROVENANCE",
    "RISK_POLICY_VERSION",
    "SIZING_POLICY_VERSION",
    "ShadowAdmissionDecision",
    "ShadowAdmissionError",
    "ShadowAdmissionResult",
    "USD_COST_PER_CONTRACT_SIDE_MINOR",
    "admit_shadow_proposals",
]
