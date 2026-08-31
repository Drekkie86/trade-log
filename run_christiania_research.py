from __future__ import annotations

import argparse
import os
from pathlib import Path

from src.providers.massive import (
    MassiveClient,
)
from src.providers.thetadata import (
    ThetaDataClient,
)
from src.research.independent_runner import (
    run_independent_research,
)


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

        name, value = line.split(
            "=",
            1,
        )

        os.environ.setdefault(
            name.strip(),
            value.strip(),
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Christiania's independent "
            "evidence-collection engine."
        )
    )

    parser.add_argument(
        "--symbols",
        nargs="+",
        default=[
            "AAPL",
            "JPM",
            "XOM",
        ],
    )

    parser.add_argument(
        "--min-dte",
        type=int,
        default=7,
    )

    parser.add_argument(
        "--max-dte",
        type=int,
        default=45,
    )

    args = parser.parse_args()

    load_env_file()

    massive_key = os.environ.get(
        "MASSIVE_API_KEY"
    )

    if not massive_key:
        print(
            "REFUSED: MASSIVE_API_KEY is missing."
        )
        return 2

    print(
        "Christiania Independent Research Runner v1"
    )
    print(
        "=========================================="
    )
    print(
        "Evidence collection only."
    )
    print(
        "No candidate creation. No Saxo. No orders."
    )
    print()
    print(
        "Symbols: "
        + ", ".join(
            symbol.upper()
            for symbol in args.symbols
        )
    )
    print(
        f"DTE window: "
        f"{args.min_dte}–{args.max_dte}"
    )
    print()

    result = run_independent_research(
        symbols=args.symbols,
        massive_client=
            MassiveClient(
                massive_key
            ),
        theta_client=
            ThetaDataClient(),
        min_dte=
            args.min_dte,
        max_dte=
            args.max_dte,
    )

    print()
    print(
        f"Run ID: {result.run_id}"
    )
    print(
        f"Status: {result.status}"
    )
    print(
        f"US session: "
        f"{result.us_session_date} "
        f"{result.us_session_state}"
    )
    print()

    for summary in result.summaries:
        print(
            f"{summary.underlying}"
        )
        print(
            f"  reference:        "
            f"{summary.reference_contracts}"
        )
        print(
            f"  Massive snapshot: "
            f"{summary.massive_snapshot_rows}"
        )
        print(
            f"  Theta quotes:     "
            f"{summary.theta_quote_rows}"
        )
        print(
            f"  Theta Greeks:     "
            f"{summary.theta_greek_rows}"
        )
        print(
            f"  snapshot absent:  "
            f"{summary.snapshot_absent}"
        )
        print(
            f"  snapshot-only:    "
            f"{summary.snapshot_only}"
        )
        print(
            f"  Theta unmatched:  "
            f"{summary.theta_unmatched}"
        )
        print(
            f"  structurally ready: "
            f"{summary.structurally_ready}"
        )
        print(
            f"  structurally blocked: "
            f"{summary.structurally_blocked}"
        )
        print(
            f"  market snapshot id: "
            f"{summary.market_snapshot_id}"
        )
        print(
            f"  freshness: "
            f"{summary.quote_freshness}"
        )
        print(
            f"  Greek quality: "
            f"{summary.greek_quality}"
        )
        print()

    print(
        "Research evidence persisted to trade_log.db."
    )
    print(
        "This run makes no edge claim."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
