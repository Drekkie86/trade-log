from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
from typing import Callable

from src.config import get_runtime_setting
from src.operations.audit_export import resolve_audit_dir
from src.providers.thetadata_control import ThetaTerminalHealth, probe_theta_terminal


DEFAULT_FAILURE_THRESHOLD = 2
STATE_FILENAME = "theta_watchdog_state.json"


@dataclass(frozen=True)
class ThetaWatchdogResult:
    observed_at: str
    state: str
    consecutive_failures: int
    failure_threshold: int
    health: dict[str, object]

    @property
    def recovery_required(self) -> bool:
        return self.state == "RECOVERY_REQUIRED"

    def as_dict(self) -> dict[str, object]:
        return asdict(self) | {"recovery_required": self.recovery_required}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _setting_int(name: str, default: int) -> int:
    raw = get_runtime_setting(name)
    if raw in (None, ""):
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be positive.")
    return value


def _read_state(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_json_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def watchdog_state_path(audit_dir: Path | None = None) -> Path:
    directory = resolve_audit_dir() if audit_dir is None else audit_dir
    return directory / STATE_FILENAME


def reset_watchdog_state(
    *,
    audit_dir: Path | None = None,
    detail: str = "reset",
) -> None:
    path = watchdog_state_path(audit_dir)
    payload = {
        "observed_at": _utc_now().isoformat().replace("+00:00", "Z"),
        "state": "RESET",
        "consecutive_failures": 0,
        "detail": detail,
    }
    _atomic_json_write(path, payload)


def evaluate_theta_watchdog(
    *,
    probe: Callable[[], ThetaTerminalHealth] = probe_theta_terminal,
    audit_dir: Path | None = None,
    failure_threshold: int | None = None,
    now: datetime | None = None,
) -> ThetaWatchdogResult:
    threshold = (
        _setting_int(
            "CHRISTIANIA_THETA_WATCHDOG_FAILURE_THRESHOLD",
            DEFAULT_FAILURE_THRESHOLD,
        )
        if failure_threshold is None
        else int(failure_threshold)
    )
    if threshold <= 0:
        raise ValueError("failure_threshold must be positive.")

    observed = _utc_now() if now is None else now.astimezone(UTC)
    path = watchdog_state_path(audit_dir)
    previous = _read_state(path)
    previous_failures = int(previous.get("consecutive_failures") or 0)

    health = probe()
    if health.ready:
        failures = 0
        state = "READY"
    else:
        failures = previous_failures + 1
        state = (
            "RECOVERY_REQUIRED"
            if failures >= threshold
            else "DEGRADED"
        )

    result = ThetaWatchdogResult(
        observed_at=observed.isoformat().replace("+00:00", "Z"),
        state=state,
        consecutive_failures=failures,
        failure_threshold=threshold,
        health=health.as_dict(),
    )
    _atomic_json_write(path, result.as_dict())
    return result
