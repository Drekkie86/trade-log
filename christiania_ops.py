from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.config import load_runtime_env_file
from src.dashboard.read_model import load_command_deck
from src.operations.audit_export import export_audit_snapshot
from src.operations.backup_recovery import (
    inventory_backups,
    resolve_latest_valid_backup,
    resolve_restore_drill_backup,
    run_restore_drill,
)
from src.operations.backup_compression import maintain_compressed_backups
from src.operations.sqlite_runtime import create_verified_backup
from src.operations.storage_audit import audit_storage
from src.operations.v1_readiness import assess_v1_readiness
from src.operations.secure_edge import inspect_secure_edge_configuration


DEPLOYMENT_ENV_FILE = Path(
    "/etc/christiania/christiania.env"
)


def _load_deployment_env_if_present() -> None:
    if DEPLOYMENT_ENV_FILE.is_file():
        load_runtime_env_file(
            DEPLOYMENT_ENV_FILE,
            overwrite=False,
        )


def _print_json(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _deck(provider: bool) -> dict:
    return load_command_deck(include_provider_health=provider)


def main() -> int:
    _load_deployment_env_if_present()

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

    compress_backups = sub.add_parser("compress-backups")
    compress_backups.add_argument("--json", action="store_true")
    compress_backups.add_argument(
        "--max-files",
        type=int,
        default=1,
        help=(
            "Maximum number of older verified backups to compress "
            "during this invocation. Defaults to 1."
        ),
    )

    drill = sub.add_parser("restore-drill")
    drill.add_argument("--backup", default=None)
    drill.add_argument("--json", action="store_true")

    export = sub.add_parser("export")
    export.add_argument("--theta", action="store_true")

    edge = sub.add_parser("secure-edge")
    edge.add_argument("--json", action="store_true")

    storage = sub.add_parser("storage-audit")
    storage.add_argument("--json", action="store_true")

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

    if args.command == "compress-backups":
        from src.operations.sqlite_runtime import resolve_backup_dir

        compression = maintain_compressed_backups(
            resolve_backup_dir(),
            keep_latest_uncompressed=1,
            max_compressions=args.max_files,
        )
        if args.json:
            _print_json(compression.as_dict())
        else:
            print(
                "Compressed retained backups: "
                f"{compression.compressed_count}"
            )
            print(
                "Bytes reclaimed: "
                f"{compression.reclaimed_bytes}"
            )
        return 0

    if args.command == "restore-drill":
        source = (
            Path(args.backup).expanduser()
            if args.backup
            else resolve_restore_drill_backup()
        )
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

    if args.command == "secure-edge":
        edge = inspect_secure_edge_configuration()
        if args.json:
            _print_json(edge.as_dict())
        else:
            print("Christiania secure web edge")
            print("---------------------------")
            for check in edge.checks:
                print(f"[{check.state}] {check.name}: {check.detail}")
        return 0 if edge.ready else 2

    if args.command == "storage-audit":
        def storage_progress(message: str) -> None:
            print(
                f"[storage-audit] {message}",
                file=sys.stderr,
                flush=True,
            )

        result = audit_storage(
            progress=storage_progress,
        )
        if args.json:
            _print_json(result.as_dict())
        else:
            print(f"Database: {result.database_path}")
            print(f"Size: {result.database_size_bytes} bytes")
            print(f"Freelist: {result.freelist_bytes} bytes")
            print("Largest SQLite objects:")
            for item in result.objects[:25]:
                print(
                    f"{item.bytes:>14}  "
                    f"{item.object_type:<8}  "
                    f"{item.name}"
                )
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
