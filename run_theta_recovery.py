from __future__ import annotations

import argparse
import json
import os

from src.operations.theta_recovery import recover_theta


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover a stale/unhealthy Theta session and resume Christiania research."
    )
    parser.add_argument("--reason", required=True)
    parser.add_argument("--wait-seconds", type=float, default=120.0)
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("REFUSED: Theta recovery must run as root so it can control systemd.")
        return 2

    result = recover_theta(
        reason=args.reason,
        wait_seconds=args.wait_seconds,
    )
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
