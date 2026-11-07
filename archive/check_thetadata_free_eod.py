from __future__ import annotations
import argparse
from datetime import date
import json

from src.providers.thetadata import (
    ThetaDataClient,
    ThetaDataError,
    field_inventory,
    summarize_option_rows,
    verify_nbbo_shape,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect the actual ThetaData free historical EOD option payload."
    )
    parser.add_argument("symbol")
    parser.add_argument("date")
    parser.add_argument("--max-dte", type=int, default=45)
    parser.add_argument("--sample-rows", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        trading_date = date.fromisoformat(args.date)
    except ValueError:
        print("FAIL: date must be YYYY-MM-DD")
        return 2

    client = ThetaDataClient()

    print("Christiania - ThetaData free EOD empirical check")
    print("===============================================")
    print("Read-only. No database writes. No broker calls.")
    print(f"Symbol: {args.symbol.upper()}")
    print(f"Date:   {trading_date.isoformat()}")
    print()

    try:
        rows = client.option_eod_chain(
            args.symbol,
            trading_date,
            max_dte=args.max_dte,
        )
    except ThetaDataError as exc:
        print(f"FAIL: {exc}")
        return 1

    if not rows:
        print("FAIL: ThetaData returned zero rows.")
        return 1

    summary = summarize_option_rows(rows)
    nbbo = verify_nbbo_shape(rows)
    fields = field_inventory(rows)

    print("SUMMARY")
    for key, value in summary.items():
        print(f"{key:28s}: {value}")

    print()
    print("ACTUAL RETURNED FIELDS")
    print(", ".join(fields))

    print()
    print("NBBO SHAPE CHECK")
    for key, value in nbbo.items():
        print(f"{key:28s}: {value}")

    print()
    print("SAMPLE ROWS")
    for index, row in enumerate(rows[: max(0, args.sample_rows)], start=1):
        print(f"--- row {index} ---")
        print(json.dumps(row, indent=2, sort_keys=True))

    print()

    if not nbbo["passes_shape_check"]:
        print(
            "FAIL: actual payload did not contain usable numeric bid/ask "
            "observations. Do not use it for spread calibration."
        )
        return 1

    print("PASS: actual payload contains numeric bid and ask observations.")
    print(
        "Next step is provider identity normalization and historical batch "
        "ingestion; this check alone does not prove Christiania semantics."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
