"""Safe mount-required backup writes and restore-drill scratch isolation."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.operations.backup_recovery import (
    _restore_drill_scratch_directory,
    run_restore_drill,
)
from src.operations.sqlite_runtime import create_verified_backup, resolve_backup_dir


def _configure_volume(monkeypatch, volume: Path, scratch: Path | None):
    monkeypatch.setenv("CHRISTIANIA_RECOVERY_VOLUME_MOUNTPOINT", str(volume))
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR", str(volume / "backups"))
    if scratch is not None:
        monkeypatch.setenv("CHRISTIANIA_RESTORE_DRILL_SCRATCH_DIR", str(scratch))
    else:
        monkeypatch.delenv("CHRISTIANIA_RESTORE_DRILL_SCRATCH_DIR", raising=False)
    # Simulate the mounted volume on platforms where tmp_path cannot be mounted.
    monkeypatch.setattr(
        Path, "is_mount",
        lambda self: self.resolve() == volume.resolve(),
    )


def test_configured_backup_volume_rejects_missing_mount_before_backup_write(
    db_path, tmp_path, monkeypatch
):
    volume = tmp_path / "volume"
    volume.mkdir()
    target = volume / "backups"
    monkeypatch.setenv("CHRISTIANIA_RECOVERY_VOLUME_MOUNTPOINT", str(volume))
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR", str(target))
    monkeypatch.setattr(Path, "is_mount", lambda self: False)

    with pytest.raises(RuntimeError, match="RECOVERY_VOLUME_NOT_MOUNTED"):
        create_verified_backup(db_path=db_path)
    assert not target.exists()


def test_configured_volume_rejects_root_disk_fallback_and_symlink(
    tmp_path, monkeypatch
):
    volume = tmp_path / "volume"
    volume.mkdir()
    scratch = volume / "scratch"
    scratch.mkdir()
    _configure_volume(monkeypatch, volume, scratch)

    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR", str(tmp_path / "root-backups"))
    with pytest.raises(RuntimeError, match="RECOVERY_PATH_NOT_ON_VOLUME"):
        resolve_backup_dir()

    outside = tmp_path / "escaped"
    outside.mkdir()
    try:
        (volume / "backups").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows account lacks symlink creation privilege")
        raise
    monkeypatch.setenv("CHRISTIANIA_BACKUP_DIR", str(volume / "backups"))
    with pytest.raises(RuntimeError, match="RECOVERY_PATH_NOT_ON_VOLUME"):
        resolve_backup_dir()


def test_restore_drill_requires_explicit_scratch_with_volume(
    db_path, tmp_path, monkeypatch
):
    volume = tmp_path / "volume"
    volume.mkdir()
    _configure_volume(monkeypatch, volume, None)

    with pytest.raises(RuntimeError, match="RECOVERY_SCRATCH_CONFIGURATION_INCOMPLETE"):
        _restore_drill_scratch_directory()


def test_restore_drill_fails_closed_when_scratch_is_not_mounted(
    tmp_path, monkeypatch
):
    volume = tmp_path / "volume"
    volume.mkdir()
    scratch = volume / "scratch"
    scratch.mkdir()
    _configure_volume(monkeypatch, volume, scratch)
    monkeypatch.setattr(Path, "is_mount", lambda self: False)

    with pytest.raises(RuntimeError, match="RECOVERY_VOLUME_NOT_MOUNTED"):
        _restore_drill_scratch_directory()


def test_mounted_volume_restores_to_scratch_without_touching_source(
    db_path, tmp_path, monkeypatch
):
    # Create verified test backup before configuring the production mount guard.
    backing = tmp_path / "ordinary"
    ordinary = create_verified_backup(db_path=db_path, backup_dir=backing)
    backup = Path(ordinary.backup_path)
    original = backup.read_bytes()

    volume = tmp_path / "volume"
    volume.mkdir()
    (volume / "backups").mkdir()
    scratch = volume / "scratch"
    scratch.mkdir()
    _configure_volume(monkeypatch, volume, scratch)
    assert resolve_backup_dir() == volume / "backups"
    assert _restore_drill_scratch_directory() == scratch

    import src.operations.backup_recovery as recovery
    real_tempdir = recovery.tempfile.TemporaryDirectory
    recorded = []

    def observed_tempdir(*args, **kwargs):
        recorded.append(kwargs["dir"])
        return real_tempdir(*args, **kwargs)

    monkeypatch.setattr(recovery.tempfile, "TemporaryDirectory", observed_tempdir)
    outcome = run_restore_drill(backup)
    assert outcome.state == "PASSED"
    assert recorded == [scratch]
    assert list(scratch.iterdir()) == []
    assert backup.read_bytes() == original
