from __future__ import annotations

from datetime import (
    UTC,
    datetime,
    timedelta,
)
import json
from pathlib import Path

import pytest

from src.operations.control_plane_status import (
    CORE_SERVICES,
    DEFAULT_SUPERVISOR_MAX_AGE_SECONDS,
    PUBLIC_EDGE_SERVICE,
    PUBLIC_EDGE_SERVICES,
    collect_control_plane_status,
)
from src.operations.systemd_resources import (
    write_resource_dropins,
)


COMMIT = (
    "0123456789abcdef"
    "0123456789abcdef"
    "01234567"
)

NOW = datetime(
    2026,
    9,
    12,
    8,
    5,
    tzinfo=UTC,
)

FRESH_OBSERVED_AT = (
    "2026-09-12T08:00:00Z"
)


def _write_supervisor(
    audit_dir: Path,
    *,
    state: str = "HEALTHY",
    research_state: str = "PASS",
    research_detail: str = (
        "Research production current."
    ),
    observed_at: str = (
        FRESH_OBSERVED_AT
    ),
) -> None:
    audit_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "state": state,
        "observed_at": observed_at,
        "checks": [
            {
                "name": (
                    "research-progress"
                ),
                "state": (
                    research_state
                ),
                "detail": (
                    research_detail
                ),
            }
        ],
    }

    (
        audit_dir
        / "rc0_supervisor_status.json"
    ).write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )


def _active(
    unit: str,
) -> str:
    if (
        unit
        in CORE_SERVICES
    ):
        return "active"

    if (
        unit
        == PUBLIC_EDGE_SERVICE
    ):
        return "inactive"

    raise AssertionError(
        f"Unexpected unit: {unit}"
    )


def _prepare(
    tmp_path: Path,
) -> tuple[
    Path,
    Path,
    Path,
]:
    app_dir = (
        tmp_path
        / "app"
    )
    audit_dir = (
        tmp_path
        / "audit"
    )
    systemd_root = (
        tmp_path
        / "systemd"
    )

    app_dir.mkdir()

    (
        app_dir
        / "DEPLOYED_COMMIT"
    ).write_text(
        COMMIT + "\n",
        encoding="utf-8",
    )

    write_resource_dropins(
        systemd_root
    )

    return (
        app_dir,
        audit_dir,
        systemd_root,
    )


def _collect(
    *,
    app_dir: Path,
    audit_dir: Path,
    systemd_root: Path,
    service_state=_active,
    service_enabled=lambda unit: "disabled",
):
    return (
        collect_control_plane_status(
            app_dir=app_dir,
            audit_dir=audit_dir,
            systemd_root=systemd_root,
            service_state=(
                service_state
            ),
            service_enabled=(
                service_enabled
            ),
            now=NOW,
        )
    )


def test_control_plane_status_ready_from_existing_evidence(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    _write_supervisor(
        audit_dir
    )

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
    )

    assert (
        status.ready
        is True
    )

    assert (
        status.deployed_commit
        == COMMIT
    )

    assert (
        status.release_identity_state
        == "PASS"
    )

    assert (
        status.core_services_state
        == "PASS"
    )

    assert (
        status.public_edge_expected
        is False
    )

    assert (
        status.public_edge_state
        == "NOT_CONFIGURED"
    )

    assert (
        status.supervisor_state
        == "HEALTHY"
    )

    assert (
        status.supervisor_freshness_state
        == "PASS"
    )

    assert (
        status.supervisor_age_seconds
        == 300.0
    )

    assert (
        status.research_progress_state
        == "PASS"
    )

    assert (
        status.resource_policy_state
        == "PASS"
    )

    assert (
        status.resource_policy_passed
        == 15
    )

    assert (
        status.resource_policy_total
        == 15
    )


def test_control_plane_status_fails_stale_supervisor_evidence(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    stale = (
        NOW
        - timedelta(
            seconds=(
                DEFAULT_SUPERVISOR_MAX_AGE_SECONDS
                + 1
            )
        )
    )

    _write_supervisor(
        audit_dir,
        observed_at=(
            stale.isoformat().replace(
                "+00:00",
                "Z",
            )
        ),
    )

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
    )

    assert (
        status.supervisor_state
        == "HEALTHY"
    )

    assert (
        status.supervisor_freshness_state
        == "FAIL"
    )

    assert (
        status.ready
        is False
    )


def test_control_plane_status_accepts_boundary_freshness(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    boundary = (
        NOW
        - timedelta(
            seconds=(
                DEFAULT_SUPERVISOR_MAX_AGE_SECONDS
            )
        )
    )

    _write_supervisor(
        audit_dir,
        observed_at=(
            boundary.isoformat().replace(
                "+00:00",
                "Z",
            )
        ),
    )

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
    )

    assert (
        status.supervisor_freshness_state
        == "PASS"
    )

    assert (
        status.ready
        is True
    )


@pytest.mark.parametrize(
    "observed_at",
    [
        "",
        "not-a-timestamp",
        "2026-09-12T08:00:00",
    ],
)
def test_control_plane_status_fails_invalid_supervisor_timestamp(
    tmp_path: Path,
    observed_at: str,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    _write_supervisor(
        audit_dir,
        observed_at=(
            observed_at
        ),
    )

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
    )

    assert (
        status.supervisor_freshness_state
        == "FAIL"
    )

    assert (
        status.supervisor_age_seconds
        is None
    )

    assert (
        status.ready
        is False
    )


def test_control_plane_status_fails_implausibly_future_supervisor_timestamp(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    future = (
        NOW
        + timedelta(
            minutes=3
        )
    )

    _write_supervisor(
        audit_dir,
        observed_at=(
            future.isoformat().replace(
                "+00:00",
                "Z",
            )
        ),
    )

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
    )

    assert (
        status.supervisor_freshness_state
        == "FAIL"
    )

    assert (
        status.ready
        is False
    )


def test_control_plane_status_fails_missing_release_identity(
    tmp_path: Path,
):
    app_dir = (
        tmp_path
        / "app"
    )
    audit_dir = (
        tmp_path
        / "audit"
    )
    systemd_root = (
        tmp_path
        / "systemd"
    )

    app_dir.mkdir()

    _write_supervisor(
        audit_dir
    )

    write_resource_dropins(
        systemd_root
    )

    status = (
        collect_control_plane_status(
            app_dir=app_dir,
            audit_dir=audit_dir,
            systemd_root=(
                systemd_root
            ),
            service_state=(
                _active
            ),
            service_enabled=(
                lambda unit: "disabled"
            ),
            now=NOW,
        )
    )

    assert (
        status.ready
        is False
    )

    assert (
        status.release_identity_state
        == "FAIL"
    )


def test_control_plane_status_fails_bad_core_service(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    _write_supervisor(
        audit_dir
    )

    def service_state(
        unit: str,
    ) -> str:
        if (
            unit
            == "christiania-daemon.service"
        ):
            return "failed"

        return "active"

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
        service_state=(
            service_state
        ),
    )

    assert (
        status.ready
        is False
    )

    assert (
        status.core_services_state
        == "FAIL"
    )


def test_control_plane_status_surfaces_research_failure(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    _write_supervisor(
        audit_dir,
        state="UNHEALTHY",
        research_state="FAIL",
        research_detail=(
            "Last successful research "
            "iteration is stale."
        ),
    )

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
    )

    assert (
        status.ready
        is False
    )

    assert (
        status.supervisor_state
        == "UNHEALTHY"
    )

    assert (
        status.research_progress_state
        == "FAIL"
    )

    assert (
        "stale"
        in (
            status.research_progress_detail
            or ""
        )
    )


def test_control_plane_status_detects_resource_policy_drift(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    _write_supervisor(
        audit_dir
    )

    paths = (
        write_resource_dropins(
            systemd_root
        )
    )

    paths[0].write_text(
        "[Service]\n"
        "MemoryMax=infinity\n",
        encoding="utf-8",
    )

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
    )

    assert (
        status.ready
        is False
    )

    assert (
        status.resource_policy_state
        == "FAIL"
    )

    assert (
        status.resource_policy_passed
        == 14
    )

    assert (
        status.resource_policy_total
        == 15
    )


def test_control_plane_status_does_not_run_deep_health(
    tmp_path: Path,
    monkeypatch,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    _write_supervisor(
        audit_dir
    )

    def forbidden_run(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "Status must not invoke "
            "arbitrary deep operational "
            "checks."
        )

    monkeypatch.setattr(
        (
            "src.operations."
            "control_plane_status."
            "subprocess.run"
        ),
        forbidden_run,
    )

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
    )

    assert (
        status.ready
        is True
    )


def test_control_plane_status_rejects_negative_freshness_budget(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    _write_supervisor(
        audit_dir
    )

    with pytest.raises(
        ValueError,
        match="cannot be negative",
    ):
        collect_control_plane_status(
            app_dir=app_dir,
            audit_dir=audit_dir,
            systemd_root=(
                systemd_root
            ),
            service_state=(
                _active
            ),
            now=NOW,
            supervisor_max_age_seconds=-1,
        )

def test_control_plane_status_requires_enabled_public_edge_to_be_active(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    _write_supervisor(
        audit_dir
    )

    def service_state(
        unit: str,
    ) -> str:
        if (
            unit
            == PUBLIC_EDGE_SERVICE
        ):
            return "inactive"

        assert (
            unit
            in (
                *CORE_SERVICES,
                *PUBLIC_EDGE_SERVICES,
            )
        )
        return "active"

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
        service_state=service_state,
        service_enabled=lambda unit: (
            "enabled"
            if unit
            == PUBLIC_EDGE_SERVICE
            else "disabled"
        ),
    )

    assert (
        status.public_edge_expected
        is True
    )
    assert (
        status.public_edge_state
        == "FAIL"
    )
    assert (
        status.ready
        is False
    )

    # A broken public edge is operationally NOT READY, but it
    # must not prevent a deployment that may repair the edge.
    assert (
        status.deployment_safe
        is True
    )


def test_control_plane_status_accepts_enabled_healthy_public_edge(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    _write_supervisor(
        audit_dir
    )

    def service_state(
        unit: str,
    ) -> str:
        assert (
            unit
            in (
                *CORE_SERVICES,
                *PUBLIC_EDGE_SERVICES,
            )
        )
        return "active"

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
        service_state=service_state,
        service_enabled=lambda unit: (
            "enabled"
            if unit
            == PUBLIC_EDGE_SERVICE
            else "disabled"
        ),
    )

    assert (
        status.public_edge_expected
        is True
    )
    assert (
        status.public_edge_state
        == "PASS"
    )
    assert (
        status.ready
        is True
    )


def test_public_edge_supervisor_failure_does_not_deadlock_deployment_repair(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    audit_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        audit_dir
        / "rc0_supervisor_status.json"
    ).write_text(
        json.dumps(
            {
                "state": "UNHEALTHY",
                "observed_at": (
                    FRESH_OBSERVED_AT
                ),
                "checks": [
                    {
                        "name": (
                            "research-progress"
                        ),
                        "state": "PASS",
                        "detail": (
                            "Research production current."
                        ),
                    },
                    {
                        "name": (
                            "public-edge-services"
                        ),
                        "state": "FAIL",
                        "detail": (
                            "OAuth proxy inactive."
                        ),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    def service_state(
        unit: str,
    ) -> str:
        if (
            unit
            == PUBLIC_EDGE_SERVICE
        ):
            return "inactive"

        return "active"

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
        service_state=service_state,
        service_enabled=lambda unit: (
            "enabled"
            if unit
            == PUBLIC_EDGE_SERVICE
            else "disabled"
        ),
    )

    assert status.ready is False
    assert (
        status.supervisor_state
        == "UNHEALTHY"
    )
    assert (
        status.deployment_supervisor_state
        == "PASS"
    )
    assert (
        status.deployment_safe
        is True
    )


def test_control_plane_status_monitors_active_public_edge_even_if_disabled(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    _write_supervisor(
        audit_dir
    )

    def service_state(
        unit: str,
    ) -> str:
        if (
            unit
            == "caddy.service"
        ):
            return "inactive"

        return "active"

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
        service_state=service_state,
        service_enabled=lambda unit: (
            "disabled"
        ),
    )

    assert status.public_edge_expected is True
    assert status.public_edge_state == "FAIL"
    assert status.ready is False

def test_backup_schema_mismatch_does_not_deadlock_schema_migration_deploy(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    audit_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        audit_dir
        / "rc0_supervisor_status.json"
    ).write_text(
        json.dumps(
            {
                "state": "UNHEALTHY",
                "observed_at": (
                    FRESH_OBSERVED_AT
                ),
                "checks": [
                    {
                        "name": "research-progress",
                        "state": "PASS",
                        "detail": (
                            "Research production current."
                        ),
                    },
                    {
                        "name": "backup-recovery-point",
                        "state": "FAIL",
                        "detail": (
                            "Recovery point due=True; "
                            "reason=LATEST_BACKUP_SCHEMA_MISMATCH; "
                            "age_hours=0.1."
                        ),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
    )

    # Full operational readiness stays strict until a current-schema normal
    # backup exists, but the deployment itself must not be rolled back after
    # its verified pre-migration rollback snapshot was committed.
    assert status.ready is False
    assert status.supervisor_state == "UNHEALTHY"
    assert status.deployment_supervisor_state == "PASS"
    assert status.deployment_safe is True


def test_other_backup_recovery_point_failures_still_block_deployment(
    tmp_path: Path,
):
    (
        app_dir,
        audit_dir,
        systemd_root,
    ) = _prepare(
        tmp_path
    )

    audit_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        audit_dir
        / "rc0_supervisor_status.json"
    ).write_text(
        json.dumps(
            {
                "state": "UNHEALTHY",
                "observed_at": (
                    FRESH_OBSERVED_AT
                ),
                "checks": [
                    {
                        "name": "research-progress",
                        "state": "PASS",
                        "detail": (
                            "Research production current."
                        ),
                    },
                    {
                        "name": "backup-recovery-point",
                        "state": "FAIL",
                        "detail": (
                            "Recovery point due=True; "
                            "reason=NO_RECOVERY_POINT."
                        ),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    status = _collect(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
    )

    assert status.ready is False
    assert status.deployment_supervisor_state == "FAIL"
    assert status.deployment_safe is False

