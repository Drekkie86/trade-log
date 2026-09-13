from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from src.database.repository import resolve_db_path
from src.operations.sqlite_runtime import open_readonly_connection

PROGRAMME_GOVERNANCE_VERSION = "1.0.0"
DEFAULT_EDGE_DISCOVERY_DIR = Path("research") / "edge_discovery"

BUDGET_STATUS_UNFROZEN = "UNFROZEN"
BUDGET_STATUS_FROZEN = "FROZEN"

ACTIVATION_BLOCKED_UNFROZEN = "BLOCKED_PROGRAMME_BUDGET_UNFROZEN"
ACTIVATION_BLOCKED_INVALID = "BLOCKED_PROGRAMME_BUDGET_INVALID"
ACTIVATION_BLOCKED_EXHAUSTED = "BLOCKED_PROGRAMME_FAMILY_BUDGET_EXHAUSTED"
ACTIVATION_ALLOCATED_ONLY = "ALLOWED_ONLY_FOR_FROZEN_ALLOCATED_FAMILIES"

INFERENCE_DISABLED = "DISABLED_UNTIL_CALIBRATED"
INFERENCE_DISCOVERY_ONLY = "DISCOVERY_ONLY"
INFERENCE_PREREGISTRATION_REVIEW_ONLY = "PREREGISTRATION_REVIEW_ONLY"


class ProgrammeFamilyGovernanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class FamilyUsage:
    family_id: str
    hypothesis_evaluations: int
    allocated: bool


@dataclass(frozen=True)
class ProgrammeGovernanceSnapshot:
    governance_version: str
    budget_status: str
    period_id: str | None
    period_start: str | None
    period_end: str | None
    max_families: int | None
    allocated_family_ids: tuple[str, ...]
    logged_family_ids: tuple[str, ...]
    family_usage: tuple[FamilyUsage, ...]
    opened_family_count: int
    remaining_family_slots: int | None
    activation_state: str
    activation_detail: str
    budget_errors: tuple[str, ...]
    budget_warnings: tuple[str, ...]
    hypothesis_evaluation_count: int
    calibration_readiness: str | None
    calibration_distinct_dates: int | None
    p_values_enabled: bool
    fdr_enabled: bool
    decision_enabled: bool
    inference_state: str
    inference_detail: str

    @property
    def ready_for_new_family_activation(self) -> bool:
        return self.activation_state == ACTIVATION_ALLOCATED_ONLY

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["family_usage"] = [asdict(item) for item in self.family_usage]
        payload["ready_for_new_family_activation"] = self.ready_for_new_family_activation
        return payload


def _repo_root(repository_root: str | Path | None = None) -> Path:
    if repository_root is not None:
        return Path(repository_root).resolve()
    return Path(__file__).resolve().parents[2]


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise ProgrammeFamilyGovernanceError(f"Required governance file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProgrammeFamilyGovernanceError(f"Cannot read governance file {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ProgrammeFamilyGovernanceError(f"Governance file must contain a JSON object: {path}")
    return payload


def _hypothesis_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        raise ProgrammeFamilyGovernanceError(f"Hypothesis evaluation log not found: {path}")
    counts: dict[str, int] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
            family_id = str(payload["family_id"]).strip()
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ProgrammeFamilyGovernanceError(
                f"Malformed hypothesis evaluation log line {line_number}: {exc}"
            ) from exc
        if not family_id:
            raise ProgrammeFamilyGovernanceError(
                f"Malformed hypothesis evaluation log line {line_number}: empty family_id"
            )
        counts[family_id] = counts.get(family_id, 0) + 1
    return counts


def validate_programme_budget(budget: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    errors: list[str] = []
    warnings: list[str] = []

    status = str(budget.get("status") or "")
    if status not in {BUDGET_STATUS_UNFROZEN, BUDGET_STATUS_FROZEN}:
        errors.append("status must be UNFROZEN or FROZEN")

    period_id = str(budget.get("period_id") or "").strip()
    if not period_id:
        errors.append("period_id is required")

    family_ids_raw = budget.get("family_ids")
    if family_ids_raw is None:
        family_ids: list[str] = []
    elif not isinstance(family_ids_raw, list):
        errors.append("family_ids must be a list when present")
        family_ids = []
    else:
        family_ids = [str(item).strip() for item in family_ids_raw]
        if any(not item for item in family_ids):
            errors.append("family_ids may not contain empty values")
        if len(set(family_ids)) != len(family_ids):
            errors.append("family_ids must be unique")

    max_families = budget.get("max_families")
    if max_families is not None and (not isinstance(max_families, int) or max_families < 1):
        errors.append("max_families must be a positive integer when present")

    if status == BUDGET_STATUS_FROZEN:
        start = budget.get("period_start")
        end = budget.get("period_end")
        if not _is_iso_date(start) or not _is_iso_date(end):
            errors.append("FROZEN budget requires ISO period_start and period_end")
        elif str(end) < str(start):
            errors.append("period_end precedes period_start")
        if max_families is None:
            errors.append("FROZEN budget requires max_families")
        if not family_ids:
            errors.append("FROZEN budget requires an explicit family_ids allocation")
        if isinstance(max_families, int) and len(family_ids) > max_families:
            errors.append("allocated family_ids exceed max_families")
        if not str(budget.get("allocation_method") or "").strip():
            errors.append("FROZEN budget requires allocation_method")
        if budget.get("alpha_or_q_budget") is None:
            warnings.append(
                "FROZEN budget has no alpha_or_q_budget; inferential claims must remain disabled"
            )
    else:
        warnings.append(
            "Programme family budget is UNFROZEN; no new edge family may be preregistered or activated"
        )

    return tuple(errors), tuple(warnings)


def _calibration_state(db_path: str | Path | None) -> dict[str, Any]:
    path = resolve_db_path(db_path)
    if not path.exists():
        return {
            "readiness": None,
            "distinct_dates": None,
            "p_values_enabled": False,
            "fdr_enabled": False,
            "decision_enabled": False,
            "detail": "Database is unavailable; inferential claims are disabled fail-closed.",
        }

    conn = open_readonly_connection(path)
    try:
        try:
            row = conn.execute(
                """
                SELECT
                    readiness_state,
                    distinct_session_dates,
                    p_values_enabled,
                    fdr_enabled,
                    decision_enabled
                FROM local_surface_calibration_validity_v1_runs
                ORDER BY id DESC
                LIMIT 1;
                """
            ).fetchone()
        except Exception:
            row = None
    finally:
        conn.close()

    if row is None:
        return {
            "readiness": None,
            "distinct_dates": None,
            "p_values_enabled": False,
            "fdr_enabled": False,
            "decision_enabled": False,
            "detail": "No calibration-validity evidence is available; inferential claims are disabled fail-closed.",
        }

    return {
        "readiness": row["readiness_state"],
        "distinct_dates": int(row["distinct_session_dates"] or 0),
        "p_values_enabled": bool(row["p_values_enabled"]),
        "fdr_enabled": bool(row["fdr_enabled"]),
        "decision_enabled": bool(row["decision_enabled"]),
        "detail": "Latest persisted local-surface calibration-validity state loaded from the evidence database.",
    }


def load_programme_governance_snapshot(
    db_path: str | Path | None = None,
    *,
    repository_root: str | Path | None = None,
) -> ProgrammeGovernanceSnapshot:
    root = _repo_root(repository_root)
    discovery_dir = root / DEFAULT_EDGE_DISCOVERY_DIR
    budget = _read_json(discovery_dir / "PROGRAMME_FAMILY_BUDGET_V1.json")
    counts = _hypothesis_counts(discovery_dir / "HYPOTHESIS_EVALUATION_LOG.jsonl")
    errors, warnings = validate_programme_budget(budget)

    status = str(budget.get("status") or "")
    family_ids_raw = budget.get("family_ids")
    allocated = tuple(
        str(item).strip()
        for item in family_ids_raw
        if str(item).strip()
    ) if isinstance(family_ids_raw, list) else ()
    logged = tuple(sorted(counts))
    opened = len(logged)
    max_families = budget.get("max_families") if isinstance(budget.get("max_families"), int) else None
    remaining = None if max_families is None else max(max_families - opened, 0)

    unallocated_logged = tuple(sorted(set(logged) - set(allocated)))
    if errors:
        activation_state = ACTIVATION_BLOCKED_INVALID
        activation_detail = "Programme family budget is invalid: " + "; ".join(errors)
    elif status != BUDGET_STATUS_FROZEN:
        activation_state = ACTIVATION_BLOCKED_UNFROZEN
        activation_detail = (
            "Programme family budget is not frozen. Existing research may continue collecting evidence, "
            "but no new edge family may be preregistered or activated."
        )
    elif unallocated_logged:
        activation_state = ACTIVATION_BLOCKED_INVALID
        activation_detail = (
            "Hypothesis log contains families outside the frozen allocation: "
            + ", ".join(unallocated_logged)
        )
    elif max_families is not None and opened >= max_families:
        activation_state = ACTIVATION_BLOCKED_EXHAUSTED
        activation_detail = (
            "Programme family budget is exhausted. More observations may be collected, but another family "
            "may not be opened without a new deliberately frozen research period."
        )
    else:
        activation_state = ACTIVATION_ALLOCATED_ONLY
        activation_detail = (
            "Only families explicitly listed in the frozen programme budget may progress. "
            "This does not imply statistical or economic validation."
        )

    calibration = _calibration_state(db_path)
    p_values_enabled = bool(calibration["p_values_enabled"])
    fdr_enabled = bool(calibration["fdr_enabled"])
    decision_enabled = bool(calibration["decision_enabled"])
    readiness = calibration["readiness"]

    if p_values_enabled or fdr_enabled or decision_enabled:
        if readiness == "READY_FOR_PREREGISTRATION_REVIEW_ONLY" and not decision_enabled:
            inference_state = INFERENCE_PREREGISTRATION_REVIEW_ONLY
            inference_detail = (
                "Calibration supports preregistration review only. Decision use remains disabled."
            )
        else:
            inference_state = INFERENCE_DISCOVERY_ONLY
            inference_detail = (
                "One or more inferential flags are enabled, but this governance surface does not promote "
                "research to a trading decision."
            )
    else:
        inference_state = INFERENCE_DISABLED
        inference_detail = (
            "p-values, FDR and decision use remain disabled until calibration evidence explicitly enables them."
        )

    usage = tuple(
        FamilyUsage(
            family_id=family_id,
            hypothesis_evaluations=int(counts[family_id]),
            allocated=family_id in set(allocated),
        )
        for family_id in logged
    )

    return ProgrammeGovernanceSnapshot(
        governance_version=PROGRAMME_GOVERNANCE_VERSION,
        budget_status=status,
        period_id=str(budget.get("period_id") or "") or None,
        period_start=budget.get("period_start"),
        period_end=budget.get("period_end"),
        max_families=max_families,
        allocated_family_ids=allocated,
        logged_family_ids=logged,
        family_usage=usage,
        opened_family_count=opened,
        remaining_family_slots=remaining,
        activation_state=activation_state,
        activation_detail=activation_detail,
        budget_errors=errors,
        budget_warnings=warnings,
        hypothesis_evaluation_count=sum(counts.values()),
        calibration_readiness=readiness,
        calibration_distinct_dates=calibration["distinct_dates"],
        p_values_enabled=p_values_enabled,
        fdr_enabled=fdr_enabled,
        decision_enabled=decision_enabled,
        inference_state=inference_state,
        inference_detail=inference_detail,
    )
