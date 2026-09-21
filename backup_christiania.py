from __future__ import annotations

import argparse
import json
import sys

from src.operations.backup_policy import (
    evaluate_backup_due,
)
from src.operations.sqlite_runtime import (
    create_verified_backup,
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
        "--force",
        action="store_true",
        help=(
            "Create a full verified recovery point even when the "
            "evidence-aware policy says no new backup is due."
        ),
    )

    args = parser.parse_args()

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
