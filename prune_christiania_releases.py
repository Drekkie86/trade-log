from __future__ import annotations

import argparse
import json

from src.operations.release_retention import (
    DEFAULT_FAILED_RELEASE_MAX_BYTES,
    DEFAULT_FAILED_RELEASE_RETENTION,
    DEFAULT_RELEASE_RETENTION,
    prune_failed_release_directories,
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
    failed_result = prune_failed_release_directories(
        release_root=args.release_root,
        retention=DEFAULT_FAILED_RELEASE_RETENTION,
        max_bytes=DEFAULT_FAILED_RELEASE_MAX_BYTES,
        dry_run=args.dry_run,
    )

    if args.json:
        payload = result.as_dict()
        payload["failed_release_prune"] = (
            failed_result.as_dict()
        )
        print(
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
            )
        )
        return

    print("Christiania release retention")
    print("------------------------------")
    print(f"Discovered: {result.discovered_release_count}")
    print(f"Retained: {result.retained_release_count}")
    print(f"Pruned: {result.pruned_release_count}")
    print(f"Pruned bytes: {result.pruned_bytes}")
    print(
        "Failed quarantines retained: "
        f"{failed_result.retained_release_count}"
    )
    print(
        "Failed quarantines pruned: "
        f"{failed_result.pruned_release_count}"
    )
    print(
        "Failed quarantine bytes pruned: "
        f"{failed_result.pruned_bytes}"
    )


if __name__ == "__main__":
    main()
