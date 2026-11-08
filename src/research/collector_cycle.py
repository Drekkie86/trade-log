"""Collector-only daemon cycle: acquire and persist market evidence, nothing else.

With ``CHRISTIANIA_COLLECTOR_ONLY=1`` the daemon runs this instead of the full
research cycle. It keeps the research-run and snapshot schema the engine reads
(``research_runs``, ``market_snapshots``, ``option_quotes``,
``provider_model_observations``) and skips the retired stages: hypothesis
scanner, surface residuals, structure bridge, shadow admission, opportunity
assessment, lifecycle advancement and shadow marks. The iteration summary keeps
its shape so the daemon's bookkeeping and the System page are unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.research.independent_runner import (
    IndependentResearchRunResult,
    run_independent_research,
)


@dataclass(frozen=True)
class _NoHypothesis:
    persisted_scanner_run_id: int | None = None


@dataclass(frozen=True)
class _NoBridge:
    proposed_count: int = 0
    blocked_count: int = 0


@dataclass(frozen=True)
class _CollectorResearchCycle:
    research: IndependentResearchRunResult
    hypothesis: _NoHypothesis = _NoHypothesis()


@dataclass(frozen=True)
class CollectorCycleResult:
    research_cycle: _CollectorResearchCycle
    structure_bridge: _NoBridge = _NoBridge()
    admission: None = None
    admission_error: str | None = None


@dataclass(frozen=True)
class _NoMarks:
    research_run_id: int
    active_candidate_count: int = 0
    marks_written: int = 0
    complete_marks: int = 0
    incomplete_marks: int = 0
    marks: tuple = ()


def run_collector_cycle(
    *,
    symbols: Iterable[str],
    massive_client,
    theta_client,
    min_dte: int = 7,
    max_dte: int = 45,
    observed_at=None,
    repo_root: Path | None = None,
    code_git_sha: str | None = None,
    db_path=None,
    **_ignored,
) -> CollectorCycleResult:
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
            f"Collector cycle cannot continue from a non-COMPLETED run: {research.status}"
        )
    return CollectorCycleResult(research_cycle=_CollectorResearchCycle(research=research))


def skip_shadow_marks(*, research_run_id: int, db_path=None, **_ignored) -> _NoMarks:
    return _NoMarks(research_run_id=int(research_run_id))
