from __future__ import annotations

from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import os
from pathlib import Path

from src.providers.massive import MassiveClient
from src.providers.thetadata import ThetaDataClient
from src.research.live_pipeline import (
    build_live_join,
    diagnose_admission,
)
from src.research.thetadata_live_adapter import (
    fetch_live_first_order_greek_rows,
    fetch_live_quote_rows,
    filter_dte_window,
)

NY = ZoneInfo("America/New_York")


def load_env_file() -> None:
    path = Path(".env")
    if not path.exists():
        return

    for raw in path.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw.strip()
        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        name, value = line.split("=", 1)
        os.environ.setdefault(
            name.strip(),
            value.strip(),
        )


def reference_identity(row):
    right = (
        "C"
        if row.get("contract_type") == "call"
        else "P"
    )
    return (
        str(
            row.get("underlying_ticker")
            or "AAPL"
        ).upper(),
        str(row["expiration_date"]),
        float(row["strike_price"]),
        right,
    )


def main() -> int:
    load_env_file()

    key = os.environ.get(
        "MASSIVE_API_KEY"
    )
    if not key:
        print(
            "REFUSED: MASSIVE_API_KEY missing."
        )
        return 2

    now_ny = datetime.now(NY)
    today = now_ny.date()

    print(
        "Christiania - Live Pipeline Admission Probe v1"
    )
    print(
        "=============================================="
    )
    print(
        "READ-ONLY. No DB writes. No candidates. No orders."
    )
    print(
        f"Observed at NY: "
        f"{now_ny.isoformat(timespec='seconds')}"
    )
    print()

    massive = MassiveClient(key)
    theta = ThetaDataClient()

    reference_rows = massive.get_option_contracts_reference(
        "AAPL",
        min_dte=7,
        max_dte=45,
        as_of_date=today,
        require_complete=True,
    )["results"]

    reference_contracts = [
        {
            "id": index + 1,
            "underlying":
                identity[0],
            "expiration":
                identity[1],
            "strike":
                identity[2],
            "right":
                identity[3],
        }
        for index, identity in enumerate(
            sorted(
                reference_identity(row)
                for row in reference_rows
            )
        )
    ]

    quote_rows = filter_dte_window(
        fetch_live_quote_rows(
            theta,
            "AAPL",
        ),
        reference_date=today,
    )

    greek_rows = filter_dte_window(
        fetch_live_first_order_greek_rows(
            theta,
            "AAPL",
        ),
        reference_date=today,
    )

    joined = build_live_join(
        reference_contracts=
            reference_contracts,
        quote_rows=quote_rows,
        greek_rows=greek_rows,
        observed_at=now_ny,
    )

    diagnostics = diagnose_admission(
        joined
    )

    freshness = Counter(
        item.quote_freshness.value
        for item in diagnostics
    )
    greek_quality = Counter(
        item.greek_quality.value
        for item in diagnostics
    )
    blockers = Counter(
        reason
        for item in diagnostics
        for reason in item.blocking_reasons
    )

    structurally_ready = sum(
        item.structurally_ready
        for item in diagnostics
    )

    print(
        f"Reference contracts: "
        f"{len(reference_contracts)}"
    )
    print(
        f"Joined contracts:    "
        f"{len(joined)}"
    )
    print()

    print("Quote freshness")
    for label in (
        "FRESH",
        "AGING",
        "STALE",
        "UNKNOWN",
    ):
        print(
            f"  {label:7s}: "
            f"{freshness[label]}"
        )
    print()

    print("Greek quality")
    for label in (
        "GOOD",
        "REVIEW",
        "BAD",
        "UNKNOWN",
    ):
        print(
            f"  {label:7s}: "
            f"{greek_quality[label]}"
        )
    print()

    print(
        "Structural admission diagnostic"
    )
    print(
        f"  structurally ready: "
        f"{structurally_ready}"
    )
    print(
        f"  blocked:            "
        f"{len(diagnostics) - structurally_ready}"
    )

    if blockers:
        print()
        print("Blocking reasons")
        for reason, count in (
            blockers.most_common()
        ):
            print(
                f"  {reason}: {count}"
            )

    print()
    print("IMPORTANT")
    print(
        "STRUCTURALLY READY is not a trade candidate "
        "and not an edge claim."
    )
    print(
        "Liquidity/spread/parity/economic filters and "
        "scanner rules are not yet applied."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
