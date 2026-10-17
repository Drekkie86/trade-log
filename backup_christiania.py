from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from src.config import load_runtime_env_file
from src.operations.backup_policy import (
    evaluate_backup_due,
)
from src.operations.sqlite_runtime import (
    create_verified_backup,
    resolve_backup_dir,
)
from src.operations.backup_compression import (
    backup_data_files,
    compress_verified_backup,
)
from src.operations.backup_verification import evidence_path_for


DEFAULT_RUNTIME_ENV_FILE = Path(
    "/etc/christiania/christiania.env"
)


def compress_pending_routine_backup(
    backup_dir: str | Path | None,
):
    """Finish one interrupted verified routine backup before another copy.

    Only files with explicit new routine evidence qualify; old unmanifested
    plaintext copies are never reswept with full integrity_check here.
    Compression proves the source SHA and its gzip roundtrip before deleting
    the *same* plaintext copy; independent older backups remain untouched.
    """
    directory = resolve_backup_dir(backup_dir)
    candidates = sorted(
        (
            p for p in backup_data_files(directory)
            if p.name.endswith(".db") and evidence_path_for(p).is_file()
        ),
        key=lambda p: p.name,
        reverse=True,
    )
    if not candidates:
        return None
    return compress_verified_backup(candidates[0])


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create a verified online SQLite backup "
            "of Christiania."
        )
    )
    parser.add_argument("--db", default=None)
    parser.add_argument(
        "--backup-dir",
        default=None,
    )
    parser.add_argument(
        "--retention",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--json",
        action="store_true",
    )
    parser.add_argument(
        "--compress-after",
        action="store_true",
        help="Complete any pending routine compression, then compress a new recovery immediately.",
    )
    parser.add_argument(
        "--cleanup-stale-temp",
        action="store_true",
        help=(
            "Remove only incomplete Christiania backup temp files "
            "from the configured backup directory and exit."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Create a full verified recovery point even when the "
            "evidence-aware policy says no new backup is due."
        ),
    )

    args = parser.parse_args()

    if DEFAULT_RUNTIME_ENV_FILE.is_file():
        load_runtime_env_file(
            DEFAULT_RUNTIME_ENV_FILE,
            overwrite=False,
        )

    if args.cleanup_stale_temp:
        directory = resolve_backup_dir(
            args.backup_dir
        )
        removed = []
        if directory.exists():
            for pattern in (
                ".christiania_backup_*.tmp.db",
                ".christiania_backup_*.tmp.db-journal",
                ".christiania_backup_*.tmp.db-wal",
                ".christiania_backup_*.tmp.db-shm",
            ):
                for path in directory.glob(pattern):
                    if path.is_file():
                        path.unlink()
                        removed.append(
                            str(path)
                        )

        payload = {
            "state": "CLEANED",
            "backup_dir": str(directory),
            "removed_count": len(removed),
            "removed": sorted(removed),
        }
        if args.json:
            print(
                json.dumps(
                    payload,
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(
                "Christiania stale backup temp cleanup complete"
            )
            print(
                "Removed: "
                f"{len(removed)}"
            )
        return

    pending_compression = None
    if args.compress_after:
        # Fail closed on a failed predecessor before committing another 30 GiB
        # snapshot. Never trigger an expensive full scan of legacy backups.
        pending_compression = compress_pending_routine_backup(args.backup_dir)
        if pending_compression is not None:
            print(
                "Prior routine backup compression recovered: "
                f"{pending_compression.compressed_path}",
                file=sys.stderr, flush=True,
            )

    decision = evaluate_backup_due(
        db_path=args.db,
        backup_dir=args.backup_dir,
    )

    if not args.force and not decision.due:
        payload = {
            "state": "SKIPPED",
            "decision": decision.as_dict(),
        }
        if pending_compression is not None:
            payload["compression"] = pending_compression.as_dict()

        if args.json:
            print(
                json.dumps(
                    payload,
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(
                "Christiania backup skipped"
            )
            print(
                "--------------------------"
            )
            print(
                f"Reason: {decision.reason}"
            )
            print(
                "Latest recovery point: "
                f"{decision.latest_backup_path or 'none'}"
            )
            print(
                "Latest completed research: "
                f"{decision.latest_completed_research_at or 'none'}"
            )
        return

    print(
        "Starting Christiania verified SQLite backup...",
        file=sys.stderr,
        flush=True,
    )
    print(
        "Backup decision: "
        f"{'FORCED' if args.force else decision.reason}",
        file=sys.stderr,
        flush=True,
    )

    def progress(message: str) -> None:
        print(
            f"[backup] {message}",
            file=sys.stderr,
            flush=True,
        )

    result = create_verified_backup(
        db_path=args.db,
        backup_dir=args.backup_dir,
        retention=args.retention,
        progress=progress,
    )

    print(
        f"Routine backup promoted: {result.backup_path}",
        file=sys.stderr,
        flush=True,
    )
    compression = None
    if args.compress_after:
        # Compressed proof must pass source SHA, gzip bytes and payload SHA.
        # Failure leaves the new plaintext copy and all older recovery points.
        compression = compress_verified_backup(result.backup_path)
        print(
            f"Routine recovery compressed and verified: {compression.compressed_path}",
            file=sys.stderr, flush=True,
        )

    if args.json:
        payload = {
            "state": "CREATED_AND_COMPRESSED" if compression else "CREATED",
            "decision": decision.as_dict(),
            "backup": result.as_dict(),
        }
        if compression is not None:
            payload["compression"] = compression.as_dict()
        print(
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
            )
        )
        return

    print("Christiania backup complete")
    print("----------------------------")
    print(f"Source: {result.source_path}")
    print(f"Backup: {result.backup_path}")
    print(f"Schema: v{result.schema_version}")
    print(
        f"Verification level: {getattr(result, 'verification_level', 'unknown')}; "
        f"quick_check: {getattr(result, 'quick_check', None)}; "
        f"full integrity_check: {result.integrity_check}"
    )
    if compression is not None:
        print(f"Compressed recovery: {compression.compressed_path}")
    print(
        "Foreign-key violations: "
        f"{result.foreign_key_violation_count}"
    )
    print(
        f"Old backups pruned: {result.pruned_count}"
    )


if __name__ == "__main__":
    main()
