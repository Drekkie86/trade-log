from __future__ import annotations

import argparse
import json

from src.operations.release_retention import (
    DEFAULT_RELEASE_RETENTION,
    prune_release_directories,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prune old Christiania immutable release directories safely."
    )
    parser.add_argument(
        "--release-root",
        default="/opt/christiania-releases",
    )
    parser.add_argument(
        "--active-release",
        default="/opt/christiania",
    )
    parser.add_argument(
        "--retention",
        type=int,
        default=DEFAULT_RELEASE_RETENTION,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
    )
    parser.add_argument(
        "--json",
        action="store_true",
    )
    args = parser.parse_args()

    result = prune_release_directories(
        release_root=args.release_root,
        active_release=args.active_release,
        retention=args.retention,
        dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return

    print("Christiania release retention")
    print("------------------------------")
    print(f"Discovered: {result.discovered_release_count}")
    print(f"Retained: {result.retained_release_count}")
    print(f"Pruned: {result.pruned_release_count}")
    print(f"Pruned bytes: {result.pruned_bytes}")


if __name__ == "__main__":
    main()
