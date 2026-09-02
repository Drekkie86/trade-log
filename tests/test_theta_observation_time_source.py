from pathlib import Path

def test_runner_uses_per_underlying_theta_observation_time():
    source = Path("src/research/independent_runner.py").read_text(encoding="utf-8")
    assert "theta_quote_observed_at = (" in source
    assert "observation_clock()" in source
    assert "else datetime.now(NY)" in source
    assert "observed_at=theta_quote_observed_at" in source
    assert "captured_at=theta_quote_observed_at" in source
    assert "observed_at=theta_quote_observed_utc" in source

def test_live_join_does_not_use_cycle_start_observed_at():
    source = Path("src/research/independent_runner.py").read_text(encoding="utf-8")
    a = source.index("joined = build_live_join(")
    b = source.index("diagnostics = diagnose_admission(", a)
    block = source[a:b]
    assert "observed_at=observed_at" not in block
    assert "observed_at=theta_quote_observed_at" in block
