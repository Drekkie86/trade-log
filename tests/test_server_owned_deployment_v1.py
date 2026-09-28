from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_server_release_launcher_is_disconnect_safe_and_bounded():
    launcher = (
        ROOT / "deploy/start_release.sh"
    ).read_text(encoding="utf-8")

    assert "systemd-run" in launcher
    assert "--no-block" in launcher
    assert "--property=Type=exec" in launcher
    assert "--property=Restart=no" in launcher
    assert "--property=KillMode=mixed" in launcher
    assert "--property=TimeoutStopSec=infinity" in launcher
    assert "status_path=${STATUS_FILE}" in launcher
    assert "unit=${UNIT}" in launcher


def test_server_release_runner_owns_exclusive_deployment_lock():
    runner = (
        ROOT / "deploy/run_server_release.sh"
    ).read_text(encoding="utf-8")

    assert 'LOCK_FILE="/run/lock/christiania-deploy.lock"' in runner
    assert 'exec 9>"${LOCK_FILE}"' in runner
    assert "flock -n 9" in runner
    assert "CHRISTIANIA_DEPLOY_LOCK_HELD=1" in runner
    assert 'status_write "RUNNING"' in runner
    assert 'status_write "SUCCEEDED"' in runner
    assert 'status_write "FAILED"' in runner


def test_release_client_requires_exact_main_sha_green_push_ci():
    deployer = (
        ROOT / "deploy/deploy_release.ps1"
    ).read_text(encoding="utf-8")

    assert "Assert-ExactShaQualityGate -Commit $head" in deployer
    assert '$_.event -eq "push"' in deployer
    assert '$_.conclusion -eq "success"' in deployer
    assert '$_.head_sha -eq $Commit' in deployer
    assert "local HEAD is not identical to origin/main" in deployer


def test_release_client_uses_server_owned_launcher_not_direct_receiver():
    deployer = (
        ROOT / "deploy/deploy_release.ps1"
    ).read_text(encoding="utf-8")

    assert "[switch]$Detach" in deployer
    assert "$launcherSourcePath" in deployer
    assert "$runnerSourcePath" in deployer
    assert "sudo bash $remoteLauncher" in deployer
    assert "sudo bash $remoteReceiver $remoteArchive" not in deployer
    assert "Deployment is server-owned" in deployer
    assert "sudo cat $statusPath" in deployer
    assert "journalctl -u $unit -n 120 --no-pager" in deployer


@pytest.mark.parametrize(
    "relative",
    [
        "deploy/start_release.sh",
        "deploy/run_server_release.sh",
        "deploy/probe_release_performance.sh",
        "deploy/receive_release.sh",
    ],
)
def test_release_shell_entrypoints_have_valid_bash_syntax(relative):
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable on this test host")

    completed = subprocess.run(
        [bash, "-n", str(ROOT / relative)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_release_performance_probe_never_mutates_live_runtime():
    probe = (
        ROOT / "deploy/probe_release_performance.sh"
    ).read_text(encoding="utf-8")

    assert 'PROBE_ROOT="/opt/christiania-probes"' in probe
    assert '--include-full' in probe
    assert '--warmups 1' in probe
    assert '--runs 3' in probe
    assert 'christiania_performance_probe.py' in probe
    assert 'systemctl stop' not in probe
    assert 'systemctl restart' not in probe
    assert 'ln -s "${PROBE_DIR}" "${APP_LINK}"' not in probe
    assert 'christiania_release_database.py' not in probe
    assert 'PRAGMA wal_checkpoint' not in probe
    assert 'ANALYZE' not in probe
    assert 'VACUUM' not in probe


def test_release_activation_requires_recent_exact_sha_performance_evidence():
    deployer = (
        ROOT / "deploy/deploy_release.ps1"
    ).read_text(encoding="utf-8")

    assert "performance-probes" in deployer
    assert "-mmin -1440" in deployer
    assert "Run deploy/probe_release_performance.ps1 first." in deployer
    assert "performanceReport.release_commit -ne $head" in deployer
    assert "performanceReport.read_only" in deployer
    assert "performanceReport.probe_version -lt 2" in deployer
    assert '"Dashboard", "Decision Desk", "Research Runs", "Calibration", "Observations", "Shadow Lab", "Ops", "FULL"' in deployer


def test_performance_probe_client_is_exact_main_sha_and_server_owned():
    client = (
        ROOT / "deploy/probe_release_performance.ps1"
    ).read_text(encoding="utf-8")

    assert "local HEAD is not identical to origin/main" in client
    assert "$_.event -eq \"push\"" in client
    assert "$_.conclusion -eq \"success\"" in client
    assert "systemd-run" in client
    assert "--property=TimeoutStopSec=infinity" in client
    assert "--no-block" in client
    assert "performanceReport" not in client
    assert "release_commit" in client
    assert "read_only" in client


def test_release_and_probe_refuse_heavy_maintenance_conflicts():
    for relative in (
        "deploy/start_release.sh",
        "deploy/probe_release_performance.sh",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "HEAVY_MAINTENANCE_UNITS=(" in source
        assert "christiania-backup.service" in source
        assert "christiania-backup-compress.service" in source
        assert "christiania-restore-drill.service" in source
        assert "systemctl is-active --quiet" in source
        assert "heavy maintenance is active" in source
