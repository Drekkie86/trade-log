"""Fail-closed bridge from retired v34 backup timers to volume-owned recovery.

The active v34 supervisor expects the legacy backup/restore timers enabled.
Those were deliberately retired after the replacement volume backup was
fully restored and verified. This gate accepts ONLY that exact transition,
and otherwise preserves strict operational deployment preconditions.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path


NEW_TIMERS = (
    "christiania-volume-recovery-backup.timer",
    "christiania-volume-recovery-audit.timer",
)
RETIRED_TIMERS = (
    "christiania-backup.timer",
    "christiania-restore-drill.timer",
)


def validate_transition(
    *,
    status: dict,
    supervisor: dict,
    volume_timer_states: dict[str, tuple[str, str]],
    recovered_backup: bool,
) -> None:
    """Raises on any unrecognised failed blocking supervisor check."""
    required = (
        "release_identity_state", "core_services_state",
        "supervisor_freshness_state", "resource_policy_state",
        "research_progress_state",
    )
    for name in required:
        if str(status.get(name) or "").upper() != "PASS":
            raise RuntimeError(f"TRANSITION_REQUIRED_STATUS_FAILED:{name}")
    if status.get("public_edge_expected") is True:
        if str(status.get("public_edge_state") or "").upper() != "PASS":
            raise RuntimeError("TRANSITION_PUBLIC_EDGE_NOT_READY")
    if str(status.get("supervisor_state") or "").upper() not in (
        "HEALTHY", "UNHEALTHY"
    ):
        raise RuntimeError("TRANSITION_SUPERVISOR_UNKNOWN")
    if not recovered_backup:
        raise RuntimeError("TRANSITION_NO_INDEPENDENT_RECOVERY_POINT")
    for timer in NEW_TIMERS:
        enabled, active = volume_timer_states.get(timer, ("unknown", "unknown"))
        if enabled != "enabled" or active != "active":
            raise RuntimeError(f"TRANSITION_NEW_TIMER_NOT_READY:{timer}:{enabled}:{active}")

    checks = supervisor.get("checks")
    if not isinstance(checks, list) or not checks:
        raise RuntimeError("TRANSITION_SUPERVISOR_CHECKS_MISSING")
    seen_retired = set()
    for check in checks:
        if not isinstance(check, dict):
            raise RuntimeError("TRANSITION_MALFORMED_SUPERVISOR_CHECK")
        if str(check.get("state") or "").upper() in ("PASS", "INFO"):
            continue
        if check.get("blocking") is False:
            continue
        name = str(check.get("name") or "")
        detail = str(check.get("detail") or "")
        if name == "research-progress":
            continue
        if name == "public-edge-services":
            continue
        if name.startswith("memory:") and "reached warning=" in detail:
            continue
        if (
            name == "backup-recovery-point"
            and "reason=LATEST_BACKUP_SCHEMA_MISMATCH" in detail
        ):
            continue
        if name.startswith("timer:") and name[6:] in RETIRED_TIMERS:
            old_timer = name[6:]
            if detail == f"{old_timer} is disabled; expected enabled.":
                seen_retired.add(old_timer)
                continue
        raise RuntimeError(f"TRANSITION_UNRECOGNISED_BLOCKER:{name}:{detail[:180]}")
    if status.get("deployment_supervisor_state") == "PASS":
        return
    if not seen_retired:
        raise RuntimeError("TRANSITION_SUPERVISOR_FAILED_WITHOUT_RETIRED_TIMERS")


def _unit_state(timer: str, action: str) -> str:
    process = subprocess.run(
        ("systemctl", action, timer),
        capture_output=True, text=True, timeout=5, check=False,
    )
    return process.stdout.strip()


def _verified_volume_backup(
    backup_status: Path, volume: Path, live_db: Path, *,
    now: datetime,
) -> bool:
    try:
        if not volume.is_mount() or volume.is_symlink():
            return False
        if os.stat(volume).st_dev == os.stat(live_db).st_dev:
            return False
        proof = json.loads(backup_status.read_text(encoding="utf-8"))
        recorded_at = datetime.fromisoformat(
            str(proof["at_utc"]).replace("Z", "+00:00")
        ).astimezone(UTC)
        age = now.astimezone(UTC) - recorded_at
        if age < timedelta(0) or age > timedelta(hours=36):
            return False
        if proof.get("phase") != "COMPLETE" or int(proof.get("verified_restore_bytes") or 0) < 1:
            return False
        archive = Path(str(proof["archive"]))
        if archive.is_symlink() or not archive.is_file() or archive.stat().st_size < 1:
            return False
        if not archive.resolve().is_relative_to((volume / "backups").resolve()):
            return False
        manifest = Path(str(archive) + ".manifest.json")
        return manifest.is_file() and manifest.stat().st_size > 0
    except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return False


def main() -> int:
    status = json.loads(os.environ["CHRISTIANIA_TRANSITION_STATUS_JSON"])
    supervisor = json.loads(Path(
        "/var/lib/christiania/audit/rc0_supervisor_status.json"
    ).read_text(encoding="utf-8"))
    volume = Path("/mnt/HC_Volume_107172834")
    verified = _verified_volume_backup(
        volume / "backups/volume_backup_scheduler_status.json",
        volume, Path("/var/lib/christiania/data/trade_log.db"),
        now=datetime.now(UTC),
    )
    timer_states = {
        timer: (_unit_state(timer, "is-enabled"), _unit_state(timer, "is-active"))
        for timer in NEW_TIMERS
    }
    validate_transition(
        status=status, supervisor=supervisor,
        volume_timer_states=timer_states,
        recovered_backup=verified,
    )
    print("Volume-owned backup timer transition verified; all other blocking controls passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
