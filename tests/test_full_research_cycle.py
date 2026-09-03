from dataclasses import dataclass

from src.providers.ecb_fx import (
    EcbFxObservation,
)
from src.research.full_research_cycle import (
    run_full_research_cycle,
)


@dataclass(frozen=True)
class FakeHypothesis:
    persisted_scanner_run_id: int = 9


@dataclass(frozen=True)
class FakeSurfaceV2:
    persisted_model_run_id: int = 999


@dataclass(frozen=True)
class FakeResearchCycle:
    hypothesis: FakeHypothesis = FakeHypothesis()
    surface_v2: FakeSurfaceV2 = FakeSurfaceV2()


@dataclass(frozen=True)
class FakeProposal:
    proposal_state: str
    persisted_proposal_id: int | None


@dataclass(frozen=True)
class FakeBridge:
    surfaced_count: int
    proposed_count: int
    blocked_count: int
    proposals: tuple


@dataclass(frozen=True)
class FakeAdmission:
    proposal_count: int = 1
    admitted_count: int = 1
    blocked_count: int = 0
    decisions: tuple = ()


def test_full_cycle_skips_fx_when_no_proposals(
    monkeypatch,
):
    calls = []

    def fake_cycle(**kwargs):
        calls.append("research_cycle")
        return FakeResearchCycle()

    def fake_bridge(**kwargs):
        calls.append(
            (
                "bridge",
                kwargs[
                    "hypothesis_scanner_run_id"
                ],
            )
        )
        return FakeBridge(
            surfaced_count=0,
            proposed_count=0,
            blocked_count=0,
            proposals=(),
        )

    def forbidden_fx():
        raise AssertionError(
            "FX must not be fetched when "
            "there are no proposals."
        )

    monkeypatch.setattr(
        "src.research.full_research_cycle."
        "run_research_cycle",
        fake_cycle,
    )

    monkeypatch.setattr(
        "src.research.full_research_cycle."
        "build_shadow_structure_proposals",
        fake_bridge,
    )

    result = run_full_research_cycle(
        symbols=["AAPL"],
        massive_client=object(),
        theta_client=object(),
        fx_fetcher=forbidden_fx,
    )

    assert result.fx_observation is None
    assert result.admission is None
    assert calls == [
        "research_cycle",
        ("bridge", 9),
    ]


def test_full_cycle_admits_only_persisted_proposals(
    monkeypatch,
):
    captured = {}

    def fake_cycle(**kwargs):
        return FakeResearchCycle()

    def fake_bridge(**kwargs):
        return FakeBridge(
            surfaced_count=3,
            proposed_count=2,
            blocked_count=1,
            proposals=(
                FakeProposal(
                    proposal_state="PROPOSED",
                    persisted_proposal_id=101,
                ),
                FakeProposal(
                    proposal_state="BLOCKED",
                    persisted_proposal_id=102,
                ),
                FakeProposal(
                    proposal_state="PROPOSED",
                    persisted_proposal_id=103,
                ),
            ),
        )

    fx = EcbFxObservation(
        provider="ECB",
        base_currency="EUR",
        quote_currency="USD",
        rate=1.20,
        reference_date="2026-09-01",
        observed_at=
            "2026-09-01T12:00:00Z",
        source_url=
            "https://example.test/ecb",
        provenance=
            "ECB_DAILY_REFERENCE_RATE",
    )

    def fake_admission(**kwargs):
        captured["proposal_ids"] = (
            kwargs["proposal_ids"]
        )
        captured["fx"] = kwargs["fx"]
        return FakeAdmission()

    monkeypatch.setattr(
        "src.research.full_research_cycle."
        "run_research_cycle",
        fake_cycle,
    )

    monkeypatch.setattr(
        "src.research.full_research_cycle."
        "build_shadow_structure_proposals",
        fake_bridge,
    )

    monkeypatch.setattr(
        "src.research.full_research_cycle."
        "admit_shadow_proposals",
        fake_admission,
    )

    result = run_full_research_cycle(
        symbols=["AAPL"],
        massive_client=object(),
        theta_client=object(),
        fx_fetcher=lambda: fx,
    )

    assert captured["proposal_ids"] == [
        101,
        103,
    ]
    assert captured["fx"] == fx
    assert result.admission.admitted_count == 1


def test_full_cycle_propagates_research_thresholds(
    monkeypatch,
):
    captured = {}

    def fake_cycle(**kwargs):
        captured.update(
            {
                "min_dte":
                    kwargs["min_dte"],
                "max_dte":
                    kwargs["max_dte"],
                "spread":
                    kwargs[
                        "max_spread_to_mid"
                    ],
                "residual":
                    kwargs[
                        "residual_threshold"
                    ],
            }
        )
        return FakeResearchCycle()

    monkeypatch.setattr(
        "src.research.full_research_cycle."
        "run_research_cycle",
        fake_cycle,
    )

    monkeypatch.setattr(
        "src.research.full_research_cycle."
        "build_shadow_structure_proposals",
        lambda **kwargs:
            FakeBridge(
                surfaced_count=0,
                proposed_count=0,
                blocked_count=0,
                proposals=(),
            ),
    )

    run_full_research_cycle(
        symbols=["AAPL"],
        massive_client=object(),
        theta_client=object(),
        min_dte=10,
        max_dte=30,
        max_spread_to_mid=0.12,
        residual_threshold=0.025,
        fx_fetcher=lambda:
            (_ for _ in ()).throw(
                AssertionError(
                    "FX should be skipped."
                )
            ),
    )

    assert captured == {
        "min_dte": 10,
        "max_dte": 30,
        "spread": 0.12,
        "residual": 0.025,
    }
