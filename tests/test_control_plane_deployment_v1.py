from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(
        encoding="utf-8"
    )


def test_windows_deployer_requires_clean_tree():
    script = _read(
        "deploy/deploy_release.ps1"
    )

    assert 'status",\n    "--porcelain"' in script
    assert (
        "Refusing deployment: working tree is not clean."
        in script
    )


def test_windows_deployer_requires_head_equal_origin_main():
    script = _read(
        "deploy/deploy_release.ps1"
    )

    assert "git fetch origin main" in script
    assert '"origin/main"' in script
    assert (
        "local HEAD is not identical to origin/main"
        in script
    )


def test_windows_deployer_uses_committed_git_archive():
    script = _read(
        "deploy/deploy_release.ps1"
    )

    assert "git archive" in script
    assert "--format=tar.gz" in script
    assert "rsync" not in script
    assert "git pull" not in script


def test_windows_deployer_normalizes_receiver_to_lf():
    script = _read(
        "deploy/deploy_release.ps1"
    )

    assert (
        '$receiverText.Replace('
        in script
    )
    assert '"`r`n"' in script
    assert '"`n"' in script
    assert (
        "System.Text.UTF8Encoding"
        in script
    )
    assert (
        "$receiverBytes -contains 13"
        in script
    )
    assert (
        "still contains CR bytes after LF normalization"
        in script
    )


def test_windows_deployer_uploads_normalized_receiver():
    script = _read(
        "deploy/deploy_release.ps1"
    )

    assert (
        '$receiverUploadPath = Join-Path $tempRoot '
        '"christiania-receive-release.sh"'
        in script
    )

    assert (
        "& scp -i $KeyPath $receiverUploadPath"
        in script
    )


def test_windows_deployer_uses_scp_then_receiver():
    script = _read(
        "deploy/deploy_release.ps1"
    )

    assert "& scp" in script
    assert "receive_release.sh" in script
    assert "sudo bash" in script


def test_receiver_does_not_use_git():
    script = _read(
        "deploy/receive_release.sh"
    )

    assert "git pull" not in script
    assert "git fetch" not in script
    assert "git checkout" not in script
    assert "git rev-parse" not in script


def test_receiver_verifies_archive_hash():
    script = _read(
        "deploy/receive_release.sh"
    )

    assert "sha256sum" in script
    assert "archive SHA-256 mismatch" in script


def test_receiver_rejects_unsafe_archive_paths():
    script = _read(
        "deploy/receive_release.sh"
    )

    assert "archive contains an absolute path" in script
    assert "archive contains path traversal" in script


def test_receiver_uses_commit_addressed_release_directory():
    script = _read(
        "deploy/receive_release.sh"
    )

    assert (
        'RELEASE_DIR="${RELEASE_ROOT}/${EXPECTED_COMMIT}"'
        in script
    )

    assert (
        'printf \'%s\\n\' "${EXPECTED_COMMIT}" '
        '> "${RELEASE_DIR}/DEPLOYED_COMMIT"'
        in script
    )


def test_receiver_preserves_vendor_runtime():
    script = _read(
        "deploy/receive_release.sh"
    )

    assert (
        'if [[ -d "${APP_LINK}/vendor" ]]'
        in script
    )

    assert (
        'cp -a "${APP_LINK}/vendor" '
        '"${RELEASE_DIR}/vendor"'
        in script
    )


def test_receiver_preflights_before_activation():
    script = _read(
        "deploy/receive_release.sh"
    )

    preflight = script.index(
        "Running release preflight before activation."
    )
    activation = script.index(
        "Preparing atomic activation."
    )

    assert preflight < activation


def test_receiver_has_rollback_path():
    script = _read(
        "deploy/receive_release.sh"
    )

    assert "rollback()" in script
    assert (
        "restoring previous Christiania release"
        in script
    )
    assert (
        'ln -s "${PREVIOUS_TARGET}" "${APP_LINK}"'
        in script
    )


def test_receiver_preserves_previous_status_wrapper_for_rollback():
    script = _read(
        "deploy/receive_release.sh"
    )

    assert (
        'STATUS_WRAPPER_HAD_PREVIOUS=0'
        in script
    )
    assert (
        'cp -a "${LOCAL_BIN}/christiania-status" "${STATUS_BACKUP}"'
        in script
    )
    assert (
        'cp -a "${STATUS_BACKUP}" "${LOCAL_BIN}/christiania-status"'
        in script
    )


def test_receiver_installs_canonical_resource_policy():
    script = _read(
        "deploy/receive_release.sh"
    )

    assert (
        "christiania_resource_policy.py"
        in script
    )
    assert "render" in script
    assert "check" in script


def test_receiver_does_not_enable_disabled_timers():
    script = _read(
        "deploy/receive_release.sh"
    )

    assert "systemctl enable" not in script
    assert "systemctl preset" not in script


def test_receiver_verifies_core_services_after_activation():
    script = _read(
        "deploy/receive_release.sh"
    )

    assert "christiania-theta.service" in script
    assert "christiania-daemon.service" in script
    assert "christiania-app.service" in script
    assert (
        'systemctl is-active "${service}"'
        in script
    )


def test_receiver_runs_post_activation_preflight():
    script = _read(
        "deploy/receive_release.sh"
    )

    assert (
        "Running post-activation deployment preflight."
        in script
    )


def test_receiver_refreshes_supervisor_before_status():
    script = _read(
        "deploy/receive_release.sh"
    )

    refresh = script.index(
        "Refreshing authoritative supervisor evidence."
    )
    status = script.index(
        "Running Christiania control-plane status."
    )

    assert refresh < status
    assert (
        "systemctl start christiania-supervisor.service"
        in script
    )


def test_receiver_installs_single_status_command():
    script = _read(
        "deploy/receive_release.sh"
    )

    assert (
        '"${APP_LINK}/deploy/christiania-status"'
        in script
    )
    assert (
        '"${LOCAL_BIN}/christiania-status"'
        in script
    )


def test_receiver_requires_control_plane_status_to_pass():
    script = _read(
        "deploy/receive_release.sh"
    )

    status_index = script.index(
        "Running Christiania control-plane status."
    )
    success_index = script.index(
        "CHRISTIANIA RELEASE ACTIVATED"
    )

    assert status_index < success_index

    assert (
        '"${LOCAL_BIN}/christiania-status" --json'
        in script
    )


def test_status_wrapper_uses_active_release_not_git_checkout():
    script = _read(
        "deploy/christiania-status"
    )

    assert 'APP_DIR="/opt/christiania"' in script
    assert "christiania_status.py" in script
    assert "git " not in script
    assert "trade-log-rc0" not in script


def test_status_wrapper_runs_as_service_account():
    script = _read(
        "deploy/christiania-status"
    )

    assert 'SERVICE_USER="christiania"' in script
    assert 'sudo -u "${SERVICE_USER}"' in script


def test_status_wrapper_passes_cli_arguments_through():
    script = _read(
        "deploy/christiania-status"
    )

    assert '"$@"' in script