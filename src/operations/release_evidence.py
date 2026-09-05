from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from src.config import get_runtime_setting
from src.dashboard.read_model import load_command_deck
from src.operations.backup_recovery import inventory_backups
from src.operations.boot_identity import current_boot_id
from src.operations.burn_in import read_burn_in_samples, summarize_burn_in
from src.operations.release_manifest import build_release_manifest
from src.operations.secure_edge import inspect_secure_edge_configuration
from src.operations.v1_readiness import assess_v1_readiness


def resolve_release_evidence_dir(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    configured = get_runtime_setting("CHRISTIANIA_AUDIT_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "audit_exports"


def build_release_evidence() -> dict[str, object]:
    deck = load_command_deck(include_provider_health=True)
    backups = inventory_backups().as_dict()
    readiness = assess_v1_readiness(deck, backups, require_runtime=True)
    return {
        "kind": "CHRISTIANIA_V1_RELEASE_EVIDENCE",
        "created_at": datetime.now(UTC).isoformat(),
        "manifest": build_release_manifest().as_dict(),
        "product_readiness": readiness.as_dict(),
        "secure_edge": inspect_secure_edge_configuration().as_dict(),
        "burn_in": summarize_burn_in(read_burn_in_samples()).as_dict(),
        "current_boot_id": current_boot_id(),
        "backup_inventory": backups,
        "theta_timestamp_semantics": deck.get("theta_timestamp_semantics"),
        "science_note": "Release evidence is operational evidence, not proof of trading edge.",
    }


def export_release_evidence(path: str | Path | None = None) -> Path:
    directory = resolve_release_evidence_dir(path)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = directory / f"christiania_v1_release_evidence_{stamp}.json"
    target.write_text(json.dumps(build_release_evidence(), indent=2, sort_keys=True, default=str), encoding="utf-8")
    return target
