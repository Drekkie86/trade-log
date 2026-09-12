from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
from typing import Callable

from src.operations.systemd_resources import (
    check_resource_dropins,
)


DEFAULT_APP_DIR = Path(
    "/opt/christiania"
)
DEFAULT_AUDIT_DIR = Path(
    "/var/lib/christiania/audit"
)
DEFAULT_SYSTEMD_ROOT = Path(
    "/etc/systemd/system"
)
DEFAULT_SUPERVISOR_STATUS = (
    "rc0_supervisor_status.json"
)

DEFAULT_SUPERVISOR_MAX_AGE_SECONDS = (
    15 * 60
)
DEFAULT_SUPERVISOR_FUTURE_TOLERANCE_SECONDS = (
    2 * 60
)

CORE_SERVICES = (
    "christiania-theta.service",
    "christiania-daemon.service",
    "christiania-app.service",
)


@dataclass(frozen=True)
class ControlPlaneStatus:
    deployed_commit: str | None
    release_identity_state: str
    core_services: dict[str, str]
    core_services_state: str
    supervisor_state: str
    supervisor_observed_at: str | None
    supervisor_freshness_state: str
    supervisor_age_seconds: float | None
    research_progress_state: str
    research_progress_detail: str | None
    resource_policy_state: str
    resource_policy_passed: int
    resource_policy_total: int

    @property
    def ready(self) -> bool:
        return all(
            (
                self.release_identity_state
                == "PASS",
                self.core_services_state
                == "PASS",
                self.supervisor_state
                == "HEALTHY",
                self.supervisor_freshness_state
                == "PASS",
                self.research_progress_state
                in {
                    "PASS",
                    "INFO",
                },
                self.resource_policy_state
                == "PASS",
            )
        )

    def as_dict(
        self,
    ) -> dict[str, object]:
        return asdict(
            self
        ) | {
            "ready": self.ready,
        }


def _read_json(
    path: Path,
) -> dict[str, object]:
    if not path.is_file():
        return {}

    try:
        payload = json.loads(
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
        payload
        if isinstance(
            payload,
            dict,
        )
        else {}
    )


def _read_deployed_commit(
    app_dir: Path,
) -> tuple[
    str | None,
    str,
]:
    marker = (
        app_dir
        / "DEPLOYED_COMMIT"
    )

    if not marker.is_file():
        return None, "FAIL"

    try:
        value = marker.read_text(
            encoding="utf-8"
        ).strip().lower()
    except OSError:
        return None, "FAIL"

    if (
        len(value) != 40
        or any(
            character
            not in (
                "0123456789abcdef"
            )
            for character in value
        )
    ):
        return (
            value or None,
            "FAIL",
        )

    return value, "PASS"


def _systemctl_state(
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

    value = (
        completed.stdout
        or completed.stderr
        or "unknown"
    ).strip()

    return (
        value
        or "unknown"
    )


def _parse_observed_at(
    value: object,
) -> datetime | None:
    if value in (
        None,
        "",
    ):
        return None

    try:
        parsed = (
            datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if parsed.tzinfo is None:
        return None

    return parsed.astimezone(
        UTC
    )


def _supervisor_freshness(
    observed_at: object,
    *,
    now: datetime,
    max_age_seconds: float,
) -> tuple[
    str,
    float | None,
]:
    observed = _parse_observed_at(
        observed_at
    )

    if observed is None:
        return "FAIL", None

    age_seconds = (
        now
        - observed
    ).total_seconds()

    if (
        age_seconds
        < -DEFAULT_SUPERVISOR_FUTURE_TOLERANCE_SECONDS
    ):
        return (
            "FAIL",
            age_seconds,
        )

    if (
        age_seconds
        > max_age_seconds
    ):
        return (
            "FAIL",
            age_seconds,
        )

    return (
        "PASS",
        age_seconds,
    )


def _research_progress(
    supervisor: dict[str, object],
) -> tuple[
    str,
    str | None,
]:
    checks = supervisor.get(
        "checks"
    )

    if not isinstance(
        checks,
        list,
    ):
        return (
            "UNKNOWN",
            None,
        )

    for raw_check in checks:
        if not isinstance(
            raw_check,
            dict,
        ):
            continue

        if (
            raw_check.get(
                "name"
            )
            != "research-progress"
        ):
            continue

        state = str(
            raw_check.get(
                "state"
            )
            or "UNKNOWN"
        ).upper()

        detail_raw = (
            raw_check.get(
                "detail"
            )
        )

        detail = (
            None
            if detail_raw is None
            else str(
                detail_raw
            )
        )

        return (
            state,
            detail,
        )

    return (
        "UNKNOWN",
        None,
    )


def collect_control_plane_status(
    *,
    app_dir: Path = DEFAULT_APP_DIR,
    audit_dir: Path = DEFAULT_AUDIT_DIR,
    systemd_root: Path = (
        DEFAULT_SYSTEMD_ROOT
    ),
    service_state: Callable[
        [str],
        str,
    ] = _systemctl_state,
    now: datetime | None = None,
    supervisor_max_age_seconds: float = (
        DEFAULT_SUPERVISOR_MAX_AGE_SECONDS
    ),
) -> ControlPlaneStatus:
    observed_now = (
        datetime.now(
            UTC
        )
        if now is None
        else now.astimezone(
            UTC
        )
    )

    if (
        supervisor_max_age_seconds
        < 0
    ):
        raise ValueError(
            "supervisor_max_age_seconds "
            "cannot be negative."
        )

    (
        deployed_commit,
        identity_state,
    ) = _read_deployed_commit(
        app_dir
    )

    core_services = {
        unit: service_state(
            unit
        )
        for unit
        in CORE_SERVICES
    }

    core_state = (
        "PASS"
        if all(
            state == "active"
            for state
            in core_services.values()
        )
        else "FAIL"
    )

    supervisor = _read_json(
        audit_dir
        / DEFAULT_SUPERVISOR_STATUS
    )

    supervisor_state = str(
        supervisor.get(
            "state"
        )
        or "UNKNOWN"
    ).upper()

    observed_raw = (
        supervisor.get(
            "observed_at"
        )
    )

    observed_at = (
        None
        if observed_raw is None
        else str(
            observed_raw
        )
    )

    (
        supervisor_freshness_state,
        supervisor_age_seconds,
    ) = _supervisor_freshness(
        observed_raw,
        now=observed_now,
        max_age_seconds=(
            supervisor_max_age_seconds
        ),
    )

    (
        research_state,
        research_detail,
    ) = _research_progress(
        supervisor
    )

    resource_checks = (
        check_resource_dropins(
            systemd_root
        )
    )

    passed = sum(
        1
        for check
        in resource_checks
        if check.passed
    )

    total = len(
        resource_checks
    )

    resource_state = (
        "PASS"
        if (
            total > 0
            and passed == total
        )
        else "FAIL"
    )

    return ControlPlaneStatus(
        deployed_commit=(
            deployed_commit
        ),
        release_identity_state=(
            identity_state
        ),
        core_services=(
            core_services
        ),
        core_services_state=(
            core_state
        ),
        supervisor_state=(
            supervisor_state
        ),
        supervisor_observed_at=(
            observed_at
        ),
        supervisor_freshness_state=(
            supervisor_freshness_state
        ),
        supervisor_age_seconds=(
            supervisor_age_seconds
        ),
        research_progress_state=(
            research_state
        ),
        research_progress_detail=(
            research_detail
        ),
        resource_policy_state=(
            resource_state
        ),
        resource_policy_passed=(
            passed
        ),
        resource_policy_total=(
            total
        ),
    )