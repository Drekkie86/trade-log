"""Theta vendor updater must write to persistent service-owned state, not releases."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from run_theta_terminal import theta_auth_mode, theta_command
from src.operations.theta_mutable_runtime import theta_runtime_jar

ROOT = Path(__file__).resolve().parents[1]


def _fixture(tmp_path):
    vendor = tmp_path / "immutable" / "vendor"
    lib = vendor / "lib"
    lib.mkdir(parents=True)
    source_jar = vendor / "ThetaTerminalv3.jar"
    source_jar.write_bytes(b"first-vendor-jar")
    (lib / "202608191.jar").write_bytes(b"old-version")
    state = tmp_path / "persistent-theta"
    state.mkdir()
    return source_jar, state


def test_theta_initializes_persistent_state_without_mutating_source(tmp_path, monkeypatch):
    source, state = _fixture(tmp_path)
    (source.parent / "creds.txt").write_bytes(b"secret-no-print")
    monkeypatch.setenv("STATE_DIRECTORY", str(state))
    output = theta_runtime_jar(source)

    assert output == state / "active" / "ThetaTerminalv3.jar"
    assert output.read_bytes() == b"first-vendor-jar"
    assert (state / "active" / "lib" / "202608191.jar").read_bytes() == b"old-version"
    assert (state / "active" / "creds.txt").read_bytes() == b"secret-no-print"
    assert source.read_bytes() == b"first-vendor-jar"
    marker = json.loads((state / "active" / "bootstrap.json").read_text())
    assert "sha256" in "".join(marker.keys())
    assert "secret-no-print" not in json.dumps(marker)
    if os.name == "posix":
        assert output.stat().st_mode & 0o777 == 0o600
        assert (state / "active").stat().st_mode & 0o777 == 0o700


def test_theta_preserves_updates_across_service_restarts_and_new_releases(tmp_path, monkeypatch):
    source, state = _fixture(tmp_path)
    monkeypatch.setenv("STATE_DIRECTORY", str(state))
    jar = theta_runtime_jar(source)
    update = jar.parent / "lib" / "202610091.jar"
    update.write_bytes(b"downloaded-updater-version")
    source.write_bytes(b"new-immutable-release-jar")

    assert theta_runtime_jar(source) == jar
    assert jar.read_bytes() == b"first-vendor-jar"
    assert update.read_bytes() == b"downloaded-updater-version"
    source.unlink()
    assert theta_runtime_jar(source) == jar  # no regression on a later release


def test_incomplete_or_symlinked_runtime_fails_closed(tmp_path, monkeypatch):
    source, state = _fixture(tmp_path)
    monkeypatch.setenv("STATE_DIRECTORY", str(state))
    (state / "active").mkdir()
    with pytest.raises(RuntimeError, match="incomplete"):
        theta_runtime_jar(source)
    if os.name != "nt":
        (state / "active").rmdir()
        (state / "active").symlink_to(source.parent, target_is_directory=True)
        with pytest.raises(RuntimeError, match="symlink"):
            theta_runtime_jar(source)


@pytest.mark.skipif(os.name == "nt", reason="Windows CI symlinks require extra privileges")
def test_unsafe_bootstrap_vendor_library_symlink_rejected(tmp_path, monkeypatch):
    source, state = _fixture(tmp_path)
    monkeypatch.setenv("STATE_DIRECTORY", str(state))
    outside = tmp_path / "outside.jar"
    outside.write_bytes(b"wrong")
    (source.parent / "lib" / "escape.jar").symlink_to(outside)
    with pytest.raises(RuntimeError, match="symbolic link"):
        theta_runtime_jar(source)
    assert not (state / "active").exists()


def test_service_theta_command_and_file_auth_use_persistent_jar(tmp_path, monkeypatch):
    source, state = _fixture(tmp_path)
    (source.parent / "creds.txt").write_bytes(b"private")
    monkeypatch.setenv("STATE_DIRECTORY", str(state))
    monkeypatch.setenv("CHRISTIANIA_THETA_JAR", str(source))
    monkeypatch.delenv("THETADATA_API_KEY", raising=False)
    monkeypatch.setattr(
        "run_theta_terminal.shutil.which",
        lambda name: "/usr/bin/java" if name == "java" else None,
    )
    assert theta_command() == [
        "/usr/bin/java",
        "-jar",
        str(state / "active" / "ThetaTerminalv3.jar"),
    ]
    assert theta_auth_mode() == "CREDS_FILE"


def test_manual_non_systemd_command_keeps_legacy_path(tmp_path, monkeypatch):
    source, state = _fixture(tmp_path)
    monkeypatch.delenv("STATE_DIRECTORY", raising=False)
    assert theta_runtime_jar(source) == source
    assert not (state / "active").exists()


def test_systemd_isolated_writable_state_and_no_mutable_release():
    unit = (ROOT / "deploy/systemd/christiania-theta.service").read_text()
    assert "StateDirectory=christiania-theta" in unit
    assert "StateDirectoryMode=0700" in unit
    assert "User=christiania" in unit
    assert "WorkingDirectory=/opt/christiania" in unit
    assert "ReadWritePaths=/opt/christiania" not in unit
