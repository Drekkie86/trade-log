from __future__ import annotations

from typing import Any, Mapping


HYPOTHESIS_LABELS = {
    "H1_DTE_14_20_TRANSFER_STABILITY": "DTE 14–20 transfer stability",
    "H2_MODEL_FORM_GENERALIZATION": "Model-form generalization",
    "H3_MARKET_QUALITY_CONDITIONING": "Market-quality conditioning",
    "H4_PERSISTENT_EPISODE_RECURRENCE": "Persistent episode recurrence",
    "LOCAL_IV_RESIDUAL_V1": "Local IV residual",
    "LOCAL_SURFACE_ROBUSTNESS_V1": "Local surface robustness",
}

MODEL_LABELS = {
    "LOCAL_SURFACE_QUADRATIC_V2": "Local surface quadratic residual",
    "NEAREST_BRACKET_LINEAR_V1": "Nearest-bracket linear comparator",
    "BLACK_SCHOLES_MERTON_BENCHMARK": "Black-Scholes-Merton benchmark",
    "BAYESIAN_PERSISTENCE_MODEL": "Bayesian persistence model",
}

PROVIDER_LABELS = {
    "massive": "Massive",
    "massive.com": "Massive",
    "thetadata": "ThetaData",
    "theta": "ThetaData",
    "saxo": "Saxo",
}


def friendly_identifier(value: Any, aliases: Mapping[str, str]) -> str:
    """Return a reviewed alias; unknown identifiers stay exact rather than invented."""
    if value is None:
        return "—"
    raw = str(value)
    return aliases.get(raw, raw)


def hypothesis_label(value: Any) -> str:
    return friendly_identifier(value, HYPOTHESIS_LABELS)


def model_label(value: Any) -> str:
    return friendly_identifier(value, MODEL_LABELS)


def provider_label(value: Any) -> str:
    if value is None:
        return "—"
    raw = str(value)
    return PROVIDER_LABELS.get(raw.casefold(), raw)


def calibration_evidence_state(*, models: list[dict], hypotheses: list[dict], independent_dates: int) -> dict[str, Any]:
    """Derive UI wording from stored governance, never from aesthetic preference."""
    decision_enabled = any(bool(row.get("decision_enabled")) for row in [*models, *hypotheses])
    admission_enabled = any(bool(row.get("admission_enabled")) for row in models)

    if decision_enabled or admission_enabled:
        return {
            "state": "GOVERNANCE REVIEW REQUIRED",
            "tone": "bad",
            "detail": "A decision/admission flag is enabled; this is not a V1-ready research-only state.",
        }

    if independent_dates < 5:
        return {
            "state": "DISCOVERY ONLY — NOT READY FOR DECISIONS",
            "tone": "warn",
            "detail": f"{independent_dates}/5 independent prospective dates collected before the first descriptive review.",
        }

    if independent_dates < 20:
        return {
            "state": "DESCRIPTIVE REVIEW ONLY — NOT READY FOR DECISIONS",
            "tone": "warn",
            "detail": f"{independent_dates}/20 independent prospective dates collected toward preregistration review.",
        }

    return {
        "state": "PREREGISTRATION REVIEW THRESHOLD REACHED — DECISIONS STILL DISABLED",
        "tone": "info",
        "detail": f"{independent_dates} independent prospective dates collected; governance still prohibits decisions/admission.",
    }
