from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.operations.control_plane_status import (
    DEFAULT_APP_DIR,
    DEFAULT_AUDIT_DIR,
    DEFAULT_SYSTEMD_ROOT,
    collect_control_plane_status,
)


def _print_human(
    payload: dict[str, object],
) -> None:
    ready = bool(
        payload["ready"]
    )

    print(
        "Christiania Control Plane"
    )
    print(
        "=========================="
    )
    print(
        "state="
        + (
            "READY"
            if ready
            else "NOT READY"
        )
    )
    print(
        "deployed_commit="
        + str(
            payload[
                "deployed_commit"
            ]
            or "UNKNOWN"
        )
    )
    print(
        "release_identity="
        + str(
            payload[
                "release_identity_state"
            ]
        )
    )
    print(
        "supervisor="
        + str(
            payload[
                "supervisor_state"
            ]
        )
    )
    print(
        "supervisor_observed_at="
        + str(
            payload[
                "supervisor_observed_at"
            ]
            or "UNKNOWN"
        )
    )
    print(
        "research_progress="
        + str(
            payload[
                "research_progress_state"
            ]
        )
    )

    detail = payload.get(
        "research_progress_detail"
    )
    if detail:
        print(
            "research_detail="
            + str(detail)
        )

    print(
        "resource_policy="
        + (
            f"{payload['resource_policy_state']} "
            f"({payload['resource_policy_passed']}/"
            f"{payload['resource_policy_total']})"
        )
    )

    services = payload[
        "core_services"
    ]

    if isinstance(
        services,
        dict,
    ):
        for unit, state in services.items():
            print(
                f"{unit}={state}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Christiania single operator "
            "status surface."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
    )
    parser.add_argument(
        "--app-dir",
        type=Path,
        default=DEFAULT_APP_DIR,
    )
    parser.add_argument(
        "--audit-dir",
        type=Path,
        default=DEFAULT_AUDIT_DIR,
    )
    parser.add_argument(
        "--systemd-root",
        type=Path,
        default=DEFAULT_SYSTEMD_ROOT,
    )

    args = parser.parse_args()

    status = collect_control_plane_status(
        app_dir=args.app_dir,
        audit_dir=args.audit_dir,
        systemd_root=args.systemd_root,
    )

    payload = status.as_dict()

    if args.json:
        print(
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_human(
            payload
        )

    return (
        0
        if status.ready
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )