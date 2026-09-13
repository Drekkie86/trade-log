from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.dashboard.read_model import load_command_deck
from src.research.programme_family_governance_v1 import (
    ProgrammeFamilyGovernanceError,
    load_programme_governance_snapshot,
)

RESEARCH_COMMAND_DECK_VERSION = "1.0.1"

NOT_READY_OPERATING_STATES = {
    "RUNTIME_NOT_READY",
    "RESEARCH_RUNTIME_DEGRADED",
    "GOVERNANCE_FAILURE",
}


@dataclass(frozen=True)
class ResearchCommandDeckState:
    version: str
    ready: bool
    operating_state: str
    operating_detail: str
    runtime: dict[str, Any]
    governance: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "ready": self.ready,
            "operating_state": self.operating_state,
            "operating_detail": self.operating_detail,
            "runtime": self.runtime,
            "governance": self.governance,
        }


def _derive_operating_state(
    runtime: dict[str, Any],
    governance: dict[str, Any],
) -> tuple[str, str]:
    if not runtime.get("ready", False):
        return (
            "RUNTIME_NOT_READY",
            f"Existing command-deck read model is not ready: {runtime.get('reason') or 'UNKNOWN'}.",
        )

    daemon = runtime.get("daemon_health") or {}
    if daemon.get("state") not in {"HEALTHY", "IDLE", "NOT_EXPECTED"}:
        return (
            "RESEARCH_RUNTIME_DEGRADED",
            f"Research daemon health is {daemon.get('state') or 'UNKNOWN'}.",
        )

    activation = governance.get("activation_state")
    inference = governance.get("inference_state")

    if activation == "BLOCKED_PROGRAMME_BUDGET_INVALID":
        return (
            "GOVERNANCE_FAILURE",
            governance.get("activation_detail") or "Programme governance is invalid.",
        )

    if activation == "BLOCKED_PROGRAMME_BUDGET_UNFROZEN":
        return (
            "COLLECTING_EXISTING_RESEARCH_ONLY",
            "Runtime research may continue, but opening a new edge family is blocked until the programme budget is deliberately frozen.",
        )

    if activation == "BLOCKED_PROGRAMME_FAMILY_BUDGET_EXHAUSTED":
        return (
            "FAMILY_BUDGET_EXHAUSTED",
            "Existing evidence collection may continue; another hypothesis family may not be opened in this research period.",
        )

    if inference == "DISABLED_UNTIL_CALIBRATED":
        return (
            "DISCOVERY_ONLY",
            "Programme allocation is governed, while p-values, FDR and decision use remain disabled pending calibration.",
        )

    return (
        "GOVERNED_RESEARCH_ACTIVE",
        "Runtime research and programme-family governance are both active. Promotion still requires prospective evidence and the normal Christiania gates.",
    )


def load_research_command_deck(
    db_path: str | Path | None = None,
    *,
    now: datetime | None = None,
    repository_root: str | Path | None = None,
    include_provider_health: bool = False,
    deep_integrity: bool = False,
) -> ResearchCommandDeckState:
    runtime = load_command_deck(
        db_path,
        now=now,
        include_provider_health=include_provider_health,
        deep_integrity=deep_integrity,
    )

    try:
        governance = load_programme_governance_snapshot(
            db_path,
            repository_root=repository_root,
        ).as_dict()
    except ProgrammeFamilyGovernanceError as exc:
        governance = {
            "activation_state": "BLOCKED_PROGRAMME_BUDGET_INVALID",
            "activation_detail": str(exc),
            "inference_state": "DISABLED_UNTIL_CALIBRATED",
            "inference_detail": "Governance artefacts could not be loaded; inference is disabled fail-closed.",
            "budget_errors": [str(exc)],
            "budget_warnings": [],
            "p_values_enabled": False,
            "fdr_enabled": False,
            "decision_enabled": False,
        }

    state, detail = _derive_operating_state(runtime, governance)
    ready = bool(runtime.get("ready")) and state not in NOT_READY_OPERATING_STATES

    return ResearchCommandDeckState(
        version=RESEARCH_COMMAND_DECK_VERSION,
        ready=ready,
        operating_state=state,
        operating_detail=detail,
        runtime=runtime,
        governance=governance,
    )
