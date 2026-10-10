from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.sqlite_runtime import inspect_database
from src.quant.registry import catalog
from src.version import CHRISTIANIA_VERSION, RELEASE_CHANNEL

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "migrations"


@dataclass(frozen=True)
class ReleaseManifest:
    version: str
    release_channel: str
    git_sha: str | None
    git_clean: bool | None
    schema_version: int | None
    expected_schema_version: int
    migration_chain_sha256: str
    quant_registry_sha256: str
    python_version: str
    platform: str
    dependencies: dict[str, str | None]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _git(*args: str) -> tuple[int, str]:
    cp = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False,
    )
    return cp.returncode, cp.stdout.strip()


def _chain_hash(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for path in paths:
        h.update(path.name.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _registry_hash() -> str:
    payload = json.dumps(catalog(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dependency_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def read_deployed_commit(
    path: str | Path = "/opt/christiania/DEPLOYED_COMMIT",
) -> str | None:
    """The release receiver's authoritative, immutable SHA marker.

    A missing/malformed marker is *unknown*, never a dirty Git checkout.
    Reading this file does not invoke Git or inspect the database.
    """
    try:
        candidate = Path(path).read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    if len(candidate) != 40 or any(c not in "0123456789abcdef" for c in candidate):
        return None
    return candidate


def build_release_manifest(
    db_path: str | Path | None = None,
    *,
    deep_integrity: bool = True,
) -> ReleaseManifest:
    rc, sha = _git("rev-parse", "HEAD")
    rc_status, status = _git("status", "--porcelain")
    # Release/deployment checks retain strict validation by default.
    # Interactive operator views may request only schema metadata; deep
    # integrity and FK verification are expensive on the production DB.
    health = inspect_database(db_path, deep_integrity=deep_integrity)
    migrations = sorted(MIGRATIONS.glob("*.sql"))
    return ReleaseManifest(
        version=CHRISTIANIA_VERSION,
        release_channel=RELEASE_CHANNEL,
        git_sha=sha if rc == 0 else None,
        git_clean=(not status) if rc_status == 0 else None,
        schema_version=health.schema_version,
        expected_schema_version=EXPECTED_SCHEMA_VERSION,
        migration_chain_sha256=_chain_hash(migrations),
        quant_registry_sha256=_registry_hash(),
        python_version=platform.python_version(),
        platform=platform.platform(),
        dependencies={
            "numpy": _dependency_version("numpy"),
            "scipy": _dependency_version("scipy"),
            "streamlit": _dependency_version("streamlit"),
            "exchange_calendars": _dependency_version("exchange_calendars"),
            "requests": _dependency_version("requests"),
        },
    )
