from __future__ import annotations

import argparse
import json

from src.config import load_runtime_env_file
from src.operations.rc0_supervisor import collect_snapshot, persist_and_alert


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lightweight Christiania hosted-RC0 supervisor."
    )
    parser.add_argument("--env-file", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-alert", action="store_true")
    args = parser.parse_args()

    for path in args.env_file:
        loaded = load_runtime_env_file(path, overwrite=False)
        if not loaded:
            raise SystemExit(f"Environment file missing or empty: {path}")

    snapshot = collect_snapshot()
    alert = persist_and_alert(
        snapshot,
        send_alert=not args.no_alert,
    )

    payload = snapshot.as_dict() | {"alert": alert}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Christiania RC0 supervisor: {snapshot.state}")
        for check in snapshot.checks:
            print(f"[{check.state}] {check.name}: {check.detail}")
        print(f"Alert: {alert['alert_state']}")

    return 0 if snapshot.healthy else 2


if __name__ == "__main__":
    raise SystemExit(main())
