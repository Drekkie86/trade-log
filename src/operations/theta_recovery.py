from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
from typing import Callable

from src.operations.audit_export import resolve_audit_dir
from src.operations.theta_watchdog import reset_watchdog_state
from src.providers.thetadata_control import (
    ThetaTerminalHealth,
    wait_for_theta_terminal,
)


RECOVERY_LOG_FILENAME = "theta_recovery.jsonl"
THETA_UNIT = "christiania-theta.service"
DAEMON_UNIT = "christiania-daemon.service"


@dataclass(frozen=True)
class ThetaRecoveryResult:
    observed_at: str
    reason: str
    state: str
    daemon_was_active: bool
    daemon_started: bool
    theta_health: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _systemctl(
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ("systemctl", *args),
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    if check and completed.returncode != 0:
        detail = (
            completed.stderr
            or completed.stdout
            or f"return code {completed.returncode}"
        ).strip()
        raise RuntimeError(
            f"systemctl {' '.join(args)} failed: {detail}"
        )
    return completed


def _unit_active(unit: str) -> bool:
    completed = _systemctl("is-active", unit, check=False)
    return completed.returncode == 0 and completed.stdout.strip() == "active"


def _append_event(
    payload: dict[str, object],
    *,
    audit_dir: Path | None = None,
) -> None:
    directory = resolve_audit_dir() if audit_dir is None else audit_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / RECOVERY_LOG_FILENAME
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def recover_theta(
    *,
    reason: str,
    wait_seconds: float = 120.0,
    poll_seconds: float = 2.0,
    audit_dir: Path | None = None,
    systemctl: Callable[..., subprocess.CompletedProcess[str]] = _systemctl,
    active: Callable[[str], bool] = _unit_active,
    wait_ready: Callable[..., ThetaTerminalHealth] = wait_for_theta_terminal,
) -> ThetaRecoveryResult:
    reason = str(reason).strip()
    if not reason:
        raise ValueError("Recovery reason cannot be blank.")

    observed = _utc_now().isoformat().replace("+00:00", "Z")
    daemon_was_active = active(DAEMON_UNIT)
    daemon_started = False

    _append_event(
        {
            "observed_at": observed,
            "event": "THETA_RECOVERY_STARTED",
            "reason": reason,
            "daemon_was_active": daemon_was_active,
        },
        audit_dir=audit_dir,
    )

    if daemon_was_active:
        systemctl("stop", DAEMON_UNIT)

    try:
        systemctl("restart", THETA_UNIT)
        health = wait_ready(
            wait_seconds=wait_seconds,
            poll_seconds=poll_seconds,
        )
        if not health.ready:
            raise RuntimeError(
                f"Theta did not recover: {health.state}: {health.detail}"
            )

        reset_watchdog_state(
            audit_dir=audit_dir,
            detail=f"successful recovery: {reason}",
        )
        systemctl(
            "reset-failed",
            "christiania-theta-watchdog.service",
            check=False,
        )
        if daemon_was_active:
            systemctl("start", DAEMON_UNIT)
            daemon_started = True

        result = ThetaRecoveryResult(
            observed_at=_utc_now().isoformat().replace("+00:00", "Z"),
            reason=reason,
            state="RECOVERED",
            daemon_was_active=daemon_was_active,
            daemon_started=daemon_started,
            theta_health=health.as_dict(),
        )
        _append_event(
            {
                "event": "THETA_RECOVERY_COMPLETED",
                **result.as_dict(),
            },
            audit_dir=audit_dir,
        )
        return result
    except Exception as exc:
        _append_event(
            {
                "observed_at": _utc_now().isoformat().replace("+00:00", "Z"),
                "event": "THETA_RECOVERY_FAILED",
                "reason": reason,
                "daemon_was_active": daemon_was_active,
                "daemon_started": daemon_started,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
            audit_dir=audit_dir,
        )
        raise
