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
    parser.add_argument(
        "--strict-daemon",
        action="store_true",
        help=(
            "Also require a live daemon lease with a recent heartbeat."
        ),
    )
    args = parser.parse_args()

    snapshot = load_command_deck(
        args.db
    )

    strict_daemon_failed = (
        args.strict_daemon
        and snapshot.get("ready") is True
        and snapshot.get("daemon_health", {}).get("state") != "HEALTHY"
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
        if not snapshot["ready"]:
            return 2
        if strict_daemon_failed:
            return 3
        return 0

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

    market_clock = snapshot.get("market_clock", {})
    print(
        "Market clock: "
        f"{market_clock.get('state')}"
    )
    print(
        "Next sample: "
        f"{market_clock.get('next_sample_at')}"
    )

    if not snapshot["ready"]:
        print(f"Reason: {snapshot['reason']}")
        return 2

    daemon_health = snapshot.get(
        "daemon_health", {}
    )
    print(
        "Daemon health: "
        f"{daemon_health.get('state')}"
    )

    if strict_daemon_failed:
        return 3

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
