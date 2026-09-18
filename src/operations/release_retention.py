from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import shutil


DEFAULT_RELEASE_RETENTION = 4


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
