from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.config import get_runtime_setting
from src.dashboard.read_model import load_command_deck
from src.database.repository import EXPECTED_SCHEMA_VERSION, resolve_db_path
from src.operations.backup_recovery import inventory_backups_fast
from src.operations.audit_export import resolve_audit_dir


DEFAULT_MIN_FREE_BYTES = 15 * 1024**3
DEFAULT_MIN_FREE_FRACTION = 0.15
DEFAULT_BACKUP_METADATA_MAX_AGE_HOURS = 30.0
DEFAULT_ALERT_TIMEOUT_SECONDS = 5.0
DEFAULT_STATUS_FILENAME = "rc0_supervisor_status.json"
DEFAULT_STATE_FILENAME = "rc0_supervisor_state.json"

MIB = 1024**2
MEMORY_POLICY_BYTES = {
    "christiania-theta.service": {
        "warning": 1024 * MIB,
        "high": 1536 * MIB,
        "max": 2560 * MIB,
    },
    "christiania-daemon.service": {
        "warning": 512 * MIB,
        "high": 768 * MIB,
        "max": 1280 * MIB,
    },
    "christiania-app.service": {
        "warning": 384 * MIB,
        "high": 512 * MIB,
        "max": 1024 * MIB,
    },
}

CORE_SERVICES = tuple(MEMORY_POLICY_BYTES)
CORE_TIMERS = (
    "christiania-backup.timer",
    "christiania-health.timer",
    "christiania-audit.timer",
    "christiania-restore-drill.timer",
    "christiania-burn-in.timer",
    "christiania-supervisor.timer",
)


@dataclass(frozen=True)
class SupervisorCheck:
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
class SupervisorSnapshot:
    observed_at: str
    state: str
    checks: tuple[SupervisorCheck, ...]
    schema_version: int | None
    daemon_state: str | None
    theta_state: str | None
    backup_file_count: int
    latest_backup_metadata_age_hours: float | None
    disk_free_bytes: int | None
    disk_free_fraction: float | None
    service_memory: dict[str, dict[str, int | None]] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return self.state == "HEALTHY"

    def as_dict(self) -> dict[str, object]:
        return {
            "observed_at": self.observed_at,
            "state": self.state,
            "healthy": self.healthy,
            "schema_version": self.schema_version,
            "daemon_state": self.daemon_state,
            "theta_state": self.theta_state,
            "backup_file_count": self.backup_file_count,
            "latest_backup_metadata_age_hours": self.latest_backup_metadata_age_hours,
            "disk_free_bytes": self.disk_free_bytes,
            "disk_free_fraction": self.disk_free_fraction,
            "service_memory": self.service_memory,
            "checks": [check.as_dict() for check in self.checks],
        }


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _setting_float(name: str, default: float) -> float:
    raw = get_runtime_setting(name)
    if raw in (None, ""):
        return default
    value = float(raw)
    if value < 0:
        raise ValueError(f"{name} cannot be negative.")
    return value


def _setting_int(name: str, default: int) -> int:
    raw = get_runtime_setting(name)
    if raw in (None, ""):
        return default
    value = int(raw)
    if value < 0:
        raise ValueError(f"{name} cannot be negative.")
    return value


def _systemd_state(unit: str) -> str:
    completed = subprocess.run(
        ["systemctl", "is-active", unit],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    return (completed.stdout or completed.stderr or "unknown").strip()


def _timer_enabled(unit: str) -> str:
    completed = subprocess.run(
        ["systemctl", "is-enabled", unit],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    return (completed.stdout or completed.stderr or "unknown").strip()


def _systemd_properties(unit: str) -> dict[str, str]:
    completed = subprocess.run(
        [
            "systemctl",
            "show",
            unit,
            "--property=MemoryCurrent",
            "--property=MemoryPeak",
            "--property=NRestarts",
            "--property=MemoryHigh",
            "--property=MemoryMax",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise RuntimeError(f"systemctl show failed for {unit}: {detail}")

    properties: dict[str, str] = {}
    for raw_line in completed.stdout.splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        properties[key.strip()] = value.strip()
    return properties


def _parse_nonnegative_int(raw: object) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or not text.isdecimal():
        return None
    value = int(text)
    return value if value >= 0 else None


def _memory_check(
    unit: str,
    properties: dict[str, str],
) -> tuple[SupervisorCheck, dict[str, int | None]]:
    policy = MEMORY_POLICY_BYTES[unit]
    current = _parse_nonnegative_int(properties.get("MemoryCurrent"))
    peak = _parse_nonnegative_int(properties.get("MemoryPeak"))
    restarts = _parse_nonnegative_int(properties.get("NRestarts"))
    high = _parse_nonnegative_int(properties.get("MemoryHigh"))
    maximum = _parse_nonnegative_int(properties.get("MemoryMax"))

    telemetry = {
        "current_bytes": current,
        "peak_bytes": peak,
        "nrestarts": restarts,
        "warning_bytes": policy["warning"],
        "memory_high_bytes": high,
        "expected_memory_high_bytes": policy["high"],
        "memory_max_bytes": maximum,
        "expected_memory_max_bytes": policy["max"],
    }

    failures: list[str] = []
    if current is None:
        failures.append("MemoryCurrent unavailable or malformed")
    elif current >= policy["warning"]:
        failures.append(
            f"MemoryCurrent={current} reached warning={policy['warning']}"
        )

    if high != policy["high"]:
        failures.append(
            f"MemoryHigh={high!r}; expected={policy['high']}"
        )
    if maximum != policy["max"]:
        failures.append(
            f"MemoryMax={maximum!r}; expected={policy['max']}"
        )

    if failures:
        return (
            SupervisorCheck(
                f"memory:{unit}",
                "FAIL",
                "; ".join(failures) + ".",
            ),
            telemetry,
        )

    return (
        SupervisorCheck(
            f"memory:{unit}",
            "PASS",
            (
                f"Current={current}; peak={peak}; restarts={restarts}; "
                f"warning={policy['warning']}; MemoryHigh={high}; "
                f"MemoryMax={maximum}."
            ),
        ),
        telemetry,
    )


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


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _post_alert(
    url: str,
    payload: dict[str, object],
    *,
    timeout_seconds: float = DEFAULT_ALERT_TIMEOUT_SECONDS,
) -> None:
    request = Request(
        url,
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Christiania-RC0-Supervisor/1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if int(response.status) < 200 or int(response.status) >= 300:
                raise RuntimeError(
                    f"Alert webhook returned HTTP {int(response.status)}."
                )
    except URLError as exc:
        raise ConnectionError(f"Alert webhook unreachable: {exc}") from exc


def collect_snapshot(
    *,
    now: datetime | None = None,
    service_state: Callable[[str], str] = _systemd_state,
    timer_state: Callable[[str], str] = _timer_enabled,
    service_properties: Callable[[str], dict[str, str]] = _systemd_properties,
    disk_usage: Callable[[str | os.PathLike[str]], object] = shutil.disk_usage,
) -> SupervisorSnapshot:
    observed = _utc_now() if now is None else now.astimezone(UTC)
    checks: list[SupervisorCheck] = []
    service_memory: dict[str, dict[str, int | None]] = {}

    deck = load_command_deck(
        include_provider_health=True,
        deep_integrity=False,
    )
    db = deck.get("database", {})
    schema_version = db.get("schema_version")
    db_ok = (
        deck.get("ready") is True
        and schema_version == EXPECTED_SCHEMA_VERSION
        and str(db.get("journal_mode", "")).lower() == "wal"
    )
    checks.append(
        SupervisorCheck(
            "database-fast-health",
            "PASS" if db_ok else "FAIL",
            (
                f"Schema v{schema_version}; WAL; interactive read model ready."
                if db_ok
                else f"Fast database/read-model check failed: {deck.get('reason')}"
            ),
        )
    )

    daemon = deck.get("daemon_health", {})
    daemon_state = str(daemon.get("state") or "UNKNOWN")
    daemon_ok = daemon_state == "HEALTHY"
    checks.append(
        SupervisorCheck(
            "daemon-heartbeat",
            "PASS" if daemon_ok else "FAIL",
            (
                f"Daemon heartbeat healthy; age={daemon.get('heartbeat_age_seconds')}s."
                if daemon_ok
                else f"Daemon state: {daemon_state}."
            ),
        )
    )

    theta = deck.get("theta_health", {})
    theta_state = str(theta.get("state") or "UNKNOWN")
    theta_ok = theta.get("ready") is True
    checks.append(
        SupervisorCheck(
            "theta-readiness",
            "PASS" if theta_ok else "FAIL",
            (
                f"Theta ready; latency={theta.get('latency_ms')}ms."
                if theta_ok
                else f"Theta state: {theta_state}."
            ),
        )
    )

    for unit in CORE_SERVICES:
        state = service_state(unit)
        checks.append(
            SupervisorCheck(
                f"systemd:{unit}",
                "PASS" if state == "active" else "FAIL",
                f"{unit} is {state}.",
            )
        )
        try:
            memory_check, telemetry = _memory_check(
                unit,
                service_properties(unit),
            )
        except Exception as exc:
            memory_check = SupervisorCheck(
                f"memory:{unit}",
                "FAIL",
                f"Unable to read effective memory policy: {type(exc).__name__}: {exc}",
            )
            telemetry = {
                "current_bytes": None,
                "peak_bytes": None,
                "nrestarts": None,
                "warning_bytes": MEMORY_POLICY_BYTES[unit]["warning"],
                "memory_high_bytes": None,
                "expected_memory_high_bytes": MEMORY_POLICY_BYTES[unit]["high"],
                "memory_max_bytes": None,
                "expected_memory_max_bytes": MEMORY_POLICY_BYTES[unit]["max"],
            }
        checks.append(memory_check)
        service_memory[unit] = telemetry

    for unit in CORE_TIMERS:
        state = timer_state(unit)
        checks.append(
            SupervisorCheck(
                f"timer:{unit}",
                "PASS" if state == "enabled" else "FAIL",
                f"{unit} is {state}.",
            )
        )

    backup_inventory = inventory_backups_fast().as_dict()
    backup_entries = backup_inventory.get("entries", [])
    latest_backup_age = min(
        (
            float(entry["age_hours"])
            for entry in backup_entries
            if entry.get("age_hours") is not None
        ),
        default=None,
    )
    max_backup_age = _setting_float(
        "CHRISTIANIA_RC0_BACKUP_METADATA_MAX_AGE_HOURS",
        DEFAULT_BACKUP_METADATA_MAX_AGE_HOURS,
    )
    backup_ok = (
        int(backup_inventory.get("total_files", 0) or 0) > 0
        and latest_backup_age is not None
        and latest_backup_age <= max_backup_age
    )
    checks.append(
        SupervisorCheck(
            "backup-freshness-metadata",
            "PASS" if backup_ok else "FAIL",
            (
                f"Latest backup file metadata age {latest_backup_age:.2f}h; "
                "deep validity is checked separately by christiania-health."
                if latest_backup_age is not None
                else "No backup file found."
            ),
        )
    )

    db_path = resolve_db_path()
    usage = disk_usage(db_path.parent)
    total = int(getattr(usage, "total"))
    free = int(getattr(usage, "free"))
    free_fraction = 0.0 if total <= 0 else free / total
    min_free_bytes = _setting_int(
        "CHRISTIANIA_RC0_MIN_FREE_BYTES",
        DEFAULT_MIN_FREE_BYTES,
    )
    min_free_fraction = _setting_float(
        "CHRISTIANIA_RC0_MIN_FREE_FRACTION",
        DEFAULT_MIN_FREE_FRACTION,
    )
    disk_ok = free >= min_free_bytes and free_fraction >= min_free_fraction
    checks.append(
        SupervisorCheck(
            "disk-headroom",
            "PASS" if disk_ok else "FAIL",
            (
                f"Free={free} bytes ({free_fraction:.1%}); "
                f"minimum={min_free_bytes} bytes and {min_free_fraction:.1%}."
            ),
        )
    )

    blockers = [
        check for check in checks
        if check.blocking and check.state == "FAIL"
    ]
    state = "HEALTHY" if not blockers else "UNHEALTHY"

    return SupervisorSnapshot(
        observed_at=observed.isoformat().replace("+00:00", "Z"),
        state=state,
        checks=tuple(checks),
        schema_version=None if schema_version is None else int(schema_version),
        daemon_state=daemon_state,
        theta_state=theta_state,
        backup_file_count=int(backup_inventory.get("total_files", 0) or 0),
        latest_backup_metadata_age_hours=latest_backup_age,
        disk_free_bytes=free,
        disk_free_fraction=free_fraction,
        service_memory=service_memory,
    )


def persist_and_alert(
    snapshot: SupervisorSnapshot,
    *,
    send_alert: bool = True,
    audit_dir: Path | None = None,
) -> dict[str, object]:
    directory = resolve_audit_dir() if audit_dir is None else audit_dir
    status_path = directory / DEFAULT_STATUS_FILENAME
    state_path = directory / DEFAULT_STATE_FILENAME

    current = snapshot.as_dict()
    previous = _read_json(state_path)
    previous_state = str(previous.get("state") or "UNKNOWN")
    transition = previous_state != snapshot.state

    _atomic_json_write(status_path, current)

    alert_url = get_runtime_setting("CHRISTIANIA_ALERT_WEBHOOK_URL")
    alert_state = "NOT_CONFIGURED"
    alert_error = None

    if send_alert and alert_url and transition:
        payload = {
            "application": "Christiania",
            "environment": "RC0",
            "event": "SUPERVISOR_STATE_TRANSITION",
            "previous_state": previous_state,
            "state": snapshot.state,
            "observed_at": snapshot.observed_at,
            "failed_checks": [
                check.as_dict()
                for check in snapshot.checks
                if check.state == "FAIL"
            ],
        }
        try:
            _post_alert(
                alert_url,
                payload,
                timeout_seconds=_setting_float(
                    "CHRISTIANIA_ALERT_TIMEOUT_SECONDS",
                    DEFAULT_ALERT_TIMEOUT_SECONDS,
                ),
            )
        except Exception as exc:
            alert_state = "FAILED"
            alert_error = f"{type(exc).__name__}: {exc}"
        else:
            alert_state = "SENT"

    state_payload = {
        "state": snapshot.state,
        "observed_at": snapshot.observed_at,
        "previous_state": previous_state,
        "transition": transition,
        "alert_state": alert_state,
        "alert_error": alert_error,
    }
    _atomic_json_write(state_path, state_payload)
    return state_payload
