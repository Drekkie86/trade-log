from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

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


def test_release_receiver_prepares_database_before_atomic_activation():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    quiesce = receiver.index(
        'echo "Quiescing Christiania database consumers for release migration."'
    )
    rollback_guard = receiver.index(
        "DATABASE_PREPARED=1",
        quiesce,
    )
    prepare = receiver.index(
        '"${RELEASE_DIR}/christiania_release_database.py"',
        rollback_guard,
    )
    target_preflight = receiver.index(
        'echo "Running target-release preflight against the migrated database."'
    )
    activation = receiver.index(
        'ln -s "${RELEASE_DIR}" "${APP_LINK}"'
    )

    assert quiesce < rollback_guard < prepare < target_preflight < activation
    assert '--rollback-pointer "${DB_ROLLBACK_POINTER}"' in receiver


def test_release_receiver_restores_database_before_restarting_old_services():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    rollback_start = receiver.index("rollback() {")
    restore = receiver.index(
        '--backup "${ROLLBACK_DB_BACKUP}"',
        rollback_start,
    )
    daemon_reload = receiver.index(
        "systemctl daemon-reload || true",
        restore,
    )
    restart = receiver.index(
        'systemctl start "${service}" >/dev/null 2>&1',
        daemon_reload,
    )

    assert rollback_start < restore < daemon_reload < restart
    assert "DATABASE ROLLBACK FAILED; core services remain stopped." in receiver


def test_release_receiver_can_restore_app_link_if_new_link_creation_fails():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    rollback_start = receiver.index("rollback() {")
    rollback_link_guard = receiver.index(
        'if [[ "${APP_LINK_MUTATED}" -eq 1 ]]; then',
        rollback_start,
    )
    rollback_restore_link = receiver.index(
        'ln -s "${PREVIOUS_TARGET}" "${APP_LINK}"',
        rollback_link_guard,
    )

    activation_start = receiver.index(
        'if [[ "${LEGACY_SOURCE}" -eq 1 ]]; then'
    )
    first_mutation_guard = receiver.index(
        "APP_LINK_MUTATED=1",
        activation_start,
    )
    second_mutation_guard = receiver.index(
        "APP_LINK_MUTATED=1",
        first_mutation_guard + 1,
    )
    new_link = receiver.index(
        'ln -s "${RELEASE_DIR}" "${APP_LINK}"',
        second_mutation_guard,
    )
    activated = receiver.index(
        "ACTIVATED=1",
        new_link,
    )

    assert rollback_link_guard < rollback_restore_link
    assert activation_start < first_mutation_guard < second_mutation_guard < new_link < activated
    assert receiver.count("APP_LINK_MUTATED=1") == 2


def test_release_receiver_treats_empty_pointer_as_pre_mutation_interrupt():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    assert (
        "Database preparation stopped before the rollback pointer was committed; "
        "no migration could have started."
    ) in receiver
    assert "DATABASE ROLLBACK METADATA MISSING" not in receiver
    assert 'if [[ -s "${DB_ROLLBACK_POINTER}" ]]; then' in receiver


def test_release_receiver_quarantines_incomplete_same_commit_retry():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    assert 'FAILED_RELEASE_ROOT="${RELEASE_ROOT}/failed"' in receiver
    assert 'if [[ -e "${RELEASE_DIR}" || -L "${RELEASE_DIR}" ]]; then' in receiver
    assert 'echo "Quarantining incomplete prior attempt for ${EXPECTED_COMMIT}' in receiver
    assert 'mv -- "${RELEASE_DIR}" "${QUARANTINED_RELEASE}"' in receiver
    assert 'rm -rf -- "${RELEASE_DIR}"' not in receiver
    assert "requested release is already the active release" in receiver
    assert 'ACTIVATION_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"' in receiver


def test_release_receiver_quiesces_db_observers_during_migration_and_restores_timers():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    quiesce = receiver.index(
        'echo "Quiescing Christiania database consumers for release migration."'
    )
    timer_stop = receiver.index(
        'for timer in "${DB_TIMER_UNITS[@]}"; do',
        quiesce,
    )
    oneshot_stop = receiver.index(
        'for service in "${DB_ONESHOT_SERVICES[@]}"; do',
        timer_stop,
    )
    app_daemon_stop = receiver.index(
        'for service in "${QUIESCE_SERVICES[@]}"; do',
        oneshot_stop,
    )
    prepare = receiver.index(
        'DB_PREP_OUTPUT="$(' ,
        app_daemon_stop,
    )
    restore_timers = receiver.index(
        'echo "Restoring database-observer timers."',
        prepare,
    )

    assert timer_stop < oneshot_stop < app_daemon_stop < prepare < restore_timers
    for timer in (
        "christiania-audit.timer",
        "christiania-backup.timer",
        "christiania-burn-in.timer",
        "christiania-health.timer",
        "christiania-restore-drill.timer",
        "christiania-supervisor.timer",
        "christiania-v1-readiness.timer",
    ):
        assert f'  "{timer}"' in receiver
    assert 'ACTIVE_DB_TIMERS+=("${timer}")' in receiver
    assert 'systemctl start "${timer}"' in receiver


def test_release_receiver_warns_that_full_current_health_check_can_take_time():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    assert "SQLite integrity check can take several minutes" in receiver
    assert "must not be interrupted" in receiver


def test_release_receiver_has_valid_bash_syntax():
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable on this test host")

    completed = subprocess.run(
        [bash, "-n", str(ROOT / "deploy/receive_release.sh")],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
