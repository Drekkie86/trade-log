from __future__ import annotations

import argparse

from src.research.research_daemon import (
    DEFAULT_INTERVAL_MINUTES,
    ResearchDaemonError,
    run_daemon,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Continuously sample Christiania's "
            "research pipeline during configured "
            "US regular-session hours."
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
        "--interval-minutes",
        type=int,
        default=
            DEFAULT_INTERVAL_MINUTES,
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help=(
            "Optional test/rehearsal limit. "
            "Omit for continuous operation."
        ),
    )

    args = parser.parse_args()

    print(
        "Christiania Research Daemon v1"
    )
    print(
        "=============================="
    )
    print(
        "Research-only repeated sampling."
    )
    print(
        "Default window: weekdays 09:45–15:45 America/New_York."
    )
    print(
        "No broker orders."
    )
    print()

    try:
        return run_daemon(
            symbols=args.symbols,
            interval_minutes=
                args.interval_minutes,
            max_iterations=
                args.max_iterations,
        )
    except ResearchDaemonError as exc:
        print(
            f"REFUSED: {exc}"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
