from __future__ import annotations

import argparse
import os
import signal

from src.research.cash_settled_universe import cash_settled_research_universe
from src.research.research_daemon import (
    DEFAULT_INTERVAL_MINUTES,
    ResearchDaemonError,
    run_daemon,
)


def _handle_sigterm(_signum, _frame) -> None:
    raise KeyboardInterrupt


LOCAL_FALLBACK_SYMBOLS = ["AAPL", "JPM", "XOM"]
CASH_SETTLED_SYMBOLS = {"SPX", "XSP"}


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def validate_cash_settled_collection(symbols: list[str]) -> None:
    requested = sorted(CASH_SETTLED_SYMBOLS.intersection(symbols))
    if not requested:
        return
    if not _truthy_env("CHRISTIANIA_ENABLE_CASH_SETTLED_RESEARCH"):
        raise ResearchDaemonError(
            "Cash-settled research symbols require explicit CHRISTIANIA_ENABLE_CASH_SETTLED_RESEARCH=1 opt-in."
        )
    state = cash_settled_research_universe()
    missing = [symbol for symbol in requested if symbol not in state.live_symbols]
    if missing:
        raise ResearchDaemonError(
            "Cash-settled research symbols are not live-provider validated: " + ", ".join(missing)
        )


def configured_symbols() -> list[str]:
    raw = os.environ.get("CHRISTIANIA_SYMBOLS")
    if raw is None or not raw.strip():
        symbols = list(LOCAL_FALLBACK_SYMBOLS)
    else:
        symbols = [value.strip().upper() for value in raw.split(",") if value.strip()]
        if not symbols:
            raise ResearchDaemonError("CHRISTIANIA_SYMBOLS is configured but empty.")
        if len(symbols) != len(set(symbols)):
            raise ResearchDaemonError("CHRISTIANIA_SYMBOLS contains duplicates.")
    validate_cash_settled_collection(symbols)
    return symbols


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_sigterm)
    parser = argparse.ArgumentParser(
        description="Continuously sample Christiania's research pipeline during configured XNYS sessions."
    )
    parser.add_argument(
        "--symbols", nargs="+", default=None,
        help="Explicit symbol list. When omitted, CHRISTIANIA_SYMBOLS is used if configured, otherwise the local fallback is used.",
    )
    parser.add_argument("--interval-minutes", type=int, default=DEFAULT_INTERVAL_MINUTES)
    parser.add_argument(
        "--max-iterations", type=int, default=None,
        help="Optional test/rehearsal limit. Omit for continuous operation.",
    )
    args = parser.parse_args()

    try:
        symbols = configured_symbols() if args.symbols is None else [value.strip().upper() for value in args.symbols if value.strip()]
        if not symbols:
            raise ResearchDaemonError("At least one research symbol is required.")
        if len(symbols) != len(set(symbols)):
            raise ResearchDaemonError("Research symbol list contains duplicates.")
        validate_cash_settled_collection(symbols)

        print("Christiania Research Daemon v1")
        print("==============================")
        print("Research-only repeated sampling.")
        print("XNYS calendar-aware; samples exclude the first and last 15 minutes of each session.")
        print(f"Universe: {len(symbols)} symbols.")
        print("No broker orders.")
        print()
        return run_daemon(
            symbols=symbols,
            interval_minutes=args.interval_minutes,
            max_iterations=args.max_iterations,
        )
    except ResearchDaemonError as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
