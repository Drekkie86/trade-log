from __future__ import annotations

from dataclasses import dataclass

import src.dashboard.research_command_deck_v1 as command_deck
from src.research.programme_family_governance_v1 import ProgrammeFamilyGovernanceError


@dataclass
class _FakeGovernance:
    payload: dict

    def as_dict(self) -> dict:
        return dict(self.payload)


def _runtime(*, ready: bool = True, daemon_state: str = "HEALTHY") -> dict:
    return {
        "ready": ready,
        "reason": None if ready else "TEST_NOT_READY",
        "daemon_health": {"state": daemon_state},
        "latest_iteration": {"status": "COMPLETED"},
        "prospective": {"independent_dates": 3},
    }


def test_unfrozen_programme_is_visible_without_stopping_existing_research(monkeypatch) -> None:
    monkeypatch.setattr(command_deck, "load_command_deck", lambda *args, **kwargs: _runtime())
    monkeypatch.setattr(
        command_deck,
        "load_programme_governance_snapshot",
        lambda *args, **kwargs: _FakeGovernance(
            {
                "activation_state": "BLOCKED_PROGRAMME_BUDGET_UNFROZEN",
                "activation_detail": "not frozen",
                "inference_state": "DISABLED_UNTIL_CALIBRATED",
                "budget_errors": [],
                "budget_warnings": [],
                "p_values_enabled": False,
                "fdr_enabled": False,
                "decision_enabled": False,
            }
        ),
    )

    state = command_deck.load_research_command_deck()

    assert state.ready is True
    assert state.operating_state == "COLLECTING_EXISTING_RESEARCH_ONLY"
    assert "opening a new edge family is blocked" in state.operating_detail


def test_invalid_governance_is_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(command_deck, "load_command_deck", lambda *args, **kwargs: _runtime())

    def _boom(*args, **kwargs):
        raise ProgrammeFamilyGovernanceError("budget file malformed")

    monkeypatch.setattr(command_deck, "load_programme_governance_snapshot", _boom)

    state = command_deck.load_research_command_deck()

    assert state.ready is False
    assert state.operating_state == "GOVERNANCE_FAILURE"
    assert state.governance["p_values_enabled"] is False
    assert state.governance["fdr_enabled"] is False
    assert state.governance["decision_enabled"] is False


def test_runtime_not_ready_takes_priority(monkeypatch) -> None:
    monkeypatch.setattr(command_deck, "load_command_deck", lambda *args, **kwargs: _runtime(ready=False))
    monkeypatch.setattr(
        command_deck,
        "load_programme_governance_snapshot",
        lambda *args, **kwargs: _FakeGovernance(
            {
                "activation_state": "ALLOWED_ONLY_FOR_FROZEN_ALLOCATED_FAMILIES",
                "inference_state": "DISABLED_UNTIL_CALIBRATED",
            }
        ),
    )

    state = command_deck.load_research_command_deck()

    assert state.ready is False
    assert state.operating_state == "RUNTIME_NOT_READY"


def test_degraded_daemon_is_not_hidden_by_governance(monkeypatch) -> None:
    monkeypatch.setattr(
        command_deck,
        "load_command_deck",
        lambda *args, **kwargs: _runtime(daemon_state="STALE"),
    )
    monkeypatch.setattr(
        command_deck,
        "load_programme_governance_snapshot",
        lambda *args, **kwargs: _FakeGovernance(
            {
                "activation_state": "ALLOWED_ONLY_FOR_FROZEN_ALLOCATED_FAMILIES",
                "inference_state": "DISABLED_UNTIL_CALIBRATED",
            }
        ),
    )

    state = command_deck.load_research_command_deck()

    assert state.operating_state == "RESEARCH_RUNTIME_DEGRADED"
    assert "STALE" in state.operating_detail
