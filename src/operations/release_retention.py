from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import shutil


DEFAULT_RELEASE_RETENTION = 4
DEFAULT_FAILED_RELEASE_RETENTION = 2
DEFAULT_FAILED_RELEASE_MAX_BYTES = 2 * 1024**3


@dataclass(frozen=True)
class ReleasePruneResult:
    release_root: str
    active_release: str
    retention: int
    discovered_release_count: int
    retained_release_count: int
    pruned_release_count: int
    pruned_bytes: int
    retained_releases: tuple[str, ...]
    pruned_releases: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "retained_releases": list(self.retained_releases),
            "pruned_releases": list(self.pruned_releases),
        }


def _is_commit_release(path: Path) -> bool:
    name = path.name
    return (
        path.is_dir()
        and not path.is_symlink()
        and len(name) == 40
        and all(ch in "0123456789abcdefABCDEF" for ch in name)
    )


def _tree_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except FileNotFoundError:
            continue
    return total


def prune_release_directories(
    *,
    release_root: str | Path,
    active_release: str | Path,
    retention: int = DEFAULT_RELEASE_RETENTION,
    dry_run: bool = False,
) -> ReleasePruneResult:
    """Prune old successful immutable release directories.

    The active release is always retained even if its mtime is not among the
    newest entries. The retention count is the total number of successful
    commit-named release directories to keep, including the active release.

    Non-commit directories such as "failed" are deliberately ignored.
    Symlinks are never traversed or deleted.
    """
    if retention < 2:
        raise ValueError(
            "Release retention must be >= 2 so active + rollback predecessor remain."
        )

    root = Path(release_root).expanduser().resolve()
    active = Path(active_release).expanduser().resolve()

    if not root.is_dir():
        raise FileNotFoundError(f"Release root does not exist: {root}")
    if not active.is_dir():
        raise FileNotFoundError(f"Active release does not exist: {active}")
    if active.parent != root:
        raise ValueError(
            f"Active release {active} is not a direct child of release root {root}."
        )
    if not _is_commit_release(active):
        raise ValueError(
            f"Active release is not a 40-character commit directory: {active}"
        )

    releases = [
        path
        for path in root.iterdir()
        if _is_commit_release(path)
    ]

    releases.sort(
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )

    protected: list[Path] = [active]
    for path in releases:
        if path == active:
            continue
        if len(protected) >= retention:
            break
        protected.append(path)

    protected_set = set(protected)
    stale = [
        path
        for path in releases
        if path not in protected_set
    ]

    sizes = {
        path: _tree_size(path)
        for path in stale
    }

    if not dry_run:
        for path in stale:
            if path.is_symlink() or path.parent.resolve() != root:
                raise RuntimeError(
                    f"Refusing to prune unsafe release path: {path}"
                )
            shutil.rmtree(path)

    return ReleasePruneResult(
        release_root=str(root),
        active_release=str(active),
        retention=retention,
        discovered_release_count=len(releases),
        retained_release_count=len(protected),
        pruned_release_count=len(stale),
        pruned_bytes=sum(sizes.values()),
        retained_releases=tuple(path.name for path in protected),
        pruned_releases=tuple(path.name for path in stale),
    )

@dataclass(frozen=True)
class FailedReleasePruneResult:
    failed_root: str
    retention: int
    max_bytes: int
    discovered_release_count: int
    retained_release_count: int
    pruned_release_count: int
    retained_bytes: int
    pruned_bytes: int
    retained_releases: tuple[str, ...]
    pruned_releases: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "retained_releases": list(self.retained_releases),
            "pruned_releases": list(self.pruned_releases),
        }


def _is_failed_release(path: Path) -> bool:
    if (
        not path.is_dir()
        or path.is_symlink()
    ):
        return False

    commit, separator, activation = (
        path.name.partition("-")
    )
    return (
        bool(separator)
        and bool(activation)
        and len(commit) == 40
        and all(
            ch in "0123456789abcdefABCDEF"
            for ch in commit
        )
    )


def prune_failed_release_directories(
    *,
    release_root: str | Path,
    retention: int = DEFAULT_FAILED_RELEASE_RETENTION,
    max_bytes: int = DEFAULT_FAILED_RELEASE_MAX_BYTES,
    dry_run: bool = False,
) -> FailedReleasePruneResult:
    """Bound quarantined failed release attempts by count and bytes.

    Failed release directories are never rollback authority and can otherwise
    accumulate indefinitely. The newest candidates are retained only while
    both the count and byte budgets allow them.
    """
    if retention < 0:
        raise ValueError(
            "Failed release retention cannot be negative."
        )
    if max_bytes < 0:
        raise ValueError(
            "Failed release max_bytes cannot be negative."
        )

    root = Path(
        release_root
    ).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(
            f"Release root does not exist: {root}"
        )

    failed_root = root / "failed"
    if not failed_root.exists():
        return FailedReleasePruneResult(
            failed_root=str(failed_root),
            retention=retention,
            max_bytes=max_bytes,
            discovered_release_count=0,
            retained_release_count=0,
            pruned_release_count=0,
            retained_bytes=0,
            pruned_bytes=0,
            retained_releases=(),
            pruned_releases=(),
        )
    if (
        not failed_root.is_dir()
        or failed_root.is_symlink()
    ):
        raise RuntimeError(
            f"Unsafe failed release root: {failed_root}"
        )

    candidates = [
        path
        for path in failed_root.iterdir()
        if _is_failed_release(path)
    ]
    candidates.sort(
        key=lambda path: (
            path.stat().st_mtime_ns,
            path.name,
        ),
        reverse=True,
    )

    sizes = {
        path: _tree_size(path)
        for path in candidates
    }

    retained: list[Path] = []
    retained_bytes = 0

    for path in candidates:
        size = sizes[path]
        if (
            len(retained) < retention
            and retained_bytes + size <= max_bytes
        ):
            retained.append(path)
            retained_bytes += size

    retained_set = set(retained)
    stale = [
        path
        for path in candidates
        if path not in retained_set
    ]

    if not dry_run:
        for path in stale:
            if (
                path.is_symlink()
                or path.parent.resolve()
                != failed_root.resolve()
            ):
                raise RuntimeError(
                    "Refusing to prune unsafe failed "
                    f"release path: {path}"
                )
            shutil.rmtree(path)

    return FailedReleasePruneResult(
        failed_root=str(failed_root),
        retention=retention,
        max_bytes=max_bytes,
        discovered_release_count=len(candidates),
        retained_release_count=len(retained),
        pruned_release_count=len(stale),
        retained_bytes=retained_bytes,
        pruned_bytes=sum(
            sizes[path]
            for path in stale
        ),
        retained_releases=tuple(
            path.name
            for path in retained
        ),
        pruned_releases=tuple(
            path.name
            for path in stale
        ),
    )

