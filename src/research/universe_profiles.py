from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Iterable
from zoneinfo import ZoneInfo


NY = ZoneInfo("America/New_York")

LIQUID_US_RESEARCH_V1 = (
    "SPY", "QQQ", "IWM", "DIA",
    "XLF", "XLK", "XLE", "XLV",
    "XLI", "XLP", "XLY", "SMH",
    "TLT", "GLD", "SLV", "HYG",
    "AAPL", "MSFT", "NVDA", "AMZN",
    "META", "GOOGL", "TSLA", "AMD",
    "AVGO", "NFLX", "ORCL", "CRM",
    "JPM", "BAC", "GS", "MS",
    "V", "MA", "XOM", "CVX",
    "UNH", "LLY", "PLTR", "INTC",
    "COST", "WMT", "HD", "CAT",
    "BA", "GE", "MU", "COIN",
)

UNIVERSE_PROFILES = {
    "LIQUID_US_RESEARCH_V1": LIQUID_US_RESEARCH_V1,
}

DEFAULT_ROTATING_BATCH_SIZE = 12
MAX_SHADOW_TRACKING_BATCH_MULTIPLIER = 2


@dataclass(frozen=True)
class UniverseBatch:
    profile: str | None
    universe_size: int
    batch_size: int
    batch_index: int
    batch_count: int
    symbols: tuple[str, ...]
    pinned_added: tuple[str, ...] = ()
    pinned_deferred: tuple[str, ...] = ()


def symbols_for_profile(name: str) -> list[str]:
    key = str(name or "").strip().upper()
    if key not in UNIVERSE_PROFILES:
        raise ValueError(
            "Unknown Christiania universe profile: "
            f"{name!r}. Available: "
            + ", ".join(sorted(UNIVERSE_PROFILES))
        )
    return list(UNIVERSE_PROFILES[key])


def select_symbol_batch(
    *,
    symbols: list[str],
    scheduled_for: datetime,
    batch_size: int,
    interval_minutes: int,
    profile: str | None = None,
    pinned: Iterable[str] = (),
) -> UniverseBatch:
    """Preserve universe rotation while sampling as many tracked pins as budgeted.

    Total symbols cannot exceed twice the normal batch size. When there are
    more active pins than fit, extra pins rotate fairly across slots and are
    reported as deferred, never silently ignored. This bounds provider work
    without claiming a guarantee of sampling every tracked symbol every slot.
    """
    if not symbols:
        raise ValueError("Universe cannot be empty.")
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1.")
    if interval_minutes < 1:
        raise ValueError("interval_minutes must be >= 1.")

    normalized = [str(symbol).strip().upper() for symbol in symbols]
    if any(not symbol for symbol in normalized):
        raise ValueError("Universe contains an empty symbol.")
    if len(normalized) != len(set(normalized)):
        raise ValueError("Universe contains duplicate symbols.")

    effective_batch = min(batch_size, len(normalized))
    batch_count = ceil(len(normalized) / effective_batch)

    local = scheduled_for.astimezone(NY)
    session_anchor_minutes = 9 * 60 + 45
    slot_minutes = local.hour * 60 + local.minute
    slot_index = max(
        0,
        (slot_minutes - session_anchor_minutes) // interval_minutes,
    )
    batch_index = slot_index % batch_count

    start = batch_index * effective_batch
    end = min(start + effective_batch, len(normalized))
    rotating = list(normalized[start:end])

    universe = set(normalized)
    eligible = sorted({
        str(raw).strip().upper()
        for raw in pinned
        if str(raw).strip().upper() in universe
        and str(raw).strip().upper() not in rotating
    })
    max_total = min(
        len(normalized), effective_batch * MAX_SHADOW_TRACKING_BATCH_MULTIPLIER
    )
    slots_remaining = max(0, max_total - len(rotating))
    if eligible and slots_remaining:
        offset = (slot_index * slots_remaining) % len(eligible)
        chosen = {
            eligible[(offset + j) % len(eligible)]
            for j in range(min(slots_remaining, len(eligible)))
        }
    else:
        chosen = set()
    pinned_added = sorted(chosen)
    pinned_deferred = sorted(set(eligible) - chosen)

    return UniverseBatch(
        profile=None if profile is None else profile.upper(),
        universe_size=len(normalized),
        batch_size=len(rotating) + len(pinned_added),
        batch_index=batch_index,
        batch_count=batch_count,
        symbols=tuple(rotating + pinned_added),
        pinned_added=tuple(pinned_added),
        pinned_deferred=tuple(pinned_deferred),
    )
