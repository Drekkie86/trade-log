from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from src.dashboard.read_model import load_command_deck
from src.operations.backup_recovery import inventory_backups, resolve_latest_valid_backup, run_restore_drill
from src.operations.boot_identity import current_boot_id, read_boot_marker, reboot_proven, write_boot_marker
from src.operations.burn_in import BurnInSample, append_burn_in_sample, read_burn_in_samples, summarize_burn_in
from src.operations.release_acceptance import assess_release_candidate
from src.operations.release_manifest import build_release_manifest
from src.operations.release_evidence import export_release_evidence
from src.operations.secure_edge import inspect_secure_edge_configuration
from src.operations.v1_readiness import assess_v1_readiness
from src.version import CHRISTIANIA_VERSION


def _json(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _timestamp_confidence(deck: dict) -> str | None:
    rows = deck.get("theta_timestamp_semantics") or []
    if isinstance(rows, list) and rows:
        return rows[0].get("confidence_state")
    if isinstance(rows, dict):
        return rows.get("confidence_state")
    return None


def _runtime_snapshot() -> tuple[dict, dict, object]:
    deck = load_command_deck(include_provider_health=True)
    backups = inventory_backups().as_dict()
    readiness = assess_v1_readiness(deck, backups, require_runtime=True)
    return deck, backups, readiness


def main() -> int:
    parser = argparse.ArgumentParser(description="Christiania V1 release-candidate control surface.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version")
    manifest = sub.add_parser("manifest")
    manifest.add_argument("--json", action="store_true")

    burn = sub.add_parser("burn-in-sample")
    burn.add_argument("--json", action="store_true")

    report = sub.add_parser("burn-in-report")
    report.add_argument("--hours", type=float, default=72.0)
    report.add_argument("--json", action="store_true")

    mark = sub.add_parser("mark-boot")
    mark.add_argument("--json", action="store_true")

    verify = sub.add_parser("verify-reboot")
    verify.add_argument("--json", action="store_true")

    evidence = sub.add_parser("evidence")
    evidence.add_argument("--json", action="store_true")

    gate = sub.add_parser("rc-gate")
    gate.add_argument("--burn-in-hours", type=float, default=72.0)
    gate.add_argument("--allow-pending-burn-in", action="store_true")
    gate.add_argument("--allow-pending-reboot", action="store_true")
    gate.add_argument("--allow-pending-timestamp-validation", action="store_true")
    gate.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.command == "version":
        print(CHRISTIANIA_VERSION)
        return 0

    if args.command == "manifest":
        result = build_release_manifest()
        _json(result.as_dict()) if args.json else print(f"Christiania {result.version} {result.git_sha or 'NO_GIT'} clean={result.git_clean}")
        return 0 if result.git_clean is not False else 2

    if args.command == "burn-in-sample":
        deck, backups, _ = _runtime_snapshot()
        latest = deck.get("latest_iteration") or {}
        sample = BurnInSample(
            observed_at=datetime.now(UTC).isoformat(),
            boot_id=current_boot_id(),
            database_ready=deck.get("ready") is True,
            daemon_state=str((deck.get("daemon_health") or {}).get("state", "UNKNOWN")),
            theta_state=str((deck.get("theta_health") or {}).get("state", "UNKNOWN")),
            backup_valid=int(backups.get("valid_files", 0) or 0) > 0,
            market_state=(deck.get("market_clock") or {}).get("state"),
            latest_iteration_status=latest.get("status") if isinstance(latest, dict) else None,
        )
        path = append_burn_in_sample(sample)
        if args.json:
            _json({"path": str(path), "sample": sample.as_dict()})
        else:
            print(path)
        return 0

    if args.command == "burn-in-report":
        result = summarize_burn_in(read_burn_in_samples(), required_hours=args.hours)
        _json(result.as_dict()) if args.json else print(f"{result.state}: {result.sample_count} samples, {result.duration_hours:.1f}h")
        return 0 if result.state == "PASSED" else 2

    if args.command == "mark-boot":
        marker = write_boot_marker()
        _json(marker.as_dict()) if args.json else print(f"Recorded boot id: {marker.boot_id}")
        return 0

    if args.command == "verify-reboot":
        marker = read_boot_marker()
        current = current_boot_id()
        passed = reboot_proven(marker, current=current)
        payload = {"previous_boot_id": marker.boot_id, "current_boot_id": current, "reboot_proven": passed}
        _json(payload) if args.json else print("REBOOT_PROVEN" if passed else "REBOOT_NOT_PROVEN")
        return 0 if passed else 2

    if args.command == "evidence":
        path = export_release_evidence()
        if args.json:
            _json({"path": str(path)})
        else:
            print(path)
        return 0

    if args.command == "rc-gate":
        deck, backups, readiness = _runtime_snapshot()
        edge = inspect_secure_edge_configuration()
        manifest_obj = build_release_manifest()
        burn = summarize_burn_in(read_burn_in_samples(), required_hours=args.burn_in_hours)
        try:
            restore = run_restore_drill(resolve_latest_valid_backup())
            restore_ok = restore.state == "PASSED"
        except Exception:
            restore_ok = False
        try:
            marker = read_boot_marker()
            reboot_ok = reboot_proven(marker)
        except Exception:
            reboot_ok = False

        result = assess_release_candidate(
            product_ready=readiness.product_ready,
            runtime_ready=(
                (deck.get("daemon_health") or {}).get("state") == "HEALTHY"
                and (deck.get("theta_health") or {}).get("ready") is True
            ),
            secure_edge_ready=edge.ready,
            restore_drill_passed=restore_ok,
            release_manifest_clean=manifest_obj.git_clean is True,
            burn_in_state=burn.state,
            reboot_proven=reboot_ok,
            theta_timestamp_confidence=_timestamp_confidence(deck),
            require_burn_in=not args.allow_pending_burn_in,
            require_reboot=not args.allow_pending_reboot,
            require_live_timestamp_validation=not args.allow_pending_timestamp_validation,
        )
        payload = result.as_dict() | {
            "burn_in": burn.as_dict(),
            "secure_edge": edge.as_dict(),
            "product_readiness": readiness.as_dict(),
        }
        _json(payload) if args.json else print(result.state)
        return 0 if result.release_candidate_ready else 2

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
