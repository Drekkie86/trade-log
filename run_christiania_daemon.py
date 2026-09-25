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
from src.research.universe_profiles import (
    DEFAULT_ROTATING_BATCH_SIZE,
    symbols_for_profile,
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


def configured_universe_profile() -> str | None:
    raw = os.environ.get("CHRISTIANIA_UNIVERSE_PROFILE")
    if raw is None or not raw.strip():
        return None
    return raw.strip().upper()


def configured_symbols() -> list[str]:
    raw = os.environ.get("CHRISTIANIA_SYMBOLS")
    profile = configured_universe_profile()

    if raw is not None and raw.strip() and profile is not None:
        raise ResearchDaemonError(
            "Configure either CHRISTIANIA_SYMBOLS or "
            "CHRISTIANIA_UNIVERSE_PROFILE, not both."
        )

    if profile is not None:
        try:
            symbols = symbols_for_profile(profile)
        except ValueError as exc:
            raise ResearchDaemonError(str(exc)) from exc
    elif raw is None or not raw.strip():
        symbols = list(LOCAL_FALLBACK_SYMBOLS)
    else:
        symbols = [value.strip().upper() for value in raw.split(",") if value.strip()]
        if not symbols:
            raise ResearchDaemonError("CHRISTIANIA_SYMBOLS is configured but empty.")
        if len(symbols) != len(set(symbols)):
            raise ResearchDaemonError("CHRISTIANIA_SYMBOLS contains duplicates.")

    validate_cash_settled_collection(symbols)
    return symbols


def configured_batch_size(
    *,
    symbol_count: int,
    profile: str | None,
) -> int:
    raw = os.environ.get("CHRISTIANIA_UNIVERSE_BATCH_SIZE")
    if raw is None or not raw.strip():
        return (
            min(DEFAULT_ROTATING_BATCH_SIZE, symbol_count)
            if profile is not None
            else symbol_count
        )

    try:
        value = int(raw)
    except ValueError as exc:
        raise ResearchDaemonError(
            "CHRISTIANIA_UNIVERSE_BATCH_SIZE must be an integer."
        ) from exc

    if value < 1:
        raise ResearchDaemonError(
            "CHRISTIANIA_UNIVERSE_BATCH_SIZE must be >= 1."
        )

    return min(value, symbol_count)


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
        "--batch-size",
        type=int,
        default=None,
        help="Symbols sampled per slot. Defaults to the full explicit list, or 12 for a configured universe profile.",
    )
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

        profile = None if args.symbols is not None else configured_universe_profile()
        batch_size = (
            configured_batch_size(
                symbol_count=len(symbols),
                profile=profile,
            )
            if args.batch_size is None
            else args.batch_size
        )
        if batch_size < 1:
            raise ResearchDaemonError("--batch-size must be >= 1.")
        batch_size = min(batch_size, len(symbols))

        print("Christiania Research Daemon v1")
        print("==============================")
        print("Research-only repeated sampling.")
        print("XNYS calendar-aware; samples exclude the first and last 15 minutes of each session.")
        print(f"Universe: {len(symbols)} symbols.")
        print(f"Universe profile: {profile or 'EXPLICIT_OR_LOCAL'}.")
        print(f"Per-slot batch: {batch_size} symbols.")
        print("No broker orders.")
        print()
        return run_daemon(
            symbols=symbols,
            interval_minutes=args.interval_minutes,
            max_iterations=args.max_iterations,
            batch_size=batch_size,
            universe_profile=profile,
        )
    except ResearchDaemonError as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
