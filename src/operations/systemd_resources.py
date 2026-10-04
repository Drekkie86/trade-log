from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.operations.service_resources import (
    SERVICE_RESOURCE_POLICIES,
    ServiceResourcePolicy,
    managed_service_units,
    systemd_dropin_text,
)


DROPIN_DIRNAME = "10-christiania-resources.conf"


@dataclass(frozen=True)
class ResourcePolicyCheck:
    unit: str
    path: Path
    state: str
    detail: str

    @property
    def passed(self) -> bool:
        return self.state == "PASS"


def dropin_path(
    systemd_root: Path,
    unit: str,
) -> Path:
    return (
        systemd_root
        / f"{unit}.d"
        / DROPIN_DIRNAME
    )


def expected_dropin_text(
    unit: str,
) -> str:
    try:
        policy = SERVICE_RESOURCE_POLICIES[unit]
    except KeyError as exc:
        raise KeyError(
            f"No Christiania resource policy is defined for {unit!r}."
        ) from exc

    return systemd_dropin_text(policy)


def write_resource_dropins(
    systemd_root: Path,
) -> tuple[Path, ...]:
    written: list[Path] = []

    for unit in managed_service_units():
        path = dropin_path(
            systemd_root,
            unit,
        )
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        # These files live under /etc/systemd/system in production and are
        # inspected by christiania-status while running as the unprivileged
        # service account. Never inherit a restrictive deployment umask.
        path.parent.chmod(0o755)
        path.write_text(
            expected_dropin_text(unit),
            encoding="utf-8",
            newline="\n",
        )
        path.chmod(0o644)
        written.append(path)

    return tuple(written)


def check_resource_dropins(
    systemd_root: Path,
) -> tuple[ResourcePolicyCheck, ...]:
    checks: list[ResourcePolicyCheck] = []

    for unit in managed_service_units():
        path = dropin_path(
            systemd_root,
            unit,
        )

        try:
            is_file = path.is_file()
        except OSError as exc:
            checks.append(
                ResourcePolicyCheck(
                    unit=unit,
                    path=path,
                    state="FAIL",
                    detail=(
                        "Cannot inspect installed Christiania "
                        "resource-policy drop-in: "
                        f"{exc.__class__.__name__}."
                    ),
                )
            )
            continue

        if not is_file:
            checks.append(
                ResourcePolicyCheck(
                    unit=unit,
                    path=path,
                    state="FAIL",
                    detail=(
                        "Expected Christiania resource-policy "
                        "drop-in is missing."
                    ),
                )
            )
            continue

        try:
            actual = path.read_text(
                encoding="utf-8",
            )
        except OSError as exc:
            checks.append(
                ResourcePolicyCheck(
                    unit=unit,
                    path=path,
                    state="FAIL",
                    detail=(
                        "Cannot read installed Christiania "
                        "resource-policy drop-in: "
                        f"{exc.__class__.__name__}."
                    ),
                )
            )
            continue

        expected = expected_dropin_text(unit)

        if actual != expected:
            checks.append(
                ResourcePolicyCheck(
                    unit=unit,
                    path=path,
                    state="FAIL",
                    detail=(
                        "Installed resource-policy drop-in "
                        "does not match the canonical policy."
                    ),
                )
            )
            continue

        checks.append(
            ResourcePolicyCheck(
                unit=unit,
                path=path,
                state="PASS",
                detail=(
                    "Installed resource-policy drop-in "
                    "matches the canonical policy."
                ),
            )
        )

    return tuple(checks)


def policy_for_unit(
    unit: str,
) -> ServiceResourcePolicy:
    try:
        return SERVICE_RESOURCE_POLICIES[unit]
    except KeyError as exc:
        raise KeyError(
            f"No Christiania resource policy is defined for {unit!r}."
        ) from exc