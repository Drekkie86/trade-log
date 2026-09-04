from __future__ import annotations

import argparse
import os
import signal

from src.research.research_daemon import (
    DEFAULT_INTERVAL_MINUTES,
    ResearchDaemonError,
    run_daemon,
)


def _handle_sigterm(_signum, _frame) -> None:
    raise KeyboardInterrupt


LOCAL_FALLBACK_SYMBOLS = [
    "AAPL",
    "JPM",
    "XOM",
]


def configured_symbols() -> list[str]:
    raw = os.environ.get(
        "CHRISTIANIA_SYMBOLS"
    )

    if raw is None or not raw.strip():
        return list(
            LOCAL_FALLBACK_SYMBOLS
        )

    symbols = [
        value.strip().upper()
        for value in raw.split(",")
        if value.strip()
    ]

    if not symbols:
        raise ResearchDaemonError(
            "CHRISTIANIA_SYMBOLS is configured but empty."
        )

    if len(symbols) != len(set(symbols)):
        raise ResearchDaemonError(
            "CHRISTIANIA_SYMBOLS contains duplicates."
        )

    return symbols


def main() -> int:
    signal.signal(
        signal.SIGTERM,
        _handle_sigterm,
    )

    parser = argparse.ArgumentParser(
        description=(
            "Continuously sample Christiania's "
            "research pipeline during configured "
            "XNYS sessions."
        )
    )

    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help=(
            "Explicit symbol list. When omitted, "
            "CHRISTIANIA_SYMBOLS is used if configured, "
            "otherwise the local three-symbol fallback is used."
        ),
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

    try:
        symbols = (
            configured_symbols()
            if args.symbols is None
            else [
                value.strip().upper()
                for value in args.symbols
                if value.strip()
            ]
        )

        if not symbols:
            raise ResearchDaemonError(
                "At least one research symbol is required."
            )

        if len(symbols) != len(set(symbols)):
            raise ResearchDaemonError(
                "Research symbol list contains duplicates."
            )

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
            "XNYS calendar-aware; samples exclude "
            "the first and last 15 minutes of each session."
        )
        print(
            f"Universe: {len(symbols)} symbols."
        )
        print(
            "No broker orders."
        )
        print()

        return run_daemon(
            symbols=symbols,
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
