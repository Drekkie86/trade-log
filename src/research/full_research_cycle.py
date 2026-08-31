from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.providers.ecb_fx import (
    EcbFxObservation,
    fetch_ecb_eurusd,
)
from src.research.research_cycle import (
    ResearchCycleResult,
    run_research_cycle,
)
from src.research.shadow_admission import (
    ShadowAdmissionResult,
    admit_shadow_proposals,
)
from src.research.shadow_structure_bridge import (
    ShadowStructureBridgeResult,
    build_shadow_structure_proposals,
)


@dataclass(frozen=True)
class FullResearchCycleResult:
    research_cycle: ResearchCycleResult
    structure_bridge: ShadowStructureBridgeResult
    fx_observation: EcbFxObservation | None
    admission: ShadowAdmissionResult | None


def run_full_research_cycle(
    *,
    symbols: Iterable[str],
    massive_client,
    theta_client,
    min_dte: int = 7,
    max_dte: int = 45,
    max_spread_to_mid: float = 0.20,
    residual_threshold: float = 0.03,
    observed_at=None,
    repo_root: Path | None = None,
    code_git_sha: str | None = None,
    db_path=None,
    fx_fetcher=fetch_ecb_eurusd,
) -> FullResearchCycleResult:
    """
    Execute Christiania's complete autonomous research-only cycle.

    Sequence:
        evidence acquisition
        -> deterministic structural filter
        -> deterministic hypothesis scan
        -> defined-risk structure proposals
        -> ECB FX
        -> EUR sizing + cost reserve
        -> shadow admission

    No broker order is created.
    """

    research_cycle = run_research_cycle(
        symbols=symbols,
        massive_client=massive_client,
        theta_client=theta_client,
        min_dte=min_dte,
        max_dte=max_dte,
        max_spread_to_mid=max_spread_to_mid,
        residual_threshold=residual_threshold,
        observed_at=observed_at,
        repo_root=repo_root,
        code_git_sha=code_git_sha,
        db_path=db_path,
    )

    hypothesis_run_id = (
        research_cycle.hypothesis
        .persisted_scanner_run_id
    )

    if hypothesis_run_id is None:
        raise RuntimeError(
            "Full research cycle requires a "
            "persisted hypothesis scanner run."
        )

    bridge = build_shadow_structure_proposals(
        hypothesis_scanner_run_id=
            hypothesis_run_id,
        persist=True,
        db_path=db_path,
    )

    proposed_ids = [
        int(item.persisted_proposal_id)
        for item in bridge.proposals
        if (
            item.proposal_state
            == "PROPOSED"
            and item.persisted_proposal_id
            is not None
        )
    ]

    if not proposed_ids:
        return FullResearchCycleResult(
            research_cycle=research_cycle,
            structure_bridge=bridge,
            fx_observation=None,
            admission=None,
        )

    fx = fx_fetcher()

    admission = admit_shadow_proposals(
        fx=fx,
        proposal_ids=proposed_ids,
        db_path=db_path,
    )

    return FullResearchCycleResult(
        research_cycle=research_cycle,
        structure_bridge=bridge,
        fx_observation=fx,
        admission=admission,
    )
