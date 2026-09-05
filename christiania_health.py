from __future__ import annotations

import argparse
import json

from src.dashboard.read_model import (
    load_command_deck,
)
from src.operations.backup_recovery import (
    inventory_backups,
)
from src.operations.v1_readiness import (
    BACKUP_MAX_AGE_HOURS,
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
        "--strict-theta",
        action="store_true",
        help=(
            "Also require the local Theta Terminal v3 API to be ready."
        ),
    )
    parser.add_argument(
        "--strict-daemon",
        action="store_true",
        help=(
            "Also require a live daemon lease with a recent heartbeat."
        ),
    )
    parser.add_argument(
        "--strict-backup",
        action="store_true",
        help=(
            "Also require a verified backup no older than "
            f"{BACKUP_MAX_AGE_HOURS:.0f} hours."
        ),
    )
    args = parser.parse_args()

    snapshot = load_command_deck(
        args.db,
        include_provider_health=True,
    )

    strict_theta_failed = (
        args.strict_theta
        and snapshot.get("ready") is True
        and snapshot.get("theta_health", {}).get("state") != "READY"
    )

    strict_daemon_failed = (
        args.strict_daemon
        and snapshot.get("ready") is True
        and snapshot.get("daemon_health", {}).get("state") != "HEALTHY"
    )

    backup_inventory = inventory_backups().as_dict()
    snapshot["backup_health"] = backup_inventory
    backup_age = backup_inventory.get("latest_valid_age_hours")
    strict_backup_failed = (
        args.strict_backup
        and snapshot.get("ready") is True
        and (
            backup_inventory.get("valid_files", 0) < 1
            or backup_age is None
            or float(backup_age) > BACKUP_MAX_AGE_HOURS
        )
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
        if strict_theta_failed:
            return 4
        if strict_backup_failed:
            return 5
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

    theta_health = snapshot.get(
        "theta_health", {}
    )
    print(
        "Theta Terminal: "
        f"{theta_health.get('state')}"
    )
    print(
        "Verified backups: "
        f"{backup_inventory.get('valid_files', 0)} valid; "
        f"latest age {backup_inventory.get('latest_valid_age_hours')}h"
    )

    if strict_daemon_failed:
        return 3
    if strict_theta_failed:
        return 4
    if strict_backup_failed:
        return 5

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
