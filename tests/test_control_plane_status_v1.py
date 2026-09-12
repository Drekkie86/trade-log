from __future__ import annotations

import json
from pathlib import Path

from src.operations.control_plane_status import (
    CORE_SERVICES,
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


def _write_supervisor(
    audit_dir: Path,
    *,
    state: str = "HEALTHY",
    research_state: str = "PASS",
    research_detail: str = (
        "Research production current."
    ),
) -> None:
    audit_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "state": state,
        "observed_at": (
            "2026-09-12T08:00:00Z"
        ),
        "checks": [
            {
                "name": (
                    "research-progress"
                ),
                "state": research_state,
                "detail": research_detail,
            }
        ],
    }

    (
        audit_dir
        / "rc0_supervisor_status.json"
    ).write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _active(
    unit: str,
) -> str:
    assert unit in CORE_SERVICES
    return "active"


def test_control_plane_status_ready_from_existing_evidence(
    tmp_path: Path,
):
    app_dir = tmp_path / "app"
    audit_dir = tmp_path / "audit"
    systemd_root = tmp_path / "systemd"

    app_dir.mkdir()
    (
        app_dir
        / "DEPLOYED_COMMIT"
    ).write_text(
        COMMIT + "\n",
        encoding="utf-8",
    )

    _write_supervisor(
        audit_dir
    )

    write_resource_dropins(
        systemd_root
    )

    status = collect_control_plane_status(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
        service_state=_active,
    )

    assert status.ready is True
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
        status.supervisor_state
        == "HEALTHY"
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
        == 14
    )
    assert (
        status.resource_policy_total
        == 14
    )


def test_control_plane_status_fails_missing_release_identity(
    tmp_path: Path,
):
    app_dir = tmp_path / "app"
    audit_dir = tmp_path / "audit"
    systemd_root = tmp_path / "systemd"

    app_dir.mkdir()

    _write_supervisor(
        audit_dir
    )

    write_resource_dropins(
        systemd_root
    )

    status = collect_control_plane_status(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
        service_state=_active,
    )

    assert status.ready is False
    assert (
        status.release_identity_state
        == "FAIL"
    )


def test_control_plane_status_fails_bad_core_service(
    tmp_path: Path,
):
    app_dir = tmp_path / "app"
    audit_dir = tmp_path / "audit"
    systemd_root = tmp_path / "systemd"

    app_dir.mkdir()
    (
        app_dir
        / "DEPLOYED_COMMIT"
    ).write_text(
        COMMIT,
        encoding="utf-8",
    )

    _write_supervisor(
        audit_dir
    )

    write_resource_dropins(
        systemd_root
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

    status = collect_control_plane_status(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
        service_state=service_state,
    )

    assert status.ready is False
    assert (
        status.core_services_state
        == "FAIL"
    )


def test_control_plane_status_surfaces_research_failure(
    tmp_path: Path,
):
    app_dir = tmp_path / "app"
    audit_dir = tmp_path / "audit"
    systemd_root = tmp_path / "systemd"

    app_dir.mkdir()
    (
        app_dir
        / "DEPLOYED_COMMIT"
    ).write_text(
        COMMIT,
        encoding="utf-8",
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

    write_resource_dropins(
        systemd_root
    )

    status = collect_control_plane_status(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
        service_state=_active,
    )

    assert status.ready is False
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
    app_dir = tmp_path / "app"
    audit_dir = tmp_path / "audit"
    systemd_root = tmp_path / "systemd"

    app_dir.mkdir()
    (
        app_dir
        / "DEPLOYED_COMMIT"
    ).write_text(
        COMMIT,
        encoding="utf-8",
    )

    _write_supervisor(
        audit_dir
    )

    paths = write_resource_dropins(
        systemd_root
    )

    paths[0].write_text(
        "[Service]\n"
        "MemoryMax=infinity\n",
        encoding="utf-8",
    )

    status = collect_control_plane_status(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
        service_state=_active,
    )

    assert status.ready is False
    assert (
        status.resource_policy_state
        == "FAIL"
    )
    assert (
        status.resource_policy_passed
        == 13
    )
    assert (
        status.resource_policy_total
        == 14
    )


def test_control_plane_status_does_not_run_deep_health(
    tmp_path: Path,
    monkeypatch,
):
    app_dir = tmp_path / "app"
    audit_dir = tmp_path / "audit"
    systemd_root = tmp_path / "systemd"

    app_dir.mkdir()
    (
        app_dir
        / "DEPLOYED_COMMIT"
    ).write_text(
        COMMIT,
        encoding="utf-8",
    )

    _write_supervisor(
        audit_dir
    )

    write_resource_dropins(
        systemd_root
    )

    def forbidden_run(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "Status must not invoke arbitrary "
            "deep operational checks."
        )

    monkeypatch.setattr(
        "src.operations.control_plane_status."
        "subprocess.run",
        forbidden_run,
    )

    status = collect_control_plane_status(
        app_dir=app_dir,
        audit_dir=audit_dir,
        systemd_root=systemd_root,
        service_state=_active,
    )

    assert status.ready is True