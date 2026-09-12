from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Callable, Mapping


DEFAULT_AUDIT_DIR = Path("/var/lib/christiania/audit")
DEFAULT_SUPERVISOR_MAX_AGE_MINUTES = 12.0
SUPERVISOR_STATUS_FILENAME = "rc0_supervisor_status.json"
SUPERVISOR_STATE_FILENAME = "rc0_supervisor_state.json"
READINESS_FILENAME = "v1_operational_readiness.json"
DEPLOYED_COMMIT_PATH = Path("/opt/christiania/DEPLOYED_COMMIT")

CORE_SERVICES = (
    "christiania-theta.service",
    "christiania-daemon.service",
    "christiania-app.service",
)

CORE_TIMERS = (
    "christiania-backup.timer",
    "christiania-health.timer",
    "christiania-audit.timer",
    "christiania-restore-drill.timer",
    "christiania-burn-in.timer",
    "christiania-supervisor.timer",
    "christiania-theta-watchdog.timer",
    "christiania-theta-refresh.timer",
    "christiania-v1-readiness.timer",
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class OperationalCheck:
    name: str
    state: str
    detail: str
    blocking: bool = True

    @property
    def passed(self) -> bool:
        return self.state in {"PASS", "INFO"}

    def as_dict(self) -> dict[str, object]:
        return asdict(self) | {"passed": self.passed}


@dataclass(frozen=True)
class OperationalReadiness:
    observed_at: str
    state: str
    operationally_ready: bool
    deployed_commit: str | None
    supervisor_observed_at: str | None
    checks: tuple[OperationalCheck, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "observed_at": self.observed_at,
            "state": self.state,
            "operationally_ready": self.operationally_ready,
            "deployed_commit": self.deployed_commit,
            "supervisor_observed_at": self.supervisor_observed_at,
            "checks": [check.as_dict() for check in self.checks],
        }


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_iso(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _setting_bool(settings: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = settings.get(name)
    if raw in (None, ""):
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


def _setting_float(
    settings: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    raw = settings.get(name)
    if raw in (None, ""):
        return default
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{name} must be positive.")
    return value


def _systemctl_state(unit: str) -> str:
    completed = subprocess.run(
        ["systemctl", "is-active", unit],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    return (completed.stdout or completed.stderr or "unknown").strip()


def _systemctl_enabled(unit: str) -> str:
    completed = subprocess.run(
        ["systemctl", "is-enabled", unit],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    return (completed.stdout or completed.stderr or "unknown").strip()


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


def evaluate_operational_readiness(
    *,
    now: datetime | None = None,
    audit_dir: Path | None = None,
    deployed_commit_path: Path | None = None,
    settings: Mapping[str, str] | None = None,
    service_state: Callable[[str], str] = _systemctl_state,
    timer_enabled: Callable[[str], str] = _systemctl_enabled,
) -> OperationalReadiness:
    observed = _utc_now() if now is None else now.astimezone(UTC)
    configuration = os.environ if settings is None else settings
    directory = (
        Path(configuration.get("CHRISTIANIA_AUDIT_DIR", str(DEFAULT_AUDIT_DIR)))
        if audit_dir is None
        else audit_dir
    )
    commit_path = DEPLOYED_COMMIT_PATH if deployed_commit_path is None else deployed_commit_path
    checks: list[OperationalCheck] = []

    deployed_commit: str | None = None
    try:
        candidate = commit_path.read_text(encoding="utf-8").strip().lower()
    except OSError as exc:
        checks.append(
            OperationalCheck(
                "deployed-commit",
                "FAIL",
                f"Unable to read deployed commit marker: {type(exc).__name__}: {exc}",
            )
        )
    else:
        if _SHA40.fullmatch(candidate):
            deployed_commit = candidate
            checks.append(
                OperationalCheck(
                    "deployed-commit",
                    "PASS",
                    f"Deployed commit marker is valid: {candidate}.",
                )
            )
        else:
            checks.append(
                OperationalCheck(
                    "deployed-commit",
                    "FAIL",
                    f"Deployed commit marker is malformed: {candidate!r}.",
                )
            )

    supervisor = _read_json(directory / SUPERVISOR_STATUS_FILENAME)
    supervisor_observed = _parse_iso(supervisor.get("observed_at"))
    max_age = timedelta(
        minutes=_setting_float(
            configuration,
            "CHRISTIANIA_V1_SUPERVISOR_MAX_AGE_MINUTES",
            DEFAULT_SUPERVISOR_MAX_AGE_MINUTES,
        )
    )

    if not supervisor:
        checks.append(
            OperationalCheck(
                "supervisor-status-present",
                "FAIL",
                "Supervisor status file is missing or unreadable.",
            )
        )
    else:
        checks.append(
            OperationalCheck(
                "supervisor-status-present",
                "PASS",
                "Supervisor status file is present and readable.",
            )
        )

    if supervisor_observed is None:
        checks.append(
            OperationalCheck(
                "supervisor-status-freshness",
                "FAIL",
                "Supervisor status has no valid observed_at timestamp.",
            )
        )
    else:
        age = observed - supervisor_observed
        fresh = timedelta(0) <= age <= max_age
        checks.append(
            OperationalCheck(
                "supervisor-status-freshness",
                "PASS" if fresh else "FAIL",
                (
                    f"Supervisor age={age.total_seconds() / 60:.1f} minutes; "
                    f"maximum={max_age.total_seconds() / 60:.1f}."
                ),
            )
        )

    supervisor_healthy = supervisor.get("state") == "HEALTHY"
    checks.append(
        OperationalCheck(
            "supervisor-health",
            "PASS" if supervisor_healthy else "FAIL",
            f"Supervisor state={supervisor.get('state') or 'UNKNOWN'}.",
        )
    )

    raw_checks = supervisor.get("checks")
    supervisor_checks = raw_checks if isinstance(raw_checks, list) else []
    research_checks = [
        item
        for item in supervisor_checks
        if isinstance(item, dict) and item.get("name") == "research-progress"
    ]
    if len(research_checks) != 1:
        checks.append(
            OperationalCheck(
                "research-production-proof",
                "FAIL",
                (
                    "Supervisor must contain exactly one research-progress check; "
                    f"found {len(research_checks)}."
                ),
            )
        )
    else:
        research_state = str(research_checks[0].get("state") or "UNKNOWN")
        research_detail = str(research_checks[0].get("detail") or "")
        checks.append(
            OperationalCheck(
                "research-production-proof",
                "PASS" if research_state == "PASS" else "FAIL",
                f"research-progress={research_state}: {research_detail}",
            )
        )

    external_required = _setting_bool(
        configuration,
        "CHRISTIANIA_REQUIRE_EXTERNAL_OBSERVABILITY",
        False,
    )
    checks.append(
        OperationalCheck(
            "external-observability-required",
            "PASS" if external_required else "FAIL",
            (
                "External observability is fail-closed."
                if external_required
                else "CHRISTIANIA_REQUIRE_EXTERNAL_OBSERVABILITY is not enabled."
            ),
        )
    )

    for name in (
        "CHRISTIANIA_ALERT_WEBHOOK_URL",
        "CHRISTIANIA_HEARTBEAT_URL",
        "CHRISTIANIA_HEARTBEAT_FAILURE_URL",
    ):
        configured = bool(str(configuration.get(name, "")).strip())
        checks.append(
            OperationalCheck(
                f"config:{name}",
                "PASS" if configured else "FAIL",
                f"{name} is {'configured' if configured else 'missing'}.",
            )
        )

    supervisor_state = _read_json(directory / SUPERVISOR_STATE_FILENAME)
    state_observed = _parse_iso(supervisor_state.get("observed_at"))
    if state_observed is None:
        checks.append(
            OperationalCheck(
                "external-heartbeat-freshness",
                "FAIL",
                "Supervisor state has no valid observed_at timestamp.",
            )
        )
    else:
        state_age = observed - state_observed
        state_fresh = timedelta(0) <= state_age <= max_age
        heartbeat_sent = supervisor_state.get("heartbeat_state") == "SENT"
        checks.append(
            OperationalCheck(
                "external-heartbeat-freshness",
                "PASS" if state_fresh and heartbeat_sent else "FAIL",
                (
                    f"heartbeat_state={supervisor_state.get('heartbeat_state') or 'UNKNOWN'}; "
                    f"age={state_age.total_seconds() / 60:.1f} minutes."
                ),
            )
        )

    for unit in CORE_SERVICES:
        state = service_state(unit)
        checks.append(
            OperationalCheck(
                f"service:{unit}",
                "PASS" if state == "active" else "FAIL",
                f"{unit} is {state}.",
            )
        )

    for unit in CORE_TIMERS:
        state = timer_enabled(unit)
        checks.append(
            OperationalCheck(
                f"timer:{unit}",
                "PASS" if state == "enabled" else "FAIL",
                f"{unit} is {state}.",
            )
        )

    blockers = [
        check
        for check in checks
        if check.blocking and check.state == "FAIL"
    ]
    ready = not blockers
    return OperationalReadiness(
        observed_at=observed.isoformat().replace("+00:00", "Z"),
        state="OPERATIONALLY_READY" if ready else "OPERATIONALLY_NOT_READY",
        operationally_ready=ready,
        deployed_commit=deployed_commit,
        supervisor_observed_at=(
            None
            if supervisor_observed is None
            else supervisor_observed.isoformat().replace("+00:00", "Z")
        ),
        checks=tuple(checks),
    )


def persist_operational_readiness(
    report: OperationalReadiness,
    *,
    audit_dir: Path | None = None,
) -> Path:
    directory = (
        Path(os.environ.get("CHRISTIANIA_AUDIT_DIR", str(DEFAULT_AUDIT_DIR)))
        if audit_dir is None
        else audit_dir
    )
    path = directory / READINESS_FILENAME
    _atomic_json_write(path, report.as_dict())
    return path
