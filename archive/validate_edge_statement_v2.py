"""
Christiania — Edge Statement validator CLI (v2).

Additive. Does not replace validate_edge_statement.py.

    python validate_edge_statement_v2.py <candidate.json> \\
        --registry research/edge_discovery/DISCOVERY_WINDOW_REGISTRY.json

Exit code 0 on PASS, 1 on FAIL, 2 on a usage/file error, so it can gate a
commit hook or CI step rather than only being read by a human.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.research.edge_statement_validation import validate_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Christiania Edge Statement."
    )
    parser.add_argument("document", help="Path to the Edge Statement JSON.")
    parser.add_argument(
        "--registry",
        default="research/edge_discovery/DISCOVERY_WINDOW_REGISTRY.json",
        help="Path to the discovery-window registry.",
    )
    args = parser.parse_args()

    print("Christiania - Edge Statement validation (v2)")
    print("==============================================")
    print(f"Document: {args.document}")
    print(f"Registry: {args.registry}")
    print()

    try:
        result = validate_file(args.document, args.registry)
    except FileNotFoundError as exc:
        print(f"FAIL: {exc}")
        return 2
    except (KeyError, ValueError) as exc:
        print(f"FAIL: malformed input: {exc}")
        return 2

    print(result.report())

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
