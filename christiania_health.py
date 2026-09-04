from __future__ import annotations

import argparse
import json

from src.dashboard.read_model import (
    load_command_deck,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Christiania operational health."
        )
    )
    parser.add_argument("--db", default=None)
    parser.add_argument(
        "--json",
        action="store_true",
    )
    args = parser.parse_args()

    snapshot = load_command_deck(
        args.db
    )

    if args.json:
        print(
            json.dumps(
                snapshot,
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 0 if snapshot["ready"] else 2

    db = snapshot["database"]

    print("Christiania operational health")
    print("------------------------------")
    print(f"Database: {db['path']}")
    print(
        f"Schema: {db['schema_version']} "
        f"(expected {db['expected_schema_version']})"
    )
    print(
        f"Journal mode: {db['journal_mode']}"
    )
    print(
        f"Quick check: {db['quick_check']}"
    )
    print(
        "Foreign-key violations: "
        f"{db['foreign_key_violation_count']}"
    )
    print(
        f"Dashboard ready: {snapshot['ready']}"
    )

    if not snapshot["ready"]:
        print(f"Reason: {snapshot['reason']}")
        return 2

    latest = snapshot["latest_iteration"]

    if latest:
        print(
            "Latest daemon iteration: "
            f"#{latest['id']} {latest['status']} "
            f"scheduled {latest['scheduled_for']}"
        )
    else:
        print(
            "Latest daemon iteration: none"
        )

    prospective = snapshot["prospective"]
    print(
        "Prospective dates: "
        f"{prospective['independent_dates']}"
    )
    print(
        "Recovered underlying samples: "
        f"{prospective['recovered_samples']}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
