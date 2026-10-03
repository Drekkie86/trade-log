from __future__ import annotations

from types import SimpleNamespace

import quality_gate


def test_shared_runner_runtime_overrun_is_advisory(monkeypatch):
    monkeypatch.setenv("CHRISTIANIA_CORE_TEST_ADVISORY_SECONDS", "240")
    monkeypatch.setenv("CHRISTIANIA_SLOW_TEST_ADVISORY_SECONDS", "30")

    monkeypatch.setattr(
        quality_gate,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    samples = iter([0.0, 500.0, 500.0, 600.0])
    monkeypatch.setattr(
        quality_gate.time,
        "perf_counter",
        lambda: next(samples),
    )

    result = quality_gate.run_pytest()

    assert result.ok is True
    assert "core=500.00s" in result.detail
    assert "slow=100.00s" in result.detail
    assert "runtime advisory only" in result.detail
    assert "exceeded advisory 240.00s" in result.detail
    assert "exceeded advisory 30.00s" in result.detail


def test_pytest_failure_still_fails_even_when_runtime_is_advisory(monkeypatch):
    monkeypatch.setenv("CHRISTIANIA_CORE_TEST_ADVISORY_SECONDS", "240")
    monkeypatch.setenv("CHRISTIANIA_SLOW_TEST_ADVISORY_SECONDS", "30")

    monkeypatch.setattr(
        quality_gate,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )

    samples = iter([0.0, 1.0])
    monkeypatch.setattr(
        quality_gate.time,
        "perf_counter",
        lambda: next(samples),
    )

    result = quality_gate.run_pytest()

    assert result.ok is False
    assert "core pytest population failed" in result.detail
