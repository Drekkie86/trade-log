"""
Christiania — Edge Statement validation with enforcement.

The existing `validate_edge_statement.py` computes a SHA-256 and checks
that a few top-level keys exist. The JSON schema declares
`additionalProperties: true` and types most substantive fields as bare
`{"type": "object"}`, so `{"setup": {}}` is schema-valid.

That means the Edge Discovery Protocol's §3 prohibitions are norms with
no mechanism. This module supplies the mechanism.

Three checks matter more than the rest:

1. DISCOVERY / CONFIRMATION SPLIT
   `confirmation.data_start` must fall strictly after every registered
   discovery window. August 2026 is already discovery data — it shaped
   the screening design across most of the dimensions §3 forbids — so a
   preregistration whose confirmation period overlaps it is rejected.

2. INDEPENDENCE UNIT
   Constrained to an enum, defaulting to `underlying_session`. Left free
   text, this single field can inflate nominal N by three orders of
   magnitude, and it is exactly the knob a motivated analyst reaches for
   when a result is nearly significant.

3. STATUS TRANSITIONS
   CONFIRMED requires a recorded preregistration hash. Results may not
   be present while status is DRAFT or PREREGISTERED, so the
   preregistration and its outcome cannot live in one editable file.

No I/O beyond reading the files it is given. No network. No database.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ALLOWED_STATUS = ("DRAFT", "PREREGISTERED", "CONFIRMED", "REJECTED")

ALLOWED_INDEPENDENCE_UNITS = (
    "underlying_session",
    "underlying_week",
    "session",
)

DEFAULT_INDEPENDENCE_UNIT = "underlying_session"

ALLOWED_MULTIPLICITY = (
    "BONFERRONI",
    "HOLM",
    "BENJAMINI_HOCHBERG",
    "PREREGISTERED_SINGLE_HYPOTHESIS",
)

ALLOWED_COST_PROVENANCE = ("QUOTED", "ASSUMED", "ACTUAL_FILL")

REQUIRED_SETUP = (
    "structure",
    "direction",
    "entry_rule",
    "exit_rule",
    "max_holding_period",
)

REQUIRED_ESTIMAND = (
    "primary_metric",
    "comparator",
    "cost_provenance",
)

REQUIRED_CONFIRMATION = (
    "data_start",
    "data_end",
    "independence_unit",
    "minimum_independent_units",
    "test",
    "alpha_or_q",
    "multiplicity_method",
    "effect_size_floor",
)

REQUIRED_SEARCHED_FAMILY = ("hypothesis_count",)


@dataclass(frozen=True)
class DiscoveryWindow:
    window_id: str
    start: str
    end: str
    description: str = ""

    def overlaps(self, start: str, end: str) -> bool:
        return not (end < self.start or start > self.end)


@dataclass
class ValidationResult:
    ok: bool
    status: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sha256: str | None = None

    def report(self) -> str:
        lines = [f"STATUS: {self.status}"]
        if self.sha256:
            lines.append(f"SHA256: {self.sha256}")
        for error in self.errors:
            lines.append(f"  ERROR   {error}")
        for warning in self.warnings:
            lines.append(f"  WARNING {warning}")
        lines.append("RESULT: " + ("PASS" if self.ok else "FAIL"))
        return "\n".join(lines)


def load_discovery_registry(
    path: str | Path,
) -> tuple[DiscoveryWindow, ...]:
    """
    Read the registry of periods already used for discovery.

    A missing registry is an error, not an empty list. Absence would
    otherwise silently permit any confirmation window.
    """

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Discovery registry not found at {path}. Every period used "
            "for discovery must be registered before any preregistration "
            "can be validated."
        )

    payload = json.loads(path.read_text(encoding="utf-8"))

    return tuple(
        DiscoveryWindow(
            window_id=str(item["window_id"]),
            start=str(item["start"]),
            end=str(item["end"]),
            description=str(item.get("description", "")),
        )
        for item in payload["discovery_windows"]
    )


def _get(obj: Mapping[str, Any], *path: str) -> Any:
    current: Any = obj
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def load_hypothesis_counts(path: str | Path) -> dict[str, int]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Hypothesis evaluation log not found at {path}")
    counts: dict[str, int] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            family_id = str(record["family_id"])
        except Exception as exc:
            raise ValueError(f"Malformed hypothesis log line {line_number}: {exc}") from exc
        counts[family_id] = counts.get(family_id, 0) + 1
    return counts


def load_programme_budget(path: str | Path) -> Mapping[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Programme family budget not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_holdout_registry(path: str | Path) -> tuple[DiscoveryWindow, ...]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Holdout access registry not found at {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    windows = []
    for item in payload.get("access_events", []):
        if not item.get("contaminates_confirmation", False):
            continue
        windows.append(DiscoveryWindow(
            window_id=str(item["event_id"]),
            start=str(item["start"]),
            end=str(item["end"]),
            description=str(item.get("reason", "")),
        ))
    return tuple(windows)


def validate_edge_statement(
    document: Mapping[str, Any],
    *,
    discovery_windows: Sequence[DiscoveryWindow],
    holdout_windows: Sequence[DiscoveryWindow] = (),
    hypothesis_counts: Mapping[str, int] | None = None,
    programme_budget: Mapping[str, Any] | None = None,
    raw_bytes: bytes | None = None,
) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    status = str(document.get("status", ""))
    if status not in ALLOWED_STATUS:
        errors.append(
            f"status {status!r} is not one of {ALLOWED_STATUS}"
        )

    sha = (
        hashlib.sha256(raw_bytes).hexdigest()
        if raw_bytes is not None
        else None
    )

    # -----------------------------------------------------------------
    # DRAFT is allowed to be incomplete. Everything else is not.
    # -----------------------------------------------------------------
    if status == "DRAFT":
        return ValidationResult(
            ok=not errors,
            status=status,
            errors=errors,
            warnings=["DRAFT is not a preregistration and proves nothing."],
            sha256=sha,
        )

    for key in REQUIRED_SETUP:
        if _get(document, "setup", key) in (None, ""):
            errors.append(f"setup.{key} is required")

    for key in REQUIRED_ESTIMAND:
        if _get(document, "estimand", key) in (None, ""):
            errors.append(f"estimand.{key} is required")

    for key in REQUIRED_CONFIRMATION:
        if _get(document, "confirmation", key) in (None, ""):
            errors.append(f"confirmation.{key} is required")

    for key in REQUIRED_SEARCHED_FAMILY:
        if _get(document, "searched_family", key) in (None, ""):
            errors.append(f"searched_family.{key} is required")

    if not str(document.get("edge_statement") or "").strip():
        errors.append(
            "edge_statement must be written before confirmation begins"
        )

    # -----------------------------------------------------------------
    # Independence unit
    # -----------------------------------------------------------------
    unit = _get(document, "confirmation", "independence_unit")
    if unit is not None and unit not in ALLOWED_INDEPENDENCE_UNITS:
        errors.append(
            f"confirmation.independence_unit {unit!r} is not one of "
            f"{ALLOWED_INDEPENDENCE_UNITS}"
        )
    elif unit is not None and unit != DEFAULT_INDEPENDENCE_UNIT:
        if not str(
            _get(document, "confirmation", "independence_justification")
            or ""
        ).strip():
            errors.append(
                f"independence_unit {unit!r} loosens the default "
                f"{DEFAULT_INDEPENDENCE_UNIT!r} and requires "
                "confirmation.independence_justification with a measured "
                "dependence estimate and its confidence interval"
            )

    # -----------------------------------------------------------------
    # Multiplicity and cost provenance
    # -----------------------------------------------------------------
    method = _get(document, "confirmation", "multiplicity_method")
    if method is not None and method not in ALLOWED_MULTIPLICITY:
        errors.append(
            f"confirmation.multiplicity_method {method!r} is not one of "
            f"{ALLOWED_MULTIPLICITY}"
        )

    count = _get(document, "searched_family", "hypothesis_count")
    if isinstance(count, int) and count < 1:
        errors.append("searched_family.hypothesis_count must be >= 1")

    provenance = _get(document, "estimand", "cost_provenance")
    if provenance is not None and provenance not in ALLOWED_COST_PROVENANCE:
        errors.append(
            f"estimand.cost_provenance {provenance!r} is not one of "
            f"{ALLOWED_COST_PROVENANCE}"
        )
    if provenance == "ASSUMED":
        warnings.append(
            "cost_provenance is ASSUMED. Harvestability cannot be "
            "established from assumed costs."
        )

    # -----------------------------------------------------------------
    # Discovery / confirmation split — the check that matters most
    # -----------------------------------------------------------------
    start = _get(document, "confirmation", "data_start")
    end = _get(document, "confirmation", "data_end")

    if start is not None and not _is_iso_date(start):
        errors.append("confirmation.data_start must be an ISO date")
    if end is not None and not _is_iso_date(end):
        errors.append("confirmation.data_end must be an ISO date")

    if _is_iso_date(start) and _is_iso_date(end):
        if end < start:
            errors.append(
                "confirmation.data_end precedes confirmation.data_start"
            )

        for window in discovery_windows:
            if window.overlaps(str(start), str(end)):
                errors.append(
                    f"confirmation window {start}..{end} overlaps "
                    f"registered discovery window {window.window_id} "
                    f"({window.start}..{window.end}). Confirmation must "
                    "use observations that did not shape the rule."
                )

        for window in holdout_windows:
            if window.overlaps(str(start), str(end)):
                errors.append(
                    f"confirmation window {start}..{end} overlaps contaminated "
                    f"holdout-access window {window.window_id} "
                    f"({window.start}..{window.end})."
                )

        discovery_end = document.get("created_from_discovery_data_end")
        if _is_iso_date(discovery_end):
            if str(start) <= str(discovery_end):
                errors.append(
                    f"confirmation.data_start {start} does not fall after "
                    f"created_from_discovery_data_end {discovery_end}"
                )
        else:
            errors.append(
                "created_from_discovery_data_end is required and must be "
                "an ISO date"
            )

    # -----------------------------------------------------------------
    # Hypothesis count is derived from the append-only research log
    # -----------------------------------------------------------------
    family_id = str(document.get("family_id") or "")
    if status == "PREREGISTERED" and hypothesis_counts is not None:
        derived_count = int(hypothesis_counts.get(family_id, 0))
        declared_count = _get(document, "searched_family", "hypothesis_count")
        if derived_count < 1:
            errors.append(
                f"family_id {family_id!r} has no logged hypothesis evaluations"
            )
        if declared_count != derived_count:
            errors.append(
                f"searched_family.hypothesis_count={declared_count!r} does not "
                f"match derived log count {derived_count} for {family_id}"
            )

    # -----------------------------------------------------------------
    # Programme-level family budget must be frozen before preregistration
    # -----------------------------------------------------------------
    if status == "PREREGISTERED" and programme_budget is not None:
        if programme_budget.get("status") != "FROZEN":
            errors.append(
                "programme family budget is not FROZEN; no new edge family may "
                "be preregistered while the programme-level error budget is open"
            )
        allowed = programme_budget.get("family_ids")
        if isinstance(allowed, list) and family_id not in {str(x) for x in allowed}:
            errors.append(
                f"family_id {family_id!r} is not allocated in the frozen programme budget"
            )

    # -----------------------------------------------------------------
    # Results may not coexist with a preregistration
    # -----------------------------------------------------------------
    results = document.get("results") or {}
    substantive = {
        key: value
        for key, value in results.items()
        if key != "locked_until_confirmation"
    }

    if status == "PREREGISTERED" and substantive:
        errors.append(
            "results are present while status is PREREGISTERED. Results "
            "belong in a separate file referencing this document's hash; "
            "a boolean lock in an editable file is not a lock."
        )

    if status in ("CONFIRMED", "REJECTED"):
        if not str(
            document.get("preregistration_sha256") or ""
        ).strip():
            errors.append(
                f"status {status} requires preregistration_sha256 naming "
                "the committed preregistration this result answers"
            )
        if not substantive:
            errors.append(
                f"status {status} but no results are recorded"
            )

    return ValidationResult(
        ok=not errors,
        status=status,
        errors=errors,
        warnings=warnings,
        sha256=sha,
    )


def validate_file(
    document_path: str | Path,
    registry_path: str | Path,
    *,
    hypothesis_log_path: str | Path | None = None,
    programme_budget_path: str | Path | None = None,
    holdout_registry_path: str | Path | None = None,
) -> ValidationResult:
    raw = Path(document_path).read_bytes()
    document = json.loads(raw.decode("utf-8"))
    windows = load_discovery_registry(registry_path)
    hypothesis_counts = (
        load_hypothesis_counts(hypothesis_log_path)
        if hypothesis_log_path is not None else None
    )
    programme_budget = (
        load_programme_budget(programme_budget_path)
        if programme_budget_path is not None else None
    )
    holdout_windows = (
        load_holdout_registry(holdout_registry_path)
        if holdout_registry_path is not None else ()
    )
    return validate_edge_statement(
        document,
        discovery_windows=windows,
        holdout_windows=holdout_windows,
        hypothesis_counts=hypothesis_counts,
        programme_budget=programme_budget,
        raw_bytes=raw,
    )
