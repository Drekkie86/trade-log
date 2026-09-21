from __future__ import annotations

import argparse
import json
import sys

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

    args = parser.parse_args()

    print(
        "Starting Christiania verified SQLite backup...",
        file=sys.stderr,
        flush=True,
    )

    result = create_verified_backup(
        db_path=args.db,
        backup_dir=args.backup_dir,
        retention=args.retention,
    )

    print(
        f"Verified backup promoted: {result.backup_path}",
        file=sys.stderr,
        flush=True,
    )

    if args.json:
        payload = result.as_dict()
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
