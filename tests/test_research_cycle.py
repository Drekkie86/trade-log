from dataclasses import dataclass

from src.research.research_cycle import (
    run_research_cycle,
)


@dataclass(frozen=True)
class FakeResearch:
    run_id: int = 42
    status: str = "COMPLETED"
    us_session_date: str = "2026-09-01"
    us_session_state: str = "INTRADAY"
    summaries: tuple = ()


@dataclass(frozen=True)
class FakeStructural:
    research_run_id: int = 42
    total_quotes: int = 100
    eligible: int = 12
    blocked: int = 88
    blocker_counts: dict = None


@dataclass(frozen=True)
class FakeSurfaceV2:
    research_run_id: int = 42
    persisted_model_run_id: int = 8
    structural_input_count: int = 12
    reference_mapped_count: int = 11
    evaluable_count: int = 7
    observations: tuple = ()


@dataclass(frozen=True)
class FakeHypothesis:
    research_run_id: int = 42
    persisted_scanner_run_id: int = 7
    structural_input_count: int = 12
    evaluable_count: int = 8
    surfaced_count: int = 2
    evaluations: tuple = ()


def test_research_cycle_orders_the_three_stages(
    monkeypatch,
):
    calls = []

    def fake_research(**kwargs):
        calls.append(
            (
                "research",
                kwargs["symbols"],
            )
        )
        return FakeResearch()

    def fake_structural(**kwargs):
        calls.append(
            (
                "structural",
                kwargs["research_run_id"],
            )
        )
        return FakeStructural(
            blocker_counts={}
        )

    def fake_hypothesis(**kwargs):
        calls.append(("hypothesis", kwargs["research_run_id"]))
        return FakeHypothesis()

    def fake_surface_v2(**kwargs):
        calls.append(("surface_v2", kwargs["research_run_id"]))
        assert kwargs["structural_summary"].eligible == 12
        return FakeSurfaceV2()

    monkeypatch.setattr(
        "src.research.research_cycle."
        "run_independent_research",
        fake_research,
    )

    monkeypatch.setattr(
        "src.research.research_cycle."
        "scan_research_run",
        fake_structural,
    )

    monkeypatch.setattr(
        "src.research.research_cycle."
        "scan_local_iv_residuals",
        fake_hypothesis,
    )
    monkeypatch.setattr(
        "src.research.research_cycle.scan_local_surface_residual_v2",
        fake_surface_v2,
    )

    result = run_research_cycle(
        symbols=[
            "AAPL",
            "JPM",
            "XOM",
        ],
        massive_client=object(),
        theta_client=object(),
    )

    assert calls == [
        (
            "research",
            [
                "AAPL",
                "JPM",
                "XOM",
            ],
        ),
        (
            "structural",
            42,
        ),
        (
            "hypothesis",
            42,
        ),
        (
            "surface_v2",
            42,
        ),
    ]

    assert result.research.run_id == 42
    assert result.structural.eligible == 12
    assert result.hypothesis.surfaced_count == 2
    assert result.surface_v2.evaluable_count == 7


def test_research_cycle_propagates_frozen_thresholds(
    monkeypatch,
):
    captured = {}

    def fake_research(**kwargs):
        return FakeResearch()

    def fake_structural(**kwargs):
        captured[
            "structural_spread"
        ] = kwargs[
            "max_spread_to_mid"
        ]
        return FakeStructural(
            blocker_counts={}
        )

    def fake_hypothesis(**kwargs):
        captured[
            "hypothesis_spread"
        ] = kwargs[
            "max_spread_to_mid"
        ]
        captured[
            "residual_threshold"
        ] = kwargs[
            "residual_threshold"
        ]
        captured[
            "persist"
        ] = kwargs[
            "persist"
        ]
        return FakeHypothesis()

    def fake_surface_v2(**kwargs):
        captured["surface_v2_spread"] = kwargs["max_spread_to_mid"]
        captured["surface_v2_persist"] = kwargs["persist"]
        captured["surface_v2_reused_structural"] = kwargs["structural_summary"].eligible
        return FakeSurfaceV2()

    monkeypatch.setattr(
        "src.research.research_cycle."
        "run_independent_research",
        fake_research,
    )

    monkeypatch.setattr(
        "src.research.research_cycle."
        "scan_research_run",
        fake_structural,
    )

    monkeypatch.setattr(
        "src.research.research_cycle."
        "scan_local_iv_residuals",
        fake_hypothesis,
    )
    monkeypatch.setattr(
        "src.research.research_cycle.scan_local_surface_residual_v2",
        fake_surface_v2,
    )

    run_research_cycle(
        symbols=["AAPL"],
        massive_client=object(),
        theta_client=object(),
        max_spread_to_mid=0.15,
        residual_threshold=0.025,
    )

    assert (
        captured["structural_spread"]
        == 0.15
    )
    assert (
        captured["hypothesis_spread"]
        == 0.15
    )
    assert (
        captured["residual_threshold"]
        == 0.025
    )
    assert captured["persist"] is True
    assert captured["surface_v2_spread"] == 0.15
    assert captured["surface_v2_persist"] is True
    assert captured["surface_v2_reused_structural"] == 12
