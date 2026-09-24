from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.config import load_runtime_env_file
from src.dashboard.read_model import load_command_deck
from src.operations.audit_export import export_audit_snapshot
from src.operations.archive_analytics import (
    read_archived_session_profile,
    verify_archive_session_parity,
)
from src.operations.archive_pruning import (
    plan_prune_session,
    prune_research_session,
)
from src.operations.backup_recovery import (
    inventory_backups,
    resolve_latest_valid_backup,
    resolve_restore_drill_backup,
    run_restore_drill,
)
from src.operations.backup_compression import maintain_compressed_backups
from src.operations.sqlite_runtime import create_verified_backup
from src.operations.storage_audit import audit_storage
from src.operations.prune_schema import (
    audit_prune_foreign_key_indexes,
)
from src.operations.remote_archive import (
    check_remote_bucket,
    inventory_remote_archive_proofs,
    upload_and_verify_remote_archive,
    verify_remote_archive_proof,
)
from src.operations.research_archive import (
    create_research_archive,
    find_archive_for_run,
    inventory_research_archives,
    maintain_research_archives,
    plan_archive_sessions,
    read_archived_run_evidence,
    verify_research_archive,
)
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

    archive_plan = sub.add_parser("archive-plan")
    archive_plan.add_argument("--keep-hot-runs", type=int, default=None)
    archive_plan.add_argument("--json", action="store_true")

    archive_inventory = sub.add_parser("archive-inventory")
    archive_inventory.add_argument("--json", action="store_true")

    archive_session = sub.add_parser("archive-session")
    archive_session.add_argument("--session-date", required=True)
    archive_session.add_argument("--keep-hot-runs", type=int, default=None)
    archive_session.add_argument("--json", action="store_true")

    archive_maintenance = sub.add_parser("archive-maintenance")
    archive_maintenance.add_argument("--keep-hot-runs", type=int, default=None)
    archive_maintenance.add_argument("--max-sessions", type=int, default=1)
    archive_maintenance.add_argument("--json", action="store_true")

    archive_find = sub.add_parser("archive-find-run")
    archive_find.add_argument("--run-id", type=int, required=True)
    archive_find.add_argument("--json", action="store_true")

    archive_read = sub.add_parser("archive-read-run")
    archive_read.add_argument("--run-id", type=int, required=True)
    archive_read.add_argument("--json", action="store_true")

    archive_profile = sub.add_parser(
        "archive-session-profile"
    )
    archive_profile.add_argument(
        "--session-date",
        required=True,
    )
    archive_profile.add_argument(
        "--json",
        action="store_true",
    )

    archive_parity = sub.add_parser(
        "archive-parity"
    )
    archive_parity.add_argument(
        "--session-date",
        required=True,
    )
    archive_parity.add_argument(
        "--json",
        action="store_true",
    )

    prune_index_audit = sub.add_parser(
        "archive-prune-index-audit"
    )
    prune_index_audit.add_argument(
        "--json",
        action="store_true",
    )

    archive_verify = sub.add_parser("archive-verify")
    archive_verify.add_argument("--manifest", required=True)
    archive_verify.add_argument("--deep", action="store_true")
    archive_verify.add_argument("--json", action="store_true")

    remote_check = sub.add_parser("archive-remote-check")
    remote_check.add_argument("--json", action="store_true")

    remote_upload = sub.add_parser("archive-remote-upload")
    remote_upload.add_argument("--manifest", required=True)
    remote_upload.add_argument("--json", action="store_true")

    remote_verify = sub.add_parser("archive-remote-verify")
    remote_verify.add_argument("--proof", required=True)
    remote_verify.add_argument("--json", action="store_true")

    remote_inventory = sub.add_parser("archive-remote-inventory")
    remote_inventory.add_argument("--json", action="store_true")

    prune_plan = sub.add_parser("archive-prune-plan")
    prune_plan.add_argument("--session-date", required=True)
    prune_plan.add_argument("--verify-remote", action="store_true")
    prune_plan.add_argument("--json", action="store_true")

    prune_session = sub.add_parser("archive-prune-session")
    prune_session.add_argument("--session-date", required=True)
    prune_session.add_argument("--confirm-session", required=True)
    prune_session.add_argument("--json", action="store_true")

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

    if args.command == "archive-plan":
        plan = plan_archive_sessions(
            keep_hot_runs=args.keep_hot_runs,
        )
        payload = [
            item.as_dict()
            for item in plan
        ]
        if args.json:
            _print_json(payload)
        else:
            for item in plan:
                print(
                    f"{item.session_date} "
                    f"runs={item.min_run_id}-{item.max_run_id} "
                    f"terminal={item.terminal_run_count} "
                    f"completed={item.completed_run_count} "
                    f"eligible={item.eligible} "
                    f"reason={item.reason}"
                )
        return 0

    if args.command == "archive-inventory":
        inventory = inventory_research_archives()
        if args.json:
            _print_json(inventory.as_dict())
        else:
            print(f"Archive directory: {inventory.directory}")
            print(f"Verified manifest count: {inventory.archive_count}")
            for manifest in inventory.manifests:
                print(
                    f"{manifest.session_date} "
                    f"runs={manifest.min_run_id}-{manifest.max_run_id} "
                    f"bytes={manifest.compressed_size_bytes} "
                    f"prune_eligible={manifest.prune_eligible}"
                )
            for invalid in inventory.invalid_manifests:
                print(f"INVALID: {invalid}", file=sys.stderr)
        return 0 if not inventory.invalid_manifests else 2

    if args.command == "archive-session":
        def archive_progress(message: str) -> None:
            print(
                f"[archive] {message}",
                file=sys.stderr,
                flush=True,
            )

        manifest = create_research_archive(
            args.session_date,
            keep_hot_runs=args.keep_hot_runs,
            progress=archive_progress,
        )
        if args.json:
            _print_json(manifest.as_dict())
        else:
            print(
                "Created verified research archive: "
                f"{manifest.archive_filename}"
            )
        return 0

    if args.command == "archive-maintenance":
        def archive_progress(message: str) -> None:
            print(
                f"[archive] {message}",
                file=sys.stderr,
                flush=True,
            )

        result = maintain_research_archives(
            keep_hot_runs=args.keep_hot_runs,
            max_sessions=args.max_sessions,
            progress=archive_progress,
        )
        if args.json:
            _print_json(result.as_dict())
        else:
            print(f"Archived sessions: {result.archived_count}")
            for session in result.archived_sessions:
                print(f"ARCHIVED {session}")
            for session in result.skipped_sessions:
                print(f"SKIPPED {session}")
        return 0

    if args.command == "archive-find-run":
        manifest = find_archive_for_run(
            args.run_id,
        )
        if manifest is None:
            if args.json:
                _print_json(
                    {
                        "run_id": args.run_id,
                        "archive": None,
                    }
                )
            else:
                print(
                    f"No research archive contains run {args.run_id}."
                )
            return 2

        if args.json:
            _print_json(manifest.as_dict())
        else:
            print(
                f"Run {args.run_id} -> "
                f"{manifest.archive_filename}"
            )
        return 0

    if args.command == "archive-read-run":
        result = read_archived_run_evidence(
            args.run_id,
        )
        if args.json:
            _print_json(result.as_dict())
        else:
            print(
                f"Archived run {result.run_id} "
                f"from {result.archive_filename}"
            )
            for table_name, count in result.table_counts.items():
                print(
                    f"{table_name}: {count}"
                )
        return 0

    if args.command == "archive-session-profile":
        def profile_progress(
            message: str,
        ) -> None:
            print(
                f"[archive-profile] {message}",
                file=sys.stderr,
                flush=True,
            )

        profile = (
            read_archived_session_profile(
                args.session_date,
                progress=profile_progress,
            )
        )

        if args.json:
            _print_json(
                profile.as_dict()
            )
        else:
            print(
                "Verified cold archive "
                "session profile"
            )
            print(
                f"Session: "
                f"{profile.session_date}"
            )
            print(
                "Runs: "
                + ",".join(
                    str(
                        value
                    )
                    for value
                    in profile.run_ids
                )
            )
            print(
                "Archive schema: v"
                f"{profile.archive_source_schema_version}"
            )
            print(
                "Option quote rows: "
                f"{profile.option_quote_universe['row_count']}"
            )
            print(
                "Underlyings: "
                f"{profile.option_quote_universe['underlying_count']}"
            )
            for (
                table_name,
                count,
            ) in profile.table_counts.items():
                print(
                    f"{table_name}: "
                    f"{count}"
                )
        return 0

    if args.command == "archive-parity":
        def parity_progress(
            message: str,
        ) -> None:
            print(
                f"[archive-parity] {message}",
                file=sys.stderr,
                flush=True,
            )

        receipt = (
            verify_archive_session_parity(
                args.session_date,
                progress=parity_progress,
            )
        )

        if args.json:
            _print_json(
                receipt.as_dict()
            )
        else:
            print(
                "Hot/cold content parity PASSED"
            )
            print(
                f"Session: "
                f"{receipt.session_date}"
            )
            print(
                f"State: "
                f"{receipt.state}"
            )
            print(
                "Archive source schema: "
                f"v{receipt.archive_source_schema_version}"
            )
            print(
                "Current schema: "
                f"v{receipt.current_schema_version}"
            )
            for (
                table_name,
                fingerprint,
            ) in receipt.hot_fingerprints.items():
                print(
                    f"{table_name}: "
                    f"rows={fingerprint.row_count} "
                    f"sha256="
                    f"{fingerprint.content_sha256}"
                )
        return 0

    if args.command == "archive-prune-index-audit":
        audit = (
            audit_prune_foreign_key_indexes()
        )

        if args.json:
            _print_json(
                audit.as_dict()
            )
        else:
            print(
                "Prune parent FK index audit"
            )
            print(
                "State: "
                + (
                    "PASS"
                    if audit.passed
                    else "FAIL"
                )
            )
            for item in audit.checks:
                print(
                    "["
                    + (
                        "PASS"
                        if item.passed
                        else "FAIL"
                    )
                    + "] "
                    + item.child_table
                    + "("
                    + ",".join(
                        item.child_columns
                    )
                    + ")->"
                    + item.parent_table
                    + " index="
                    + str(
                        item.supporting_index
                        or "NONE"
                    )
                )

        return (
            0
            if audit.passed
            else 2
        )

    if args.command == "archive-verify":
        manifest = verify_research_archive(
            args.manifest,
            deep_payload=args.deep,
        )
        if args.json:
            _print_json(manifest.as_dict())
        else:
            print("Research archive verification PASSED")
            print(f"Session: {manifest.session_date}")
            print(f"Archive: {manifest.archive_filename}")
            print(f"Deep payload: {args.deep}")
        return 0

    if args.command == "archive-remote-check":
        result = check_remote_bucket()
        if args.json:
            _print_json(result)
        else:
            print("Remote archive bucket check PASSED")
            print(f"Endpoint: {result['endpoint_url']}")
            print(f"Region: {result['region']}")
            print(f"Bucket: {result['bucket']}")
            print(f"Prefix: {result['prefix']}")
            print(f"Retention days: {result['retention_days']}")
            print("Object Lock: enabled")
        return 0

    if args.command == "archive-remote-upload":
        def remote_progress(message: str) -> None:
            print(
                f"[remote-archive] {message}",
                file=sys.stderr,
                flush=True,
            )

        proof = upload_and_verify_remote_archive(
            args.manifest,
            progress=remote_progress,
        )
        if args.json:
            _print_json(proof.as_dict())
        else:
            print("Off-host immutable archive verification PASSED")
            print(f"Session: {proof.session_date}")
            print(f"Bucket: {proof.bucket}")
            print(f"Archive key: {proof.archive_object.key}")
            print(f"Retention: {proof.archive_object.retain_until}")
            print(f"Gate: {proof.pruning_gate_state}")
        return 0

    if args.command == "archive-remote-verify":
        def remote_progress(message: str) -> None:
            print(
                f"[remote-archive] {message}",
                file=sys.stderr,
                flush=True,
            )

        proof = verify_remote_archive_proof(
            args.proof,
            progress=remote_progress,
        )
        if args.json:
            _print_json(proof.as_dict())
        else:
            print("Remote archive proof verification PASSED")
            print(f"Session: {proof.session_date}")
            print(f"Gate: {proof.pruning_gate_state}")
        return 0

    if args.command == "archive-remote-inventory":
        inventory = inventory_remote_archive_proofs()
        if args.json:
            _print_json(inventory.as_dict())
        else:
            print(f"Remote proofs: {inventory.proof_count}")
            for proof in inventory.proofs:
                print(
                    f"{proof.session_date} "
                    f"gate={proof.pruning_gate_state} "
                    f"retain_until={proof.archive_object.retain_until}"
                )
            for invalid in inventory.invalid_proofs:
                print(
                    f"INVALID: {invalid}",
                    file=sys.stderr,
                )
        return 0 if not inventory.invalid_proofs else 2

    if args.command == "archive-prune-plan":
        def prune_plan_progress(message: str) -> None:
            print(
                f"[prune-plan] {message}",
                file=sys.stderr,
                flush=True,
            )

        plan = plan_prune_session(
            args.session_date,
            verify_remote=args.verify_remote,
            progress=prune_plan_progress,
        )
        if args.json:
            _print_json(plan.as_dict())
        else:
            print(
                f"Session: {plan.session_date} "
                f"runs={plan.min_run_id}-{plan.max_run_id}"
            )
            print(
                f"Apply eligible: {plan.apply_eligible}"
            )
            print(
                f"Hot floor run: {plan.hot_floor_run_id}"
            )
            print(
                f"Remote gate: {plan.remote_gate_state}"
            )
            for item in plan.tables:
                print(
                    f"{item.table_name}: "
                    f"archived={item.archived_rows} "
                    f"deletable={item.deletable_rows} "
                    f"preserved={item.preserved_rows}"
                )
            for blocker in plan.blockers:
                print(
                    f"BLOCKER: {blocker}",
                    file=sys.stderr,
                )
        return 0 if plan.apply_eligible else 2

    if args.command == "archive-prune-session":
        def prune_progress(message: str) -> None:
            print(
                f"[prune] {message}",
                file=sys.stderr,
                flush=True,
            )

        receipt = prune_research_session(
            args.session_date,
            confirm_session=args.confirm_session,
            progress=prune_progress,
        )
        if args.json:
            _print_json(receipt.as_dict())
        else:
            print("Reference-aware hot pruning committed.")
            print(f"Session: {receipt.session_date}")
            print(
                f"Remote gate: {receipt.remote_gate_state}"
            )
            for table_name, count in receipt.rows_deleted.items():
                print(
                    f"{table_name}: deleted={count} "
                    f"preserved={receipt.rows_preserved[table_name]}"
                )
            print(
                f"Freelist before: {receipt.freelist_bytes_before} bytes"
            )
            print(
                f"Freelist after: {receipt.freelist_bytes_after} bytes"
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
