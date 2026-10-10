"""Prepare a persistent, service-owned Theta Terminal updater workspace.

The root-owned Christiania release is a read-only bootstrap source. Theta's
versioned JAR downloads must live outside that immutable release. When systemd
provides STATE_DIRECTORY, stage the initial vendor tree atomically. Later
service restarts reuse the persisted tree, including Theta's own updates.

No provider requests, service control or database writes occur here.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path


def _checked_regular_file(path: Path) -> bool:
    if path.is_symlink():
        raise RuntimeError("Theta vendor source contains a symbolic link.")
    if not path.exists():
        return False
    if not path.is_file():
        raise RuntimeError("Theta vendor source is not a regular file.")
    return True


def _copy_vendor_file(source: Path, destination: Path) -> None:
    if not _checked_regular_file(source):
        raise FileNotFoundError("Required Theta vendor file is absent.")
    with source.open("rb") as infile, destination.open("xb") as outfile:
        shutil.copyfileobj(infile, outfile, length=1024 * 1024)
    destination.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _stage_vendor(source_jar: Path, destination: Path) -> str:
    _copy_vendor_file(source_jar, destination / "ThetaTerminalv3.jar")

    source_lib = source_jar.parent / "lib"
    if source_lib.is_symlink():
        raise RuntimeError("Theta vendor library directory must not be a symlink.")
    if source_lib.exists():
        if not source_lib.is_dir():
            raise RuntimeError("Theta vendor library location is not a directory.")
        for base, dirs, files in os.walk(source_lib, followlinks=False):
            here = Path(base)
            if here.is_symlink():
                raise RuntimeError("Theta vendor library symlink refused.")
            relative = here.relative_to(source_lib)
            target = destination / "lib" / relative
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.chmod(0o700)
            for name in dirs:
                if (here / name).is_symlink():
                    raise RuntimeError("Theta vendor library symlink refused.")
            for name in files:
                _copy_vendor_file(here / name, target / name)

    # File-based vendor credentials are copied only within the 0700 service
    # workspace, never printed or embedded into a release or report.
    credentials = source_jar.parent / "creds.txt"
    if _checked_regular_file(credentials):
        _copy_vendor_file(credentials, destination / "creds.txt")

    digest = hashlib.sha256()
    with source_jar.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    info = {
        "bootstrap_jar_sha256": digest.hexdigest(),
        "source": "immutable_release_vendor",
        "state": "service_owned_mutable_theta_runtime",
    }
    marker = destination / "bootstrap.json"
    marker.write_text(json.dumps(info, sort_keys=True) + "\n", encoding="utf-8")
    marker.chmod(0o600)
    return digest.hexdigest()


def theta_runtime_jar(source_jar: Path) -> Path:
    """Resolve executable JAR, creating state once when run under systemd.

    Outside the actual Theta systemd service, retain the configured JAR path
    so development tools and deployment preflight remain read-only.
    """
    state_path = os.environ.get("STATE_DIRECTORY", "").strip()
    if not state_path:
        if not _checked_regular_file(source_jar):
            raise FileNotFoundError(f"Theta Terminal jar not found: {source_jar}")
        return source_jar

    if os.pathsep in state_path:
        raise RuntimeError("Theta service requires exactly one StateDirectory.")
    root = Path(state_path)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise RuntimeError("Theta persistent StateDirectory is missing or unsafe.")
    if os.name == "posix" and root.stat().st_uid != os.geteuid():
        raise RuntimeError("Theta StateDirectory is not owned by the service user.")
    if not os.access(root, os.W_OK | os.X_OK):
        raise RuntimeError("Theta StateDirectory is not writable by its service.")

    active = root / "active"
    jar = active / "ThetaTerminalv3.jar"
    if active.is_symlink() or jar.is_symlink():
        raise RuntimeError("Theta active runtime symlink refused.")
    if active.exists():
        lib = active / "lib"
        if not active.is_dir() or not jar.is_file():
            raise RuntimeError("Theta active runtime exists but is incomplete.")
        if lib.is_symlink() or (lib.exists() and not lib.is_dir()):
            raise RuntimeError("Theta active runtime library is unsafe.")
        if not os.access(active, os.W_OK | os.X_OK):
            raise RuntimeError("Theta active runtime is not writable.")
        if lib.exists() and not os.access(lib, os.W_OK | os.X_OK):
            raise RuntimeError("Theta active runtime library is not writable.")
        return jar

    if not _checked_regular_file(source_jar):
        raise FileNotFoundError("Theta bootstrap jar is missing.")

    staged = Path(tempfile.mkdtemp(prefix=".theta-bootstrap-", dir=root))
    staged.chmod(0o700)
    try:
        _stage_vendor(source_jar, staged)
        # Only rename a finished, restrictive workspace into the active path.
        # systemd runs a single Theta service, avoiding concurrent bootstraps.
        staged.rename(active)
    except BaseException:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return jar
