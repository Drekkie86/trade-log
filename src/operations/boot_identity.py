from __future__ import annotations

import os
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.config import get_runtime_setting

DEFAULT_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


@dataclass(frozen=True)
class BootMarker:
    boot_id: str
    recorded_at: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def current_boot_id(path: str | Path | None = None) -> str:
    override = os.environ.get("CHRISTIANIA_BOOT_ID_OVERRIDE")
    if override:
        return override.strip()
    target = DEFAULT_BOOT_ID_PATH if path is None else Path(path)
    if target.is_file():
        value = target.read_text(encoding="utf-8").strip()
        if value:
            return value
    # Windows/local development fallback: stable only for the process invocation,
    # never accepted as production reboot proof.
    return f"UNAVAILABLE:{uuid.uuid4()}"


def resolve_boot_marker_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    configured = get_runtime_setting("CHRISTIANIA_BOOT_MARKER_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "audit_exports" / "v1_boot_marker.json"


def write_boot_marker(path: str | Path | None = None, *, boot_id: str | None = None) -> BootMarker:
    marker = BootMarker(
        boot_id=boot_id or current_boot_id(),
        recorded_at=datetime.now(UTC).isoformat(),
    )
    target = resolve_boot_marker_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    import json
    target.write_text(json.dumps(marker.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return marker


def read_boot_marker(path: str | Path | None = None) -> BootMarker:
    import json
    target = resolve_boot_marker_path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    return BootMarker(boot_id=str(payload["boot_id"]), recorded_at=str(payload["recorded_at"]))


def reboot_proven(previous: BootMarker, *, current: str | None = None) -> bool:
    now = current or current_boot_id()
    return (
        not previous.boot_id.startswith("UNAVAILABLE:")
        and not now.startswith("UNAVAILABLE:")
        and previous.boot_id != now
    )
