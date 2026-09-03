from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.research.deterministic_scanner import (
    ScannerRunSummary,
    scan_research_run,
)
from src.research.hypothesis_scanner import (
    HypothesisScannerResult,
    scan_local_iv_residuals,
)
from src.research.independent_runner import (
    IndependentResearchRunResult,
    run_independent_research,
)


@dataclass(frozen=True)
class ResearchCycleResult:
    research: IndependentResearchRunResult
    structural: ScannerRunSummary
    hypothesis: HypothesisScannerResult


def run_research_cycle(
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
) -> ResearchCycleResult:
    """
    Execute one complete Christiania research cycle.

    The cycle is deliberately evidence-only:

        acquire/persist market evidence
        -> deterministic structural eligibility
        -> deterministic hypothesis evaluation

    It does not create shadow candidates, place orders, or make an edge claim.
    """

    research = run_independent_research(
        symbols=symbols,
        massive_client=massive_client,
        theta_client=theta_client,
        min_dte=min_dte,
        max_dte=max_dte,
        observed_at=observed_at,
        repo_root=repo_root,
        code_git_sha=code_git_sha,
        db_path=db_path,
    )

    if research.status != "COMPLETED":
        raise RuntimeError(
            "Research cycle cannot continue from a "
            f"non-COMPLETED run: {research.status}"
        )

    structural = scan_research_run(
        research_run_id=research.run_id,
        max_spread_to_mid=max_spread_to_mid,
        db_path=db_path,
    )

    hypothesis = scan_local_iv_residuals(
        research_run_id=research.run_id,
        max_spread_to_mid=max_spread_to_mid,
        residual_threshold=residual_threshold,
        persist=True,
        structural_summary=structural,
        db_path=db_path,
    )

    return ResearchCycleResult(
        research=research,
        structural=structural,
        hypothesis=hypothesis,
    )
