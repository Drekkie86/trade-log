"""Fail-closed storage mount guards for Christiania recovery operations.

The configured recovery volume must be a genuine mounted filesystem, not merely
an empty directory left behind after a lost Hetzner volume mount.
No check implicitly mounts disks, creates directories or deletes backups.
"""
from __future__ import annotations

from pathlib import Path

from src.config import get_runtime_setting

RECOVERY_MOUNT_SETTING = "CHRISTIANIA_RECOVERY_VOLUME_MOUNTPOINT"


def require_recovery_volume_path(
    target: str | Path,
    *,
    must_exist: bool = False,
) -> Path:
    """Ensure a recovery path lives below the mounted recovery volume.

    The guard is opt-in for existing non-volume installations, but becomes
    mandatory wherever CHRISTIANIA_RECOVERY_VOLUME_MOUNTPOINT is configured.
    """
    path = Path(target).expanduser()
    configured = get_runtime_setting(RECOVERY_MOUNT_SETTING)
    if not configured:
        return path

    mount = Path(configured).expanduser()
    if not mount.is_absolute() or mount.is_symlink() or not mount.is_mount():
        raise RuntimeError(
            "RECOVERY_VOLUME_NOT_MOUNTED: configured recovery volume is "
            f"not an active filesystem mount: {mount}"
        )

    mounted = mount.resolve(strict=True)
    resolved_target = path.resolve(strict=must_exist)
    if resolved_target == mounted or not resolved_target.is_relative_to(mounted):
        raise RuntimeError(
            "RECOVERY_PATH_NOT_ON_VOLUME: recovery target must be a "
            f"subdirectory of the mounted recovery volume: {path}"
        )
    if must_exist and not resolved_target.is_dir():
        raise RuntimeError(
            f"RECOVERY_DIRECTORY_MISSING: {resolved_target}"
        )
    return path
