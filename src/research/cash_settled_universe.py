from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CashSettledUniverseState:
    symbols: tuple[str, ...]
    provider_compatibility_state: str
    live_collection_enabled: bool
    note: str

    def as_dict(self) -> dict:
        return asdict(self)


def cash_settled_research_universe() -> CashSettledUniverseState:
    return CashSettledUniverseState(
        symbols=("SPX", "XSP"),
        provider_compatibility_state="NOT_LIVE_PROBED",
        live_collection_enabled=False,
        note=(
            "SPX/XSP are the V1 cash-settled research candidates, but Christiania has not yet proven end-to-end provider compatibility for them. "
            "They are therefore not silently added to the daemon universe."
        ),
    )
