"""Durable daemon restart obligation across separate Theta recovery attempts.

Intent is recorded before recovery deliberately stops a running daemon.
An intentionally stopped daemon without this marker must not be started.
"""
from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path

from src.operations.audit_export import resolve_audit_dir

RESTART_INTENT_FILENAME = "theta_daemon_restart_pending.json"


def _path(audit_dir: Path | None) -> Path:
    return (resolve_audit_dir() if audit_dir is None else Path(audit_dir)) / RESTART_INTENT_FILENAME


def _sync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def restart_intent_pending(audit_dir: Path | None = None) -> bool:
    path = _path(audit_dir)
    if not path.exists():
        return False
    # Do not silently ignore corrupted restart obligations.
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("intent") != "RESTART_RESEARCH_DAEMON_AFTER_THETA":
        raise RuntimeError("Invalid persisted Theta daemon restart obligation.")
    return True


def remember_daemon_restart(*, reason: str, audit_dir: Path | None = None) -> None:
    """Durably record intent before issuing systemctl stop."""
    path = _path(audit_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if restart_intent_pending(audit_dir):
        return  # Preserve the original incident that stopped the daemon.
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    payload = {
        "intent": "RESTART_RESEARCH_DAEMON_AFTER_THETA",
        "reason": reason,
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def clear_daemon_restart(*, audit_dir: Path | None = None) -> None:
    """Clear only after systemctl start confirms success."""
    path = _path(audit_dir)
    if path.exists():
        # Revalidate before deletion to avoid losing an unknown state file.
        restart_intent_pending(audit_dir)
        path.unlink()
        _sync_directory(path.parent)
