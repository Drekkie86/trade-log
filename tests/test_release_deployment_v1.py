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
        'phase_start "Quiescing scheduled jobs and database consumers"'
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
        'phase_start "Validating target release prerequisites"'
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


def test_release_receiver_gives_atomic_pointer_writer_private_workspace():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    assert 'install -d -m 0750 -o root -g "${SERVICE_USER}" "${ROLLBACK_ROOT}"' in receiver
    assert 'DB_ROLLBACK_DIR="${ROLLBACK_ROOT}/${ACTIVATION_ID}-database"' in receiver
    assert 'DB_ROLLBACK_POINTER="${DB_ROLLBACK_DIR}/rollback.txt"' in receiver
    assert (
        'install -d -m 0700 -o "${SERVICE_USER}" -g "${SERVICE_USER}" '
        '"${DB_ROLLBACK_DIR}"'
    ) in receiver
    assert (
        'install -m 0600 -o "${SERVICE_USER}" -g "${SERVICE_USER}" '
        '/dev/null "${DB_ROLLBACK_POINTER}"'
    ) in receiver

    prepare = receiver.index('DB_PREP_OUTPUT="$(')
    harden = receiver.index(
        'chown -R root:root "${DB_ROLLBACK_DIR}"',
        prepare,
    )
    target_preflight = receiver.index(
        'phase_start "Validating target release prerequisites"',
        harden,
    )

    assert prepare < harden < target_preflight
    assert 'chmod 0700 "${DB_ROLLBACK_DIR}"' in receiver[harden:target_preflight]
    assert 'chmod 0600 "${DB_ROLLBACK_POINTER}"' in receiver[harden:target_preflight]


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


def test_release_receiver_quiesces_all_scheduled_jobs_before_migration():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    quiesce = receiver.index(
        'phase_start "Quiescing scheduled jobs and database consumers"'
    )
    timer_stop = receiver.index(
        'for timer in "${QUIESCE_TIMER_UNITS[@]}"; do',
        quiesce,
    )
    oneshot_guard = receiver.index(
        "assert_no_busy_oneshots",
        timer_stop,
    )
    quiesce_guard = receiver.index(
        "SERVICES_QUIESCED=1",
        oneshot_guard,
    )
    app_daemon_stop = receiver.index(
        'for service in "${QUIESCE_SERVICES[@]}"; do',
        quiesce_guard,
    )
    theta_guard = receiver.index(
        'systemctl is-active christiania-theta.service',
        app_daemon_stop,
    )
    prepare = receiver.index(
        'DB_PREP_OUTPUT="$(' ,
        theta_guard,
    )
    restore_timers = receiver.index(
        'echo "Restoring scheduled Christiania timers."',
        prepare,
    )

    assert (
        quiesce
        < timer_stop
        < oneshot_guard
        < quiesce_guard
        < app_daemon_stop
        < theta_guard
        < prepare
        < restore_timers
    )

    for timer in (
        "christiania-audit.timer",
        "christiania-backup.timer",
        "christiania-burn-in.timer",
        "christiania-health.timer",
        "christiania-restore-drill.timer",
        "christiania-supervisor.timer",
        "christiania-theta-refresh.timer",
        "christiania-theta-watchdog.timer",
        "christiania-v1-readiness.timer",
    ):
        assert f'  "{timer}"' in receiver

    for service in (
        "christiania-audit.service",
        "christiania-backup.service",
        "christiania-burn-in.service",
        "christiania-health.service",
        "christiania-restore-drill.service",
        "christiania-supervisor.service",
        "christiania-theta-refresh.service",
        "christiania-theta-watchdog.service",
        "christiania-theta-recover.service",
        "christiania-v1-readiness.service",
    ):
        assert f'  "{service}"' in receiver

    assert 'ACTIVE_QUIESCE_TIMERS+=("${timer}")' in receiver
    assert 'stop_unit_for_release "${timer}"' in receiver

    quiesce_block = receiver[
        quiesce:prepare
    ]

    # One-shot work is guarded, never stopped by the release receiver.
    assert (
        'for service in "${QUIESCE_ONESHOT_SERVICES[@]}"; do'
        not in quiesce_block
    )
    assert (
        quiesce_block.count(
            "assert_no_busy_oneshots"
        )
        == 2
    )

    # Database consumers still must actually be stopped.
    core_loop_start = quiesce_block.index(
        'for service in "${QUIESCE_SERVICES[@]}"; do'
    )
    core_loop_end = quiesce_block.index(
        "done",
        core_loop_start,
    )
    core_loop = quiesce_block[
        core_loop_start:core_loop_end
    ]

    assert (
        'stop_unit_for_release "${service}"'
        in core_loop
    )

    assert 'systemctl start "${timer}"' in receiver


def test_release_receiver_has_complete_command_prerequisite_checks():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    required_block = receiver.split("for required in", 1)[1].split("; do", 1)[0]
    required_commands = set(required_block.replace("\\", " ").split())

    assert {
        "awk",
        "basename",
        "chmod",
        "chown",
        "cp",
        "curl",
        "date",
        "find",
        "id",
        "install",
        "ln",
        "mktemp",
        "mv",
        "python3",
        "readlink",
        "rm",
        "seq",
        "sha256sum",
        "sleep",
        "sudo",
        "systemctl",
        "tar",
        "tr",
    }.issubset(required_commands)


def test_release_receiver_avoids_redundant_deep_database_preflights():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")
    preflight = (
        ROOT / "christiania_deploy_preflight.py"
    ).read_text(encoding="utf-8")

    assert '"${LOCAL_BIN}/christiania-status" --json' in receiver
    assert "Deep database integrity is not repeated here." in receiver
    assert receiver.count("--metadata-db-check") == 2
    assert "deep_database: bool = True" in preflight
    assert "deep_integrity=False" in preflight
    assert '"--metadata-db-check"' in preflight


def test_release_receiver_reports_phase_timings():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(encoding="utf-8")

    assert "phase_start()" in receiver
    assert "phase_done()" in receiver
    assert 'completed in ${elapsed}s' in receiver
    assert 'phase_start "Preparing release database"' in receiver
    assert 'phase_start "Verifying live application and secure edge"' in receiver
    assert 'echo "Quiescing ${unit}..."' in receiver
    assert 'echo "Quiesced ${unit} in ${elapsed}s; ActiveState=${state}"' in receiver


def test_release_client_keeps_long_ssh_sessions_alive():
    deployer = (
        ROOT / "deploy/deploy_release.ps1"
    ).read_text(encoding="utf-8")

    assert '"-o", "ServerAliveInterval=15"' in deployer
    assert '"-o", "ServerAliveCountMax=20"' in deployer
    assert '"-o", "TCPKeepAlive=yes"' in deployer
    assert "& ssh @SshOptions -t -i $KeyPath" in deployer


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


def test_release_receiver_pre_activation_gate_uses_current_release_policy():
    receiver = (
        ROOT / "deploy/receive_release.sh"
    ).read_text(
        encoding="utf-8"
    )

    phase = receiver.index(
        'phase_start "Validating current production deployment safety"'
    )
    phase_end = receiver.index(
        "phase_done",
        phase,
    )

    block = receiver[
        phase:phase_end
    ]

    assert (
        '"${PREVIOUS_TARGET}/.venv/bin/python"'
        in block
    )
    assert (
        '"${PREVIOUS_TARGET}/christiania_status.py"'
        in block
    )
    assert (
        '"${RELEASE_DIR}/christiania_status.py"'
        not in block
    )

    activation = receiver.index(
        'ln -s "${RELEASE_DIR}" "${APP_LINK}"'
    )

    target_policy_check = receiver.index(
        '"${APP_LINK}/christiania_resource_policy.py" \\',
        activation,
    )

    post_activation_status = receiver.index(
        '"${LOCAL_BIN}/christiania-status" --json --deployment-safe',
        target_policy_check,
    )

    assert (
        phase
        < phase_end
        < activation
        < target_policy_check
        < post_activation_status
    )



def test_release_receiver_capacity_preflight_happens_before_quiescence():
    receiver = (
        ROOT
        / "deploy/receive_release.sh"
    ).read_text(
        encoding="utf-8"
    )

    database_metadata = receiver.index(
        'phase_start "Validating current database schema/WAL metadata"'
    )
    capacity_preflight = receiver.index(
        'phase_start "Preflighting target database migration capacity"'
    )
    preflight_command = receiver.index(
        "preflight \\",
        capacity_preflight,
    )
    quiesce = receiver.index(
        'phase_start "Quiescing scheduled jobs and database consumers"'
    )
    actual_prepare = receiver.index(
        'phase_start "Preparing release database"'
    )

    assert (
        database_metadata
        < capacity_preflight
        < preflight_command
        < quiesce
        < actual_prepare
    )

    # The early preflight is advisory in timing, not a replacement for the
    # capacity check repeated by the actual rollback-copy creation.
    release_db = (
        ROOT
        / "christiania_release_database.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "assert_backup_capacity("
        in release_db
    )



def test_release_receiver_never_stops_busy_oneshot_during_rollback():
    receiver = (
        ROOT
        / "deploy/receive_release.sh"
    ).read_text(
        encoding="utf-8"
    )

    rollback_start = receiver.index(
        "rollback() {"
    )
    rollback_end = receiver.index(
        "trap 'rollback $?'",
        rollback_start,
    )
    rollback = receiver[
        rollback_start:rollback_end
    ]

    assert (
        'QUIESCE_ONESHOT_SERVICES'
        not in rollback
    )
    assert (
        "release refuses to interrupt busy one-shot service"
        in receiver
    )

    helper_start = receiver.index(
        "unit_is_busy_for_release()"
    )
    helper_end = receiver.index(
        "assert_no_busy_oneshots()",
        helper_start,
    )
    helper = receiver[
        helper_start:helper_end
    ]

    for state in (
        "active",
        "activating",
        "reloading",
        "deactivating",
    ):
        assert state in helper



def test_release_rollback_refuses_database_restore_if_new_oneshot_is_busy():
    receiver = (
        ROOT
        / "deploy/receive_release.sh"
    ).read_text(
        encoding="utf-8"
    )

    rollback_start = receiver.index(
        "rollback() {"
    )
    rollback_end = receiver.index(
        "trap 'rollback $?'",
        rollback_start,
    )
    rollback = receiver[
        rollback_start:rollback_end
    ]

    guard = rollback.index(
        "AUTOMATIC ROLLBACK REFUSED"
    )
    app_link_restore = rollback.index(
        'if [[ "${APP_LINK_MUTATED}" -eq 1 ]]'
    )
    database_restore = rollback.index(
        'if [[ "${DATABASE_PREPARED}" -eq 1 ]]'
    )

    assert (
        guard
        < app_link_restore
        < database_restore
    )
    assert (
        'unit_is_busy_for_release "${service}"'
        in rollback
    )
    assert (
        "Core services remain stopped"
        in rollback
    )
