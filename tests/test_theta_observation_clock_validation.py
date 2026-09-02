from pathlib import Path

def test_runner_exposes_observation_clock_for_deterministic_runs():
    source = Path("src/research/independent_runner.py").read_text(encoding="utf-8")
    assert "observation_clock=None" in source
    assert "observation_clock()" in source
    assert "observation_clock must return a timezone-aware datetime." in source
