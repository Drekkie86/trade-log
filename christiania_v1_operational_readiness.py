from __future__ import annotations

import argparse
import json

from src.config import load_runtime_env_file
from src.operations.v1_operational_readiness import (
    evaluate_operational_readiness,
    persist_operational_readiness,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Christiania V1 operational independence gate."
    )
    parser.add_argument("--env-file", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    for path in args.env_file:
        loaded = load_runtime_env_file(path, overwrite=False)
        if not loaded:
            raise SystemExit(f"Environment file missing or empty: {path}")

    report = evaluate_operational_readiness()
    persist_operational_readiness(report)

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print(f"Christiania V1 operational readiness: {report.state}")
        for check in report.checks:
            print(f"[{check.state}] {check.name}: {check.detail}")

    return 0 if report.operationally_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
