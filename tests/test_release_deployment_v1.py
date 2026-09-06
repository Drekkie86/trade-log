from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_burn_in_timer_is_persistent_and_15_minute_cadence():
    timer = (
        ROOT / "deploy/systemd/christiania-burn-in.timer"
    ).read_text(encoding="utf-8")

    assert "OnUnitActiveSec=15min" in timer
    assert "Persistent=true" in timer


def test_burn_in_service_is_unprivileged_and_limits_write_paths():
    unit = (
        ROOT / "deploy/systemd/christiania-burn-in.service"
    ).read_text(encoding="utf-8")

    assert "User=christiania" in unit
    assert "Group=christiania" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "ProtectHome=true" in unit
    assert (
        "ReadWritePaths=/var/lib/christiania/data "
        "/var/lib/christiania/audit"
    ) in unit
    assert "christiania_release.py burn-in-sample" in unit


def test_deployment_env_routes_release_artifacts_to_persistent_audit_storage():
    env = (
        ROOT / "deploy/christiania.env.example"
    ).read_text(encoding="utf-8")

    assert (
        "CHRISTIANIA_BURN_IN_LOG="
        "/var/lib/christiania/audit/v1_burn_in.jsonl"
    ) in env
    assert (
        "CHRISTIANIA_BOOT_MARKER_PATH="
        "/var/lib/christiania/audit/v1_boot_marker.json"
    ) in env


def test_install_one_vm_will_install_new_burn_in_units_via_existing_glob():
    installer = (
        ROOT / "deploy/install_one_vm.sh"
    ).read_text(encoding="utf-8")

    assert "deploy/systemd/christiania-*.service" in installer
    assert "deploy/systemd/christiania-*.timer" in installer