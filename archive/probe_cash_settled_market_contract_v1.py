from __future__ import annotations

import argparse
import json

from src.providers.thetadata import ThetaDataClient
from src.research.cash_settled_market_contract import (
    RESEARCH_SYMBOLS,
    build_probe_evidence,
    default_evidence_path,
    write_probe_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe ThetaData capability for Christiania's cash-settled V1 research universe."
    )
    parser.add_argument("--mode", choices=("reference", "live"), default="reference")
    parser.add_argument("--symbols", nargs="+", default=list(RESEARCH_SYMBOLS))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    evidence = build_probe_evidence(
        ThetaDataClient(), symbols=args.symbols, mode=args.mode
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    if not args.no_write:
        path = write_probe_evidence(evidence, default_evidence_path())
        print(f"Evidence written: {path}")

    if args.mode == "reference":
        return 0 if evidence.get("overall_state") == "REFERENCE_PROVEN" else 2
    return 0 if "XSP" in set(evidence.get("live_symbols") or []) else 2


if __name__ == "__main__":
    raise SystemExit(main())
