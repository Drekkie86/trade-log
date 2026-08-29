from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED_NONEMPTY = (
    ("candidate_id",),
    ("family_id",),
    ("edge_statement",),
    ("setup", "structure"),
    ("setup", "entry_rule"),
    ("setup", "exit_rule"),
    ("estimand", "primary_metric"),
    ("estimand", "cost_provenance"),
    ("confirmation", "independence_unit"),
    ("confirmation", "test"),
    ("confirmation", "multiplicity_method"),
)


def get_path(obj, path):
    cur = obj
    for part in path:
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument(
        "--preregister",
        action="store_true",
        help="Require preregistration-ready fields and print SHA256."
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.path)

    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 2

    if data.get("schema_version") != "1.0":
        print("FAIL: schema_version must be 1.0")
        return 2

    if not args.preregister:
        print("VALID JSON EDGE STATEMENT")
        print(f"SHA256: {hashlib.sha256(raw).hexdigest()}")
        return 0

    failures = []

    for field_path in REQUIRED_NONEMPTY:
        value = get_path(data, field_path)
        if value in (None, "", [], {}):
            failures.append(".".join(field_path))

    if data.get("status") != "PREREGISTERED":
        failures.append("status must equal PREREGISTERED")

    results = data.get("results")
    if not isinstance(results, dict) or results != {
        "locked_until_confirmation": True
    }:
        failures.append(
            "results must contain only locked_until_confirmation=true"
        )

    if failures:
        print("NOT PREREGISTRATION READY")
        for failure in failures:
            print(f"- {failure}")
        return 2

    print("PREREGISTRATION READY")
    print(f"SHA256: {hashlib.sha256(raw).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
