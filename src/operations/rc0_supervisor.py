from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.config import get_runtime_setting
from src.dashboard.read_model import load_command_deck
from src.database.repository import (
    EXPECTED_SCHEMA_VERSION,
    resolve_db_path,
)
from src.operations.audit_export import resolve_audit_dir
from src.operations.backup_recovery import (
    inventory_backups_fast,
)
from src.operations.market_calendar import (
    market_clock_snapshot,
)
from src.operations.service_resources import (
    SERVICE_RESOURCE_POLICIES,
    ServiceResourcePolicy,
    service_resource_policy,
)


DEFAULT_MIN_FREE_BYTES = 15 * 1024**3
DEFAULT_MIN_FREE_FRACTION = 0.15
DEFAULT_BACKUP_METADATA_MAX_AGE_HOURS = 30.0
DEFAULT_ALERT_TIMEOUT_SECONDS = 5.0
DEFAULT_STATUS_FILENAME = "rc0_supervisor_status.json"
DEFAULT_STATE_FILENAME = "rc0_supervisor_state.json"
DEFAULT_RESEARCH_SUCCESS_MAX_AGE_MINUTES = 40.0


CORE_SERVICES = (
    "christiania-theta.service",
    "christiania-daemon.service",
    "christiania-app.service",
)

RUNTIME_MEMORY_SERVICES = CORE_SERVICES

EXPECTED_ENABLED_TIMERS = (
    "christiania-backup.timer",
    "christiania-audit.timer",
    "christiania-restore-drill.timer",
    "christiania-supervisor.timer",
    "christiania-theta-watchdog.timer",
    "christiania-theta-refresh.timer",
)

INTENTIONALLY_DISABLED_TIMERS = (
    "christiania-health.timer",
    "christiania-burn-in.timer",
    "christiania-v1-readiness.timer",
)


@dataclass(frozen=True)
class SupervisorCheck:
    name: str
    state: str
    detail: str
    blocking: bool = True

    @property
    def passed(self) -> bool:
        return self.state in {
            "PASS",
            "INFO",
        }

    def as_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "passed": self.passed,
        }


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
    service_memory: dict[
        str,
        dict[str, int | None],
    ] = field(default_factory=dict)

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
            "latest_backup_metadata_age_hours": (
                self.latest_backup_metadata_age_hours
            ),
            "disk_free_bytes": self.disk_free_bytes,
            "disk_free_fraction": self.disk_free_fraction,
            "service_memory": self.service_memory,
            "checks": [
                check.as_dict()
                for check in self.checks
            ],
        }


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _setting_float(
    name: str,
    default: float,
) -> float:
    raw = get_runtime_setting(name)

    if raw in (
        None,
        "",
    ):
        return default

    value = float(raw)

    if value < 0:
        raise ValueError(
            f"{name} cannot be negative."
        )

    return value


def _setting_int(
    name: str,
    default: int,
) -> int:
    raw = get_runtime_setting(name)

    if raw in (
        None,
        "",
    ):
        return default

    value = int(raw)

    if value < 0:
        raise ValueError(
            f"{name} cannot be negative."
        )

    return value


def _setting_bool(
    name: str,
    default: bool = False,
) -> bool:
    raw = get_runtime_setting(name)

    if raw in (
        None,
        "",
    ):
        return default

    value = str(
        raw
    ).strip().lower()

    if value in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True

    if value in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False

    raise ValueError(
        f"{name} must be a boolean value."
    )


def _systemd_state(
    unit: str,
) -> str:
    completed = subprocess.run(
        [
            "systemctl",
            "is-active",
            unit,
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    return (
        completed.stdout
        or completed.stderr
        or "unknown"
    ).strip()


def _timer_enabled(
    unit: str,
) -> str:
    completed = subprocess.run(
        [
            "systemctl",
            "is-enabled",
            unit,
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    return (
        completed.stdout
        or completed.stderr
        or "unknown"
    ).strip()


def _systemd_properties(
    unit: str,
) -> dict[str, str]:
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
            "--property=TimeoutStartUSec",
            "--property=TimeoutStopUSec",
            "--property=OOMPolicy",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    if completed.returncode != 0:
        detail = (
            completed.stderr
            or completed.stdout
            or "unknown error"
        ).strip()

        raise RuntimeError(
            "systemctl show failed for "
            f"{unit}: {detail}"
        )

    properties: dict[str, str] = {}

    for raw_line in completed.stdout.splitlines():
        if "=" not in raw_line:
            continue

        key, value = raw_line.split(
            "=",
            1,
        )

        properties[
            key.strip()
        ] = value.strip()

    return properties


def _parse_nonnegative_int(
    raw: object,
) -> int | None:
    if raw is None:
        return None

    text = str(
        raw
    ).strip()

    if (
        not text
        or not text.isdecimal()
    ):
        return None

    value = int(text)

    return (
        value
        if value >= 0
        else None
    )


_SYSTEMD_DURATION_TOKEN = re.compile(
    r"""
    (?P<value>\d+(?:\.\d+)?)
    \s*
    (?P<unit>
        usec|us|µs|
        msec|ms|
        sec|s|
        min|
        h|
        d
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SYSTEMD_DURATION_MULTIPLIERS = {
    "usec": 1,
    "us": 1,
    "µs": 1,
    "msec": 1_000,
    "ms": 1_000,
    "sec": 1_000_000,
    "s": 1_000_000,
    "min": 60 * 1_000_000,
    "h": 60 * 60 * 1_000_000,
    "d": 24 * 60 * 60 * 1_000_000,
}


def _parse_systemd_usec(
    raw: object,
) -> int | None:
    """
    Parse systemd timeout properties into microseconds.

    `systemctl show` may expose values either as raw integer
    microseconds or as normalized human-readable durations such
    as `1min 30s`.
    """
    if raw is None:
        return None

    text = str(
        raw
    ).strip()

    if not text:
        return None

    direct = _parse_nonnegative_int(
        text
    )

    if direct is not None:
        return direct

    if text.lower() == "infinity":
        return None

    position = 0
    total = 0.0
    matched = False

    for match in _SYSTEMD_DURATION_TOKEN.finditer(
        text
    ):
        gap = text[
            position:match.start()
        ]

        if gap.strip():
            return None

        matched = True

        value = float(
            match.group("value")
        )
        unit = (
            match.group("unit")
            .lower()
        )

        multiplier = (
            _SYSTEMD_DURATION_MULTIPLIERS[
                unit
            ]
        )

        total += (
            value
            * multiplier
        )

        position = match.end()

    if (
        not matched
        or text[position:].strip()
    ):
        return None

    if total < 0:
        return None

    return int(
        round(total)
    )


def _memory_check(
    unit: str,
    properties: dict[str, str],
) -> tuple[
    SupervisorCheck,
    dict[str, int | None],
]:
    policy = service_resource_policy(
        unit
    )

    current = _parse_nonnegative_int(
        properties.get(
            "MemoryCurrent"
        )
    )
    peak = _parse_nonnegative_int(
        properties.get(
            "MemoryPeak"
        )
    )
    restarts = _parse_nonnegative_int(
        properties.get(
            "NRestarts"
        )
    )
    high = _parse_nonnegative_int(
        properties.get(
            "MemoryHigh"
        )
    )
    maximum = _parse_nonnegative_int(
        properties.get(
            "MemoryMax"
        )
    )

    telemetry = {
        "current_bytes": current,
        "peak_bytes": peak,
        "nrestarts": restarts,
        "warning_bytes": (
            policy.memory_warning_bytes
        ),
        "memory_high_bytes": high,
        "expected_memory_high_bytes": (
            policy.memory_high_bytes
        ),
        "memory_max_bytes": maximum,
        "expected_memory_max_bytes": (
            policy.memory_max_bytes
        ),
    }

    failures: list[str] = []

    if current is None:
        failures.append(
            "MemoryCurrent unavailable "
            "or malformed"
        )
    elif (
        current
        >= policy.memory_warning_bytes
    ):
        failures.append(
            "MemoryCurrent="
            f"{current} reached warning="
            f"{policy.memory_warning_bytes}"
        )

    if (
        high
        != policy.memory_high_bytes
    ):
        failures.append(
            f"MemoryHigh={high!r}; "
            "expected="
            f"{policy.memory_high_bytes}"
        )

    if (
        maximum
        != policy.memory_max_bytes
    ):
        failures.append(
            f"MemoryMax={maximum!r}; "
            "expected="
            f"{policy.memory_max_bytes}"
        )

    if failures:
        return (
            SupervisorCheck(
                f"memory:{unit}",
                "FAIL",
                "; ".join(
                    failures
                )
                + ".",
            ),
            telemetry,
        )

    return (
        SupervisorCheck(
            f"memory:{unit}",
            "PASS",
            (
                f"Current={current}; "
                f"peak={peak}; "
                f"restarts={restarts}; "
                "warning="
                f"{policy.memory_warning_bytes}; "
                f"MemoryHigh={high}; "
                f"MemoryMax={maximum}."
            ),
        ),
        telemetry,
    )


def _resource_policy_check(
    unit: str,
    properties: dict[str, str],
) -> SupervisorCheck:
    policy = service_resource_policy(
        unit
    )

    high = _parse_nonnegative_int(
        properties.get(
            "MemoryHigh"
        )
    )
    maximum = _parse_nonnegative_int(
        properties.get(
            "MemoryMax"
        )
    )
    timeout_start_usec = (
        _parse_systemd_usec(
            properties.get(
                "TimeoutStartUSec"
            )
        )
    )
    timeout_stop_usec = (
        _parse_systemd_usec(
            properties.get(
                "TimeoutStopUSec"
            )
        )
    )
    oom_policy = str(
        properties.get(
            "OOMPolicy"
        )
        or ""
    ).strip()

    expected_start_usec = (
        policy.timeout_start_seconds
        * 1_000_000
    )
    expected_stop_usec = (
        policy.timeout_stop_seconds
        * 1_000_000
    )

    failures: list[str] = []

    if (
        high
        != policy.memory_high_bytes
    ):
        failures.append(
            f"MemoryHigh={high!r}; "
            "expected="
            f"{policy.memory_high_bytes}"
        )

    if (
        maximum
        != policy.memory_max_bytes
    ):
        failures.append(
            f"MemoryMax={maximum!r}; "
            "expected="
            f"{policy.memory_max_bytes}"
        )

    if (
        timeout_start_usec
        != expected_start_usec
    ):
        failures.append(
            "TimeoutStartUSec="
            f"{timeout_start_usec!r}; "
            "expected="
            f"{expected_start_usec}"
        )

    if (
        timeout_stop_usec
        != expected_stop_usec
    ):
        failures.append(
            "TimeoutStopUSec="
            f"{timeout_stop_usec!r}; "
            "expected="
            f"{expected_stop_usec}"
        )

    if (
        oom_policy
        != policy.oom_policy
    ):
        failures.append(
            f"OOMPolicy={oom_policy!r}; "
            "expected="
            f"{policy.oom_policy!r}"
        )

    if failures:
        return SupervisorCheck(
            f"resource-policy:{unit}",
            "FAIL",
            "; ".join(
                failures
            )
            + ".",
        )

    return SupervisorCheck(
        f"resource-policy:{unit}",
        "PASS",
        (
            "Effective systemd resource "
            "policy matches canonical "
            "Christiania policy."
        ),
    )


def _resource_policy_failure(
    unit: str,
    exc: Exception,
) -> SupervisorCheck:
    return SupervisorCheck(
        f"resource-policy:{unit}",
        "FAIL",
        (
            "Unable to read effective "
            "systemd resource policy: "
            f"{type(exc).__name__}: {exc}"
        ),
    )


def _memory_failure(
    unit: str,
    policy: ServiceResourcePolicy,
    exc: Exception,
) -> tuple[
    SupervisorCheck,
    dict[str, int | None],
]:
    return (
        SupervisorCheck(
            f"memory:{unit}",
            "FAIL",
            (
                "Unable to read effective "
                "memory policy: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        ),
        {
            "current_bytes": None,
            "peak_bytes": None,
            "nrestarts": None,
            "warning_bytes": (
                policy.memory_warning_bytes
            ),
            "memory_high_bytes": None,
            "expected_memory_high_bytes": (
                policy.memory_high_bytes
            ),
            "memory_max_bytes": None,
            "expected_memory_max_bytes": (
                policy.memory_max_bytes
            ),
        },
    )


def _parse_iso_datetime(
    value: object,
) -> datetime | None:
    if value in (
        None,
        "",
    ):
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return None

    return parsed.astimezone(
        UTC
    )


def _research_progress_check(
    db_path: Path,
    observed: datetime,
) -> SupervisorCheck:
    """
    Verify successful research production.

    Process liveness alone is insufficient.
    The append-only daemon iteration table is
    the operational source of truth.
    """
    observed = observed.astimezone(
        UTC
    )

    try:
        uri = (
            f"file:{db_path}?mode=ro"
        )
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=5,
        )
        conn.row_factory = sqlite3.Row

        try:
            rows = conn.execute(
                """
                SELECT
                    id,
                    scheduled_for,
                    started_at,
                    completed_at,
                    status,
                    error_type,
                    error_message
                FROM research_daemon_iterations
                ORDER BY
                    scheduled_for DESC,
                    id DESC
                LIMIT 64;
                """
            ).fetchall()
        finally:
            conn.close()

    except Exception as exc:
        return SupervisorCheck(
            "research-progress",
            "FAIL",
            (
                "Unable to inspect daemon "
                "iteration evidence: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        )

    clock = market_clock_snapshot(
        now=observed
    )

    if not rows:
        if clock.state in {
            "ACTIVE_SAMPLE_WINDOW",
            "AFTER_SAMPLE_WINDOW",
        }:
            return SupervisorCheck(
                "research-progress",
                "FAIL",
                (
                    "No daemon iteration "
                    "evidence exists during "
                    f"{clock.state}."
                ),
            )

        return SupervisorCheck(
            "research-progress",
            "INFO",
            (
                "No daemon iteration "
                "evidence yet; market "
                f"state={clock.state}."
            ),
            blocking=False,
        )

    latest = rows[0]

    latest_status = str(
        latest["status"]
        or "UNKNOWN"
    ).upper()

    if latest_status in {
        "FAILED",
        "ORPHANED",
    }:
        error_type = str(
            latest["error_type"]
            or "UNKNOWN_ERROR"
        )
        error_message = str(
            latest["error_message"]
            or ""
        ).strip()

        detail = (
            "Latest scheduled research "
            f"iteration is {latest_status}: "
            f"{error_type}"
        )

        if error_message:
            detail += (
                f": {error_message}"
            )

        return SupervisorCheck(
            "research-progress",
            "FAIL",
            detail,
        )

    latest_success = next(
        (
            row
            for row in rows
            if str(
                row["status"]
                or ""
            ).upper()
            == "COMPLETED"
        ),
        None,
    )

    latest_running = next(
        (
            row
            for row in rows
            if str(
                row["status"]
                or ""
            ).upper()
            == "RUNNING"
        ),
        None,
    )

    max_age = timedelta(
        minutes=(
            DEFAULT_RESEARCH_SUCCESS_MAX_AGE_MINUTES
        )
    )

    if (
        clock.state
        == "ACTIVE_SAMPLE_WINDOW"
    ):
        if (
            latest_running
            is not None
        ):
            started = (
                _parse_iso_datetime(
                    latest_running[
                        "started_at"
                    ]
                )
            )

            if (
                started is not None
                and observed - started
                <= max_age
            ):
                age_minutes = (
                    (
                        observed
                        - started
                    ).total_seconds()
                    / 60
                )

                return SupervisorCheck(
                    "research-progress",
                    "PASS",
                    (
                        "A scheduled research "
                        "iteration is currently "
                        "running and started "
                        f"{age_minutes:.1f} "
                        "minutes ago."
                    ),
                )

        if latest_success is None:
            return SupervisorCheck(
                "research-progress",
                "FAIL",
                (
                    "No successful daemon "
                    "iteration exists during "
                    "an active market sample "
                    "window."
                ),
            )

        completed = (
            _parse_iso_datetime(
                latest_success[
                    "completed_at"
                ]
            )
        )

        if completed is None:
            return SupervisorCheck(
                "research-progress",
                "FAIL",
                (
                    "Latest successful daemon "
                    "iteration has no valid "
                    "completed_at."
                ),
            )

        age = (
            observed
            - completed
        )

        if age > max_age:
            return SupervisorCheck(
                "research-progress",
                "FAIL",
                (
                    "Last successful research "
                    "iteration is stale during "
                    "the active sample window: "
                    "age="
                    f"{age.total_seconds() / 60:.1f} "
                    "minutes; maximum="
                    f"{DEFAULT_RESEARCH_SUCCESS_MAX_AGE_MINUTES:.1f}."
                ),
            )

        return SupervisorCheck(
            "research-progress",
            "PASS",
            (
                "Research production current; "
                "last successful iteration "
                "age="
                f"{age.total_seconds() / 60:.1f} "
                "minutes."
            ),
        )

    if (
        clock.state
        == "AFTER_SAMPLE_WINDOW"
    ):
        if latest_success is None:
            return SupervisorCheck(
                "research-progress",
                "FAIL",
                (
                    "No successful daemon "
                    "iteration exists after "
                    "today's market sample "
                    "window."
                ),
            )

        scheduled = (
            _parse_iso_datetime(
                latest_success[
                    "scheduled_for"
                ]
            )
        )

        session_date = (
            None
            if clock.session is None
            else (
                clock.session.session_date
            )
        )

        if (
            scheduled is None
            or session_date is None
            or (
                scheduled.astimezone(
                    __import__(
                        "zoneinfo"
                    ).ZoneInfo(
                        "America/New_York"
                    )
                ).date().isoformat()
                != session_date
            )
        ):
            return SupervisorCheck(
                "research-progress",
                "FAIL",
                (
                    "No successful daemon "
                    "iteration is recorded "
                    "for today's completed "
                    "market sample window."
                ),
            )

    if latest_success is None:
        return SupervisorCheck(
            "research-progress",
            "FAIL",
            (
                "No successful research "
                "iteration exists; market "
                f"state={clock.state}."
            ),
        )

    return SupervisorCheck(
        "research-progress",
        "PASS",
        (
            "Latest daemon iteration is "
            "healthy; market state="
            f"{clock.state}."
        ),
    )


def _atomic_json_write(
    path: Path,
    payload: dict[str, object],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    encoded = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(
            path.parent
        ),
        text=True,
    )

    temp = Path(
        temp_name
    )

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(
                encoded
            )
            handle.flush()
            os.fsync(
                handle.fileno()
            )

        os.replace(
            temp,
            path,
        )

    finally:
        if temp.exists():
            temp.unlink()


def _read_json(
    path: Path,
) -> dict[str, object]:
    if not path.is_file():
        return {}

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return {}

    return (
        data
        if isinstance(
            data,
            dict,
        )
        else {}
    )


def _post_alert(
    url: str,
    payload: dict[str, object],
    *,
    timeout_seconds: float = (
        DEFAULT_ALERT_TIMEOUT_SECONDS
    ),
) -> None:
    request = Request(
        url,
        data=json.dumps(
            payload,
            sort_keys=True,
        ).encode(
            "utf-8"
        ),
        headers={
            "Content-Type": (
                "application/json"
            ),
            "User-Agent": (
                "Christiania-RC0-"
                "Supervisor/1"
            ),
        },
        method="POST",
    )

    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            if (
                int(response.status)
                < 200
                or int(response.status)
                >= 300
            ):
                raise RuntimeError(
                    "Alert webhook returned "
                    "HTTP "
                    f"{int(response.status)}."
                )

    except URLError as exc:
        raise ConnectionError(
            "Alert webhook unreachable: "
            f"{exc}"
        ) from exc


def _ping_heartbeat(
    url: str,
    *,
    timeout_seconds: float = (
        DEFAULT_ALERT_TIMEOUT_SECONDS
    ),
) -> None:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Christiania-RC0-"
                "Heartbeat/1"
            ),
        },
        method="GET",
    )

    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            if (
                int(response.status)
                < 200
                or int(response.status)
                >= 300
            ):
                raise RuntimeError(
                    "Heartbeat endpoint "
                    "returned HTTP "
                    f"{int(response.status)}."
                )

    except URLError as exc:
        raise ConnectionError(
            "Heartbeat endpoint "
            f"unreachable: {exc}"
        ) from exc


def collect_snapshot(
    *,
    now: datetime | None = None,
    service_state: Callable[
        [str],
        str,
    ] = _systemd_state,
    timer_state: Callable[
        [str],
        str,
    ] = _timer_enabled,
    service_properties: Callable[
        [str],
        dict[str, str],
    ] = _systemd_properties,
    disk_usage: Callable[
        [str | os.PathLike[str]],
        object,
    ] = shutil.disk_usage,
) -> SupervisorSnapshot:
    observed = (
        _utc_now()
        if now is None
        else now.astimezone(
            UTC
        )
    )

    checks: list[
        SupervisorCheck
    ] = []

    service_memory: dict[
        str,
        dict[str, int | None],
    ] = {}

    deck = load_command_deck(
        include_provider_health=True,
        deep_integrity=False,
    )

    db = deck.get(
        "database",
        {},
    )
    schema_version = db.get(
        "schema_version"
    )

    db_ok = (
        deck.get("ready")
        is True
        and schema_version
        == EXPECTED_SCHEMA_VERSION
        and str(
            db.get(
                "journal_mode",
                "",
            )
        ).lower()
        == "wal"
    )

    checks.append(
        SupervisorCheck(
            "database-fast-health",
            (
                "PASS"
                if db_ok
                else "FAIL"
            ),
            (
                (
                    f"Schema v{schema_version}; "
                    "WAL; interactive read "
                    "model ready."
                )
                if db_ok
                else (
                    "Fast database/read-model "
                    "check failed: "
                    f"{deck.get('reason')}"
                )
            ),
        )
    )

    daemon = deck.get(
        "daemon_health",
        {},
    )

    daemon_state = str(
        daemon.get(
            "state"
        )
        or "UNKNOWN"
    )

    daemon_ok = (
        daemon_state
        == "HEALTHY"
    )

    checks.append(
        SupervisorCheck(
            "daemon-heartbeat",
            (
                "PASS"
                if daemon_ok
                else "FAIL"
            ),
            (
                (
                    "Daemon heartbeat healthy; "
                    "age="
                    f"{daemon.get('heartbeat_age_seconds')}s."
                )
                if daemon_ok
                else (
                    "Daemon state: "
                    f"{daemon_state}."
                )
            ),
        )
    )

    theta = deck.get(
        "theta_health",
        {},
    )

    theta_state = str(
        theta.get(
            "state"
        )
        or "UNKNOWN"
    )

    theta_ok = (
        theta.get("ready")
        is True
    )

    checks.append(
        SupervisorCheck(
            "theta-readiness",
            (
                "PASS"
                if theta_ok
                else "FAIL"
            ),
            (
                (
                    "Theta ready; latency="
                    f"{theta.get('latency_ms')}ms."
                )
                if theta_ok
                else (
                    "Theta state: "
                    f"{theta_state}."
                )
            ),
        )
    )

    external_required = (
        _setting_bool(
            (
                "CHRISTIANIA_REQUIRE_"
                "EXTERNAL_OBSERVABILITY"
            ),
            False,
        )
    )

    alert_url = get_runtime_setting(
        "CHRISTIANIA_ALERT_WEBHOOK_URL"
    )
    heartbeat_url = (
        get_runtime_setting(
            "CHRISTIANIA_HEARTBEAT_URL"
        )
    )

    for (
        name,
        configured,
        detail,
    ) in (
        (
            "external-alert-config",
            bool(
                alert_url
            ),
            (
                "State-transition alert "
                "webhook configured."
            ),
        ),
        (
            "external-heartbeat-config",
            bool(
                heartbeat_url
            ),
            (
                "External dead-man "
                "heartbeat configured."
            ),
        ),
    ):
        if configured:
            checks.append(
                SupervisorCheck(
                    name,
                    "PASS",
                    detail,
                )
            )

        elif external_required:
            checks.append(
                SupervisorCheck(
                    name,
                    "FAIL",
                    (
                        "External observability "
                        "is required but not "
                        "configured."
                    ),
                )
            )

        else:
            checks.append(
                SupervisorCheck(
                    name,
                    "INFO",
                    (
                        "External observability "
                        "endpoint not configured "
                        "yet."
                    ),
                    blocking=False,
                )
            )

    properties_by_unit: dict[
        str,
        dict[str, str],
    ] = {}

    for unit in (
        SERVICE_RESOURCE_POLICIES
    ):
        try:
            properties = (
                service_properties(
                    unit
                )
            )
        except Exception as exc:
            checks.append(
                _resource_policy_failure(
                    unit,
                    exc,
                )
            )
            continue

        properties_by_unit[
            unit
        ] = properties

        checks.append(
            _resource_policy_check(
                unit,
                properties,
            )
        )

    for unit in CORE_SERVICES:
        state = service_state(
            unit
        )

        checks.append(
            SupervisorCheck(
                f"systemd:{unit}",
                (
                    "PASS"
                    if state == "active"
                    else "FAIL"
                ),
                (
                    f"{unit} is "
                    f"{state}."
                ),
            )
        )

        policy = (
            service_resource_policy(
                unit
            )
        )

        properties = (
            properties_by_unit.get(
                unit
            )
        )

        if properties is None:
            memory_check, telemetry = (
                _memory_failure(
                    unit,
                    policy,
                    RuntimeError(
                        (
                            "effective systemd "
                            "properties unavailable"
                        )
                    ),
                )
            )
        else:
            try:
                (
                    memory_check,
                    telemetry,
                ) = _memory_check(
                    unit,
                    properties,
                )
            except Exception as exc:
                (
                    memory_check,
                    telemetry,
                ) = _memory_failure(
                    unit,
                    policy,
                    exc,
                )

        checks.append(
            memory_check
        )
        service_memory[
            unit
        ] = telemetry

    for unit in EXPECTED_ENABLED_TIMERS:
        state = timer_state(
            unit
        )

        checks.append(
            SupervisorCheck(
                f"timer:{unit}",
                (
                    "PASS"
                    if state == "enabled"
                    else "FAIL"
                ),
                (
                    f"{unit} is {state}; "
                    "expected enabled."
                ),
            )
        )

    for unit in (
        INTENTIONALLY_DISABLED_TIMERS
    ):
        state = timer_state(
            unit
        )

        checks.append(
            SupervisorCheck(
                f"timer:{unit}",
                (
                    "PASS"
                    if state == "disabled"
                    else "FAIL"
                ),
                (
                    f"{unit} is {state}; "
                    "expected disabled by "
                    "current control-plane "
                    "policy."
                ),
            )
        )

    backup_inventory = (
        inventory_backups_fast().as_dict()
    )

    backup_entries = (
        backup_inventory.get(
            "entries",
            [],
        )
    )

    latest_backup_age = min(
        (
            float(
                entry[
                    "age_hours"
                ]
            )
            for entry in (
                backup_entries
            )
            if entry.get(
                "age_hours"
            )
            is not None
        ),
        default=None,
    )

    max_backup_age = (
        _setting_float(
            (
                "CHRISTIANIA_RC0_BACKUP_"
                "METADATA_MAX_AGE_HOURS"
            ),
            (
                DEFAULT_BACKUP_METADATA_MAX_AGE_HOURS
            ),
        )
    )

    backup_ok = (
        int(
            backup_inventory.get(
                "total_files",
                0,
            )
            or 0
        )
        > 0
        and latest_backup_age
        is not None
        and latest_backup_age
        <= max_backup_age
    )

    checks.append(
        SupervisorCheck(
            (
                "backup-freshness-"
                "metadata"
            ),
            (
                "PASS"
                if backup_ok
                else "FAIL"
            ),
            (
                (
                    "Latest backup file "
                    "metadata age "
                    f"{latest_backup_age:.2f}h; "
                    "deep validity is checked "
                    "separately."
                )
                if latest_backup_age
                is not None
                else (
                    "No backup file found."
                )
            ),
        )
    )

    db_path = resolve_db_path()

    checks.append(
        _research_progress_check(
            db_path,
            observed,
        )
    )

    usage = disk_usage(
        db_path.parent
    )

    total = int(
        getattr(
            usage,
            "total",
        )
    )
    free = int(
        getattr(
            usage,
            "free",
        )
    )

    free_fraction = (
        0.0
        if total <= 0
        else free / total
    )

    min_free_bytes = (
        _setting_int(
            "CHRISTIANIA_RC0_MIN_FREE_BYTES",
            DEFAULT_MIN_FREE_BYTES,
        )
    )

    min_free_fraction = (
        _setting_float(
            (
                "CHRISTIANIA_RC0_"
                "MIN_FREE_FRACTION"
            ),
            DEFAULT_MIN_FREE_FRACTION,
        )
    )

    disk_ok = (
        free
        >= min_free_bytes
        and free_fraction
        >= min_free_fraction
    )

    checks.append(
        SupervisorCheck(
            "disk-headroom",
            (
                "PASS"
                if disk_ok
                else "FAIL"
            ),
            (
                f"Free={free} bytes "
                f"({free_fraction:.1%}); "
                "minimum="
                f"{min_free_bytes} bytes "
                "and "
                f"{min_free_fraction:.1%}."
            ),
        )
    )

    blockers = [
        check
        for check in checks
        if (
            check.blocking
            and check.state
            == "FAIL"
        )
    ]

    state = (
        "HEALTHY"
        if not blockers
        else "UNHEALTHY"
    )

    return SupervisorSnapshot(
        observed_at=(
            observed.isoformat().replace(
                "+00:00",
                "Z",
            )
        ),
        state=state,
        checks=tuple(
            checks
        ),
        schema_version=(
            None
            if schema_version
            is None
            else int(
                schema_version
            )
        ),
        daemon_state=daemon_state,
        theta_state=theta_state,
        backup_file_count=int(
            backup_inventory.get(
                "total_files",
                0,
            )
            or 0
        ),
        latest_backup_metadata_age_hours=(
            latest_backup_age
        ),
        disk_free_bytes=free,
        disk_free_fraction=(
            free_fraction
        ),
        service_memory=(
            service_memory
        ),
    )


def persist_and_alert(
    snapshot: SupervisorSnapshot,
    *,
    send_alert: bool = True,
    audit_dir: Path | None = None,
) -> dict[str, object]:
    directory = (
        resolve_audit_dir()
        if audit_dir is None
        else audit_dir
    )

    status_path = (
        directory
        / DEFAULT_STATUS_FILENAME
    )
    state_path = (
        directory
        / DEFAULT_STATE_FILENAME
    )

    current = snapshot.as_dict()
    previous = _read_json(
        state_path
    )

    previous_state = str(
        previous.get(
            "state"
        )
        or "UNKNOWN"
    )

    transition = (
        previous_state
        != snapshot.state
    )

    _atomic_json_write(
        status_path,
        current,
    )

    alert_url = get_runtime_setting(
        "CHRISTIANIA_ALERT_WEBHOOK_URL"
    )

    alert_state = (
        "NOT_CONFIGURED"
    )
    alert_error = None

    retry_failed_alert = (
        snapshot.state
        == "UNHEALTHY"
        and str(
            previous.get(
                "alert_state"
            )
            or ""
        )
        == "FAILED"
    )

    should_alert = (
        transition
        or retry_failed_alert
    )

    if (
        send_alert
        and alert_url
        and should_alert
    ):
        payload = {
            "application": (
                "Christiania"
            ),
            "environment": (
                "RC0"
            ),
            "event": (
                "SUPERVISOR_STATE_"
                "TRANSITION"
            ),
            "previous_state": (
                previous_state
            ),
            "state": snapshot.state,
            "observed_at": (
                snapshot.observed_at
            ),
            "failed_checks": [
                check.as_dict()
                for check
                in snapshot.checks
                if check.state
                == "FAIL"
            ],
        }

        try:
            _post_alert(
                alert_url,
                payload,
                timeout_seconds=(
                    _setting_float(
                        (
                            "CHRISTIANIA_ALERT_"
                            "TIMEOUT_SECONDS"
                        ),
                        (
                            DEFAULT_ALERT_TIMEOUT_SECONDS
                        ),
                    )
                ),
            )
        except Exception as exc:
            alert_state = (
                "FAILED"
            )
            alert_error = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )
        else:
            alert_state = (
                "SENT"
            )

    elif (
        alert_url
        and str(
            previous.get(
                "alert_state"
            )
            or ""
        )
        == "SENT"
    ):
        alert_state = "SENT"

    heartbeat_url = (
        get_runtime_setting(
            "CHRISTIANIA_HEARTBEAT_URL"
        )
    )

    heartbeat_failure_url = (
        get_runtime_setting(
            (
                "CHRISTIANIA_HEARTBEAT_"
                "FAILURE_URL"
            )
        )
    )

    heartbeat_state = (
        "NOT_CONFIGURED"
    )
    heartbeat_error = None

    heartbeat_target = (
        heartbeat_url
        if snapshot.healthy
        else heartbeat_failure_url
    )

    if heartbeat_target:
        try:
            _ping_heartbeat(
                heartbeat_target,
                timeout_seconds=(
                    _setting_float(
                        (
                            "CHRISTIANIA_ALERT_"
                            "TIMEOUT_SECONDS"
                        ),
                        (
                            DEFAULT_ALERT_TIMEOUT_SECONDS
                        ),
                    )
                ),
            )
        except Exception as exc:
            heartbeat_state = (
                "FAILED"
            )
            heartbeat_error = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )
        else:
            heartbeat_state = (
                "SENT"
            )

    elif heartbeat_url:
        heartbeat_state = (
            "SUPPRESSED_UNHEALTHY"
        )

    state_payload = {
        "state": snapshot.state,
        "observed_at": (
            snapshot.observed_at
        ),
        "previous_state": (
            previous_state
        ),
        "transition": transition,
        "alert_state": (
            alert_state
        ),
        "alert_error": (
            alert_error
        ),
        "heartbeat_state": (
            heartbeat_state
        ),
        "heartbeat_error": (
            heartbeat_error
        ),
    }

    _atomic_json_write(
        state_path,
        state_payload,
    )

    return state_payload