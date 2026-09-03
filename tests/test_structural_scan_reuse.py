from types import SimpleNamespace

import src.research.hypothesis_scanner as hypothesis_scanner
import src.research.research_cycle as research_cycle


def test_research_cycle_reuses_structural_scan(
    monkeypatch,
):
    research = SimpleNamespace(
        status="COMPLETED",
        run_id=123,
    )
    structural = SimpleNamespace(
        observations=(),
    )
    hypothesis = object()
    received = {}

    monkeypatch.setattr(
        research_cycle,
        "run_independent_research",
        lambda **kwargs: research,
    )
    monkeypatch.setattr(
        research_cycle,
        "scan_research_run",
        lambda **kwargs: structural,
    )

    def fake_hypothesis(**kwargs):
        received.update(kwargs)
        return hypothesis

    monkeypatch.setattr(
        research_cycle,
        "scan_local_iv_residuals",
        fake_hypothesis,
    )

    result = research_cycle.run_research_cycle(
        symbols=["AAPL"],
        massive_client=object(),
        theta_client=object(),
    )

    assert result.structural is structural
    assert result.hypothesis is hypothesis
    assert received["structural_summary"] is structural


def test_hypothesis_accepts_precomputed_structural(
    monkeypatch,
):
    structural = SimpleNamespace(
        observations=(),
    )

    def should_not_run(**kwargs):
        raise AssertionError(
            "duplicate structural scan executed"
        )

    monkeypatch.setattr(
        hypothesis_scanner,
        "scan_research_run",
        should_not_run,
    )

    result = (
        hypothesis_scanner
        .scan_local_iv_residuals(
            research_run_id=123,
            structural_summary=structural,
            persist=False,
        )
    )

    assert result.structural_input_count == 0
    assert result.evaluable_count == 0
    assert result.surfaced_count == 0
