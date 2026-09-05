from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from src.research.cash_settled_market_contract import (
    PRIMARY_V1_SYMBOL,
    RESEARCH_SYMBOLS,
    default_evidence_path,
    read_probe_evidence,
)


@dataclass(frozen=True)
class CashSettledUniverseState:
    symbols: tuple[str, ...]
    provider_compatibility_state: str
    live_collection_enabled: bool
    live_symbols: tuple[str, ...]
    primary_v1_symbol: str
    evidence_path: str
    note: str

    def as_dict(self) -> dict:
        return asdict(self)


def cash_settled_research_universe(
    *,
    evidence_path: str | Path | None = None,
) -> CashSettledUniverseState:
    path = Path(evidence_path).expanduser() if evidence_path is not None else default_evidence_path()
    evidence = read_probe_evidence(path)
    if evidence is None:
        return CashSettledUniverseState(
            symbols=("SPX", "XSP"),
            provider_compatibility_state="NOT_LIVE_PROBED",
            live_collection_enabled=False,
            live_symbols=(),
            primary_v1_symbol=PRIMARY_V1_SYMBOL,
            evidence_path=str(path),
            note=(
                "SPX/XSP are the V1 cash-settled research candidates, but Christiania has not yet recorded a passing live provider proof. "
                "They are not silently added to the daemon universe. XSP is the primary V1 live-contract target."
            ),
        )

    live = tuple(symbol for symbol in RESEARCH_SYMBOLS if symbol in set(evidence.get("live_symbols") or []))
    state = str(evidence.get("overall_state") or "EVIDENCE_INVALID")
    return CashSettledUniverseState(
        symbols=("SPX", "XSP"),
        provider_compatibility_state=state,
        live_collection_enabled=bool(live),
        live_symbols=live,
        primary_v1_symbol=PRIMARY_V1_SYMBOL,
        evidence_path=str(path),
        note=(
            f"Recorded provider proof state: {state}. Live-proven symbols: {', '.join(live) if live else 'none'}. "
            "Daemon collection still requires explicit operator opt-in; proof alone never adds symbols automatically."
        ),
    )
