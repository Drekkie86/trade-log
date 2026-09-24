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


DEFAULT_RUNTIME_ENV_FILE = Path(
    "/etc/christiania/christiania.env"
)


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

    decision = evaluate_backup_due(
        db_path=args.db,
        backup_dir=args.backup_dir,
    )

    if not args.force and not decision.due:
        payload = {
            "state": "SKIPPED",
            "decision": decision.as_dict(),
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
        f"Verified backup promoted: {result.backup_path}",
        file=sys.stderr,
        flush=True,
    )

    if args.json:
        payload = {
            "state": "CREATED",
            "decision": decision.as_dict(),
            "backup": result.as_dict(),
        }
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
        f"Integrity: {result.integrity_check}"
    )
    print(
        "Foreign-key violations: "
        f"{result.foreign_key_violation_count}"
    )
    print(
        f"Old backups pruned: {result.pruned_count}"
    )


if __name__ == "__main__":
    main()
