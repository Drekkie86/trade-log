from __future__ import annotations

import argparse
import json

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

    result = create_verified_backup(
        db_path=args.db,
        backup_dir=args.backup_dir,
        retention=args.retention,
    )

    if args.json:
        print(
            json.dumps(
                result.as_dict(),
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
