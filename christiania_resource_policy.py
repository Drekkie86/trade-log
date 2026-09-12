from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.operations.service_resources import (
    SERVICE_RESOURCE_POLICIES,
    managed_service_units,
)
from src.operations.systemd_resources import (
    check_resource_dropins,
    write_resource_dropins,
)


DEFAULT_SYSTEMD_ROOT = Path(
    "/etc/systemd/system"
)


def _policy_payload() -> dict[str, object]:
    return {
        "service_count": len(
            SERVICE_RESOURCE_POLICIES
        ),
        "services": {
            unit: SERVICE_RESOURCE_POLICIES[
                unit
            ].as_dict()
            for unit in managed_service_units()
        },
    }


def _print_policy_json() -> None:
    print(
        json.dumps(
            _policy_payload(),
            indent=2,
            sort_keys=True,
        )
    )


def _render(
    root: Path,
) -> int:
    paths = write_resource_dropins(root)

    for path in paths:
        print(path)

    print(
        f"Wrote {len(paths)} Christiania "
        "resource-policy drop-ins."
    )
    return 0


def _check(
    root: Path,
) -> int:
    checks = check_resource_dropins(root)

    for check in checks:
        print(
            f"[{check.state}] "
            f"{check.unit}: "
            f"{check.detail}"
        )

    failed = [
        check
        for check in checks
        if not check.passed
    ]

    if failed:
        print()
        print(
            "RESOURCE POLICY MISMATCH"
        )
        return 2

    print()
    print(
        "RESOURCE POLICY MATCHED"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Christiania canonical systemd "
            "resource-policy control surface."
        )
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    sub.add_parser(
        "show",
        help=(
            "Print the canonical Christiania "
            "service-resource policy as JSON."
        ),
    )

    render = sub.add_parser(
        "render",
        help=(
            "Write canonical systemd resource "
            "drop-ins."
        ),
    )
    render.add_argument(
        "--systemd-root",
        type=Path,
        default=DEFAULT_SYSTEMD_ROOT,
    )

    check = sub.add_parser(
        "check",
        help=(
            "Verify installed systemd resource "
            "drop-ins against the canonical policy."
        ),
    )
    check.add_argument(
        "--systemd-root",
        type=Path,
        default=DEFAULT_SYSTEMD_ROOT,
    )

    args = parser.parse_args()

    if args.command == "show":
        _print_policy_json()
        return 0

    if args.command == "render":
        return _render(
            args.systemd_root,
        )

    if args.command == "check":
        return _check(
            args.systemd_root,
        )

    raise AssertionError(
        "unreachable"
    )


if __name__ == "__main__":
    raise SystemExit(main())