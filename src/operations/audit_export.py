from __future__ import annotations

import json
import os
import subprocess
import tempfile
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from src.config import get_runtime_setting
from src.dashboard.read_model import load_command_deck
from src.operations.backup_recovery import inventory_backups_fast
from src.operations.v1_readiness import assess_v1_readiness


SAFE_CONFIGURATION_KEYS = (
    "CHRISTIANIA_DB_PATH",
    "CHRISTIANIA_BACKUP_DIR",
    "CHRISTIANIA_AUDIT_DIR",
    "CHRISTIANIA_THETA_BASE_URL",
    "CHRISTIANIA_THETA_JAR",
    "CHRISTIANIA_SYMBOLS",
)
SECRET_PRESENCE_KEYS = (
    "MASSIVE_API_KEY",
    "THETADATA_API_KEY",
    "OAUTH2_PROXY_CLIENT_SECRET",
    "OAUTH2_PROXY_COOKIE_SECRET",
)


def resolve_audit_dir(audit_dir: str | Path | None = None) -> Path:
    if audit_dir is not None:
        return Path(audit_dir).expanduser()
    configured = get_runtime_setting("CHRISTIANIA_AUDIT_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "audit_exports"


def _git_metadata() -> dict[str, object]:
    root = Path(__file__).resolve().parents[2]
    def capture(*args: str) -> str | None:
        cp = subprocess.run(args, cwd=root, text=True, capture_output=True, check=False)
        return cp.stdout.strip() if cp.returncode == 0 else None
    return {
        "commit_sha": capture("git", "rev-parse", "HEAD"),
        "commit_subject": capture("git", "log", "-1", "--pretty=%s"),
        "working_tree_clean": not bool(capture("git", "status", "--porcelain")),
    }


def _secret_values() -> tuple[str, ...]:
    values = []
    for key in SECRET_PRESENCE_KEYS:
        value = os.environ.get(key) or get_runtime_setting(key)
        if value:
            values.append(value)
    return tuple(sorted(set(values), key=len, reverse=True))


def _redact(value, secrets: tuple[str, ...]):
    if isinstance(value, str):
        result = value
        for secret in secrets:
            result = result.replace(secret, "[REDACTED_SECRET]")
        return result
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, secrets) for item in value)
    return value


def _audit_stage(name: str, operation):
    """Emit safe, flushed stage timings so a systemd timeout is attributable."""
    print(f"AUDIT_STAGE_START {name}", file=sys.stderr, flush=True)
    began = time.monotonic()
    try:
        return operation()
    finally:
        print(
            f"AUDIT_STAGE_FINISH {name} elapsed_ms={int((time.monotonic() - began)*1000)}",
            file=sys.stderr, flush=True,
        )


def build_audit_snapshot(*, include_provider_health: bool = False) -> dict[str, object]:
    deck = _audit_stage("command_deck", lambda: load_command_deck(
        include_provider_health=include_provider_health))
    # Deep inventory can re-open/verify EVERY large SQLite or compressed
    # backup and repeatedly exceeded the nightly reporting budget.
    # Verification is performed by the dedicated backup and restore controls.
    # Never relabel metadata-only entries as VALID: NOT_REVERIFIED is explicit.
    backups = _audit_stage("backup_metadata", lambda: inventory_backups_fast().as_dict())
    readiness = _audit_stage("readiness", lambda: assess_v1_readiness(deck, backups).as_dict())
    safe_config = {key: get_runtime_setting(key) for key in SAFE_CONFIGURATION_KEYS}
    secret_presence = {key: bool(os.environ.get(key) or get_runtime_setting(key)) for key in SECRET_PRESENCE_KEYS}
    payload = {
        "artifact": "CHRISTIANIA_V1_OPERATIONAL_AUDIT",
        "generated_at": datetime.now(UTC).isoformat(),
        "git": _git_metadata(),
        "configuration": safe_config,
        "secret_presence": secret_presence,
        "readiness": readiness,
        "backup_inventory": backups,
        "command_deck": deck,
        "disclaimer": "Operational/research audit only. No live-order capability or trading-readiness claim.",
    }
    return _redact(payload, _secret_values())


def export_audit_snapshot(
    audit_dir: str | Path | None = None,
    *,
    include_provider_health: bool = False,
) -> Path:
    directory = resolve_audit_dir(audit_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    final_path = directory / f"christiania_audit_{stamp}.json"
    if final_path.exists():
        raise FileExistsError("Audit export timestamp collision.")
    payload = build_audit_snapshot(include_provider_health=include_provider_health)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, prefix=".christiania_audit_", suffix=".tmp", delete=False) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    os.replace(temp_path, final_path)
    return final_path
