import numpy as np

from research.detectability.simulate_detectability import (
    SimulationConfig,
    adaptive_block_length,
    benjamini_hochberg_rejections,
    calibrate_null,
    estimate_discovery_power,
    estimate_effective_n,
    estimate_power,
    moving_block_bootstrap_mean_ci,
    simulate_daily_paired_edges,
    simulate_pair_edges,
    simulate_underlying_day_paired_edges,
)


def _small(**kwargs):
    base = dict(
        days=30,
        effect_ru=0.03,
        monte_carlo_runs=50,
        calibration_runs=100,
        validation_runs=100,
        effective_n_runs=50,
        bootstrap_samples=100,
    )
    base.update(kwargs)
    return SimulationConfig(**base)


def test_simulator_returns_one_value_per_day():
    config = _small(days=30)
    daily = simulate_daily_paired_edges(config, np.random.default_rng(123))
    assert daily.shape == (30,)


def test_multi_underlying_shapes_are_explicit():
    config = _small(days=25, underlyings_per_day=3, pairs_per_day=4)
    rng = np.random.default_rng(9)
    pairs = simulate_pair_edges(config, rng)
    assert pairs.shape == (25, 3, 4)

    underlying = simulate_underlying_day_paired_edges(
        config,
        np.random.default_rng(9),
    )
    assert underlying.shape == (25, 3)


def test_injected_effect_moves_mean_in_expected_direction():
    low = _small(
        days=500,
        effect_ru=0.00,
        day_ar1=0.0,
        within_day_corr=0.5,
        cross_underlying_edge_corr=0.0,
        seed=1,
    )
    high = _small(
        days=500,
        effect_ru=0.10,
        day_ar1=0.0,
        within_day_corr=0.5,
        cross_underlying_edge_corr=0.0,
        seed=1,
    )

    low_values = simulate_daily_paired_edges(low, np.random.default_rng(999))
    high_values = simulate_daily_paired_edges(high, np.random.default_rng(999))

    difference = float(np.mean(high_values) - np.mean(low_values))
    assert 0.09 < difference < 0.11


def test_incremental_cost_reduces_expected_mean():
    free = _small(days=400, effect_ru=0.05, incremental_cost_mean_ru=0.0)
    costly = _small(
        days=400,
        effect_ru=0.05,
        incremental_cost_mean_ru=0.02,
        incremental_cost_sd_ru=0.0,
    )

    a = simulate_daily_paired_edges(free, np.random.default_rng(1234))
    b = simulate_daily_paired_edges(costly, np.random.default_rng(1234))
    assert np.isclose(float(np.mean(a - b)), 0.02, atol=1e-12)


def test_bootstrap_ci_contains_constant_mean():
    values = np.full(50, 0.04)
    lower, upper = moving_block_bootstrap_mean_ci(
        values,
        block_length=4,
        bootstrap_samples=200,
        rng=np.random.default_rng(7),
    )
    assert lower == 0.04
    assert upper == 0.04


def test_adaptive_block_length_scales_with_horizon():
    assert adaptive_block_length(20) == 3
    assert adaptive_block_length(40) == 3
    assert adaptive_block_length(60) == 4
    assert adaptive_block_length(120) == 5
    assert adaptive_block_length(250) == 6


def test_null_calibration_is_first_class_and_uses_synthetic_provenance():
    config = _small(days=40, effect_ru=0.0, seed=77)
    calibration = calibrate_null(config)

    assert calibration.parameters_source == "SYNTHETIC"
    assert calibration.block_length == adaptive_block_length(40)
    assert len(calibration.null_statistics) == config.calibration_runs
    assert 0.0 <= calibration.empirical_fpr <= 1.0


def test_20_day_null_fpr_is_calibrated_under_fixed_seed():
    config = SimulationConfig(
        days=20,
        effect_ru=0.0,
        monte_carlo_runs=50,
        calibration_runs=600,
        validation_runs=600,
        effective_n_runs=50,
        bootstrap_samples=150,
        seed=20260829,
    )
    calibration = calibrate_null(config)
    assert 0.015 <= calibration.empirical_fpr <= 0.040


def test_large_effect_has_more_power_than_null_after_calibration():
    null = _small(days=120, effect_ru=0.00, monte_carlo_runs=80, seed=10)
    calibration = calibrate_null(null)
    signal = _small(days=120, effect_ru=0.15, monte_carlo_runs=80, seed=10)

    null_result = estimate_power(null, calibration=calibration)
    signal_result = estimate_power(signal, calibration=calibration)
    assert signal_result["estimated_power"] > null_result["estimated_power"]


def test_bh_rejection_rule_matches_known_example():
    p = np.array([0.001, 0.010, 0.040, 0.20])
    rejected = benjamini_hochberg_rejections(p, q=0.05)
    assert rejected.tolist() == [True, True, False, False]


def test_multiplicity_can_be_simulated_with_false_discovery_reporting():
    config = _small(
        days=80,
        effect_ru=0.12,
        discovery_hypotheses_k=5,
        monte_carlo_runs=50,
        seed=555,
    )
    calibration = calibrate_null(_small(days=80, effect_ru=0.0, seed=555))
    result = estimate_discovery_power(config, calibration=calibration)

    assert result["k"] == 5.0
    assert 0.0 <= result["true_family_power"] <= 1.0
    assert result["mean_false_discoveries"] >= 0.0


def test_effective_n_is_bounded_by_nominal_n():
    config = _small(
        days=40,
        underlyings_per_day=3,
        pairs_per_day=5,
        effective_n_runs=80,
        seed=91,
    )
    result = estimate_effective_n(config)
    assert result.nominal_pair_observations == 600
    assert 1.0 <= result.effective_n <= 600.0
    assert 0.0 < result.efficiency_ratio <= 1.0


def test_lower_cross_underlying_correlation_buys_more_effective_n():
    low_corr = _small(
        days=80,
        underlyings_per_day=8,
        pairs_per_day=3,
        cross_underlying_edge_corr=0.0,
        day_ar1=0.0,
        effective_n_runs=180,
        seed=123,
    )
    high_corr = _small(
        days=80,
        underlyings_per_day=8,
        pairs_per_day=3,
        cross_underlying_edge_corr=0.9,
        day_ar1=0.0,
        effective_n_runs=180,
        seed=123,
    )

    low = estimate_effective_n(low_corr)
    high = estimate_effective_n(high_corr)
    assert low.effective_n > high.effective_n
