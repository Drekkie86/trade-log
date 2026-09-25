from __future__ import annotations

import os
from pathlib import Path

from src.operations.release_retention import (
    prune_failed_release_directories,
    prune_release_directories,
)


def _release(root: Path, name: str, *, mtime: int) -> Path:
    path = root / name
    path.mkdir(parents=True)
    payload = path / "payload.bin"
    payload.write_bytes(b"x" * 16)
    os.utime(path, (mtime, mtime))
    os.utime(payload, (mtime, mtime))
    return path


def test_release_prune_keeps_active_plus_newest_predecessors(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()

    names = [f"{index:040x}" for index in range(1, 7)]
    paths = [
        _release(root, name, mtime=100 + index)
        for index, name in enumerate(names)
    ]

    active = paths[2]
    failed = root / "failed"
    failed.mkdir()
    (failed / "keep.txt").write_text("do not touch", encoding="utf-8")

    result = prune_release_directories(
        release_root=root,
        active_release=active,
        retention=4,
    )

    assert result.discovered_release_count == 6
    assert result.retained_release_count == 4
    assert result.pruned_release_count == 2
    assert active.exists()
    assert failed.exists()

    remaining = {
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name != "failed"
    }

    # Active is protected even though it is older than the three newest.
    assert remaining == {
        names[2],
        names[3],
        names[4],
        names[5],
    }


def test_release_prune_dry_run_does_not_delete(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()

    paths = [
        _release(root, f"{index:040x}", mtime=100 + index)
        for index in range(1, 6)
    ]

    result = prune_release_directories(
        release_root=root,
        active_release=paths[-1],
        retention=2,
        dry_run=True,
    )

    assert result.pruned_release_count == 3
    assert all(path.exists() for path in paths)


def test_release_prune_rejects_retention_below_two(tmp_path: Path):
    import pytest

    root = tmp_path / "releases"
    root.mkdir()
    active = _release(root, "1" * 40, mtime=100)

    with pytest.raises(ValueError, match="must be >= 2"):
        prune_release_directories(
            release_root=root,
            active_release=active,
            retention=1,
        )

def test_failed_release_quarantine_is_bounded_by_count_and_bytes(
    tmp_path: Path,
):
    root = tmp_path / "releases"
    failed = root / "failed"
    failed.mkdir(parents=True)

    names = [
        f"{index:040x}-20260925T12000{index}Z-{index}"
        for index in range(1, 5)
    ]

    for index, name in enumerate(names):
        path = _release(
            failed,
            name,
            mtime=100 + index,
        )
        (path / "payload.bin").write_bytes(
            b"x" * 100
        )

    result = prune_failed_release_directories(
        release_root=root,
        retention=2,
        max_bytes=500,
    )

    assert result.discovered_release_count == 4
    assert result.retained_release_count == 2
    assert result.pruned_release_count == 2

    remaining = {
        path.name
        for path in failed.iterdir()
        if path.is_dir()
    }
    assert remaining == {
        names[2],
        names[3],
    }


def test_failed_release_byte_budget_can_prune_all_quarantines(
    tmp_path: Path,
):
    root = tmp_path / "releases"
    failed = root / "failed"
    failed.mkdir(parents=True)

    path = _release(
        failed,
        ("a" * 40) + "-20260925T120000Z-1",
        mtime=100,
    )
    (path / "payload.bin").write_bytes(
        b"x" * 1024
    )

    result = prune_failed_release_directories(
        release_root=root,
        retention=2,
        max_bytes=1,
    )

    assert result.retained_release_count == 0
    assert result.pruned_release_count == 1
    assert not path.exists()
