from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.dashboard.read_model import load_command_deck
from src.operations.audit_export import export_audit_snapshot
from src.operations.backup_recovery import inventory_backups, resolve_latest_valid_backup, run_restore_drill
from src.operations.sqlite_runtime import create_verified_backup
from src.operations.v1_readiness import assess_v1_readiness


def _print_json(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _deck(provider: bool) -> dict:
    return load_command_deck(include_provider_health=provider)


def main() -> int:
    parser = argparse.ArgumentParser(description="Christiania V1 operator control surface.")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.add_argument("--theta", action="store_true")
    status.add_argument("--json", action="store_true")

    readiness = sub.add_parser("readiness")
    readiness.add_argument("--runtime", action="store_true")
    readiness.add_argument("--json", action="store_true")

    backups = sub.add_parser("backups")
    backups.add_argument("--json", action="store_true")

    backup = sub.add_parser("backup")
    backup.add_argument("--json", action="store_true")

    drill = sub.add_parser("restore-drill")
    drill.add_argument("--backup", default=None)
    drill.add_argument("--json", action="store_true")

    export = sub.add_parser("export")
    export.add_argument("--theta", action="store_true")

    copenhagen = sub.add_parser("copenhagen")
    copenhagen.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.command == "status":
        deck = _deck(args.theta)
        if args.json:
            _print_json(deck)
        else:
            print("Christiania status")
            print("------------------")
            print(f"Deck ready: {deck.get('ready')}")
            print(f"Market: {deck.get('market_clock', {}).get('state')}")
            print(f"Daemon: {deck.get('daemon_health', {}).get('state')}")
            print(f"Theta: {deck.get('theta_health', {}).get('state')}")
            print(f"Prospective dates: {deck.get('prospective', {}).get('independent_dates', 0)}")
        return 0 if deck.get("ready") else 2

    if args.command == "readiness":
        deck = _deck(args.runtime)
        inventory = inventory_backups().as_dict()
        result = assess_v1_readiness(deck, inventory, require_runtime=args.runtime)
        if args.json:
            _print_json(result.as_dict())
        else:
            print(result.product_state)
            print(f"Scientific state: {result.scientific_state}")
            for check in result.checks:
                print(f"[{check.state}] {check.category}/{check.name}: {check.detail}")
        return 0 if result.product_ready else 2

    if args.command == "backups":
        result = inventory_backups()
        if args.json:
            _print_json(result.as_dict())
        else:
            print(f"Backup directory: {result.directory}")
            print(f"Valid: {result.valid_files}; invalid: {result.invalid_files}")
            print(f"Latest valid: {result.latest_valid_path or 'none'}")
            if result.latest_valid_age_hours is not None:
                print(f"Latest age: {result.latest_valid_age_hours:.1f}h")
        return 0 if result.valid_files else 2

    if args.command == "backup":
        result = create_verified_backup()
        if args.json:
            _print_json(result.as_dict())
        else:
            print(f"Created verified backup: {result.backup_path}")
        return 0

    if args.command == "restore-drill":
        source = Path(args.backup).expanduser() if args.backup else resolve_latest_valid_backup()
        result = run_restore_drill(source)
        if args.json:
            _print_json(result.as_dict())
        else:
            print("Restore drill PASSED")
            print(f"Source: {result.source_backup}")
            print(f"Schema: v{result.restored_schema_version}")
            print(f"Integrity: {result.integrity_check}")
        return 0

    if args.command == "export":
        path = export_audit_snapshot(include_provider_health=args.theta)
        print(path)
        return 0

    if args.command == "copenhagen":
        deck = _deck(True)
        inventory = inventory_backups().as_dict()
        readiness_result = assess_v1_readiness(deck, inventory, require_runtime=True)
        payload = {
            "gate": "COPENHAGEN_V1_RUNTIME_GATE",
            "product_readiness": readiness_result.as_dict(),
            "backup_inventory": inventory,
            "data_quality": deck.get("data_quality"),
            "science_note": "Scientific maturity remains separate from product/runtime readiness.",
        }
        if args.json:
            _print_json(payload)
        else:
            print(readiness_result.product_state)
            print(f"Scientific state: {readiness_result.scientific_state}")
            for check in readiness_result.checks:
                print(f"[{check.state}] {check.name}: {check.detail}")
        return 0 if readiness_result.product_ready else 2

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
