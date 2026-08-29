from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, replace
from typing import Iterable

import numpy as np


DEFAULT_NOMINAL_ALPHA = 0.025
DEFAULT_FDR_Q = 0.05


@dataclass(frozen=True)
class SimulationConfig:
    days: int
    effect_ru: float
    within_day_corr: float = 0.80
    cross_underlying_edge_corr: float = 0.50
    underlyings_per_day: int = 1
    day_ar1: float = 0.40
    student_t_df: float = 5.0
    pairs_per_day: int = 5
    idiosyncratic_scale: float = 0.20
    common_scale: float = 0.20
    incremental_cost_mean_ru: float = 0.0
    incremental_cost_sd_ru: float = 0.0
    bootstrap_block_length: int | None = None
    bootstrap_samples: int = 500
    monte_carlo_runs: int = 250
    calibration_runs: int = 600
    validation_runs: int = 600
    effective_n_runs: int = 300
    discovery_hypotheses_k: int = 1
    fdr_q: float = DEFAULT_FDR_Q
    nominal_alpha: float = DEFAULT_NOMINAL_ALPHA
    seed: int = 42
    parameters_source: str = "SYNTHETIC"
    cost_parameters_source: str = "SYNTHETIC_NONE"


@dataclass(frozen=True)
class NullCalibration:
    days: int
    critical_value: float
    empirical_fpr: float
    nominal_alpha: float
    block_length: int
    calibration_runs: int
    validation_runs: int
    parameters_source: str
    null_statistics: tuple[float, ...]


@dataclass(frozen=True)
class EffectiveNResult:
    nominal_pair_observations: int
    effective_n: float
    efficiency_ratio: float
    marginal_pair_variance: float
    grand_mean_variance: float
    underlyings_per_day: int
    pairs_per_day: int
    cross_underlying_edge_corr: float
    within_day_corr: float
    days: int
    parameters_source: str


def adaptive_block_length(days: int) -> int:
    """Scale the moving-block length with the number of session-days."""
    if days < 1:
        raise ValueError("days must be positive")
    return max(2, round(days ** (1.0 / 3.0)))


def resolved_block_length(config: SimulationConfig) -> int:
    block = (
        config.bootstrap_block_length
        if config.bootstrap_block_length is not None
        else adaptive_block_length(config.days)
    )
    return min(block, config.days)


def _validate(config: SimulationConfig) -> None:
    if config.days < 5:
        raise ValueError("days must be at least 5")
    if not -0.99 < config.day_ar1 < 0.99:
        raise ValueError("day_ar1 must be between -0.99 and 0.99")
    if not 0.0 <= config.within_day_corr < 1.0:
        raise ValueError("within_day_corr must be in [0, 1)")
    if not 0.0 <= config.cross_underlying_edge_corr < 1.0:
        raise ValueError("cross_underlying_edge_corr must be in [0, 1)")
    if config.underlyings_per_day < 1:
        raise ValueError("underlyings_per_day must be >= 1")
    if config.student_t_df <= 2:
        raise ValueError("student_t_df must exceed 2 for finite variance")
    if config.pairs_per_day < 1:
        raise ValueError("pairs_per_day must be >= 1")
    if config.idiosyncratic_scale < 0 or config.common_scale < 0:
        raise ValueError("noise scales must be non-negative")
    if config.incremental_cost_mean_ru < 0:
        raise ValueError("incremental_cost_mean_ru must be >= 0")
    if config.incremental_cost_sd_ru < 0:
        raise ValueError("incremental_cost_sd_ru must be >= 0")
    if config.incremental_cost_mean_ru == 0.0 and config.incremental_cost_sd_ru > 0.0:
        raise ValueError("positive cost SD requires a positive cost mean")
    if config.bootstrap_block_length is not None and config.bootstrap_block_length < 1:
        raise ValueError("bootstrap_block_length must be >= 1 when provided")
    if config.bootstrap_samples < 100:
        raise ValueError("bootstrap_samples should be >= 100")
    if config.monte_carlo_runs < 50:
        raise ValueError("monte_carlo_runs should be >= 50")
    if config.calibration_runs < 100:
        raise ValueError("calibration_runs should be >= 100")
    if config.validation_runs < 100:
        raise ValueError("validation_runs should be >= 100")
    if config.effective_n_runs < 50:
        raise ValueError("effective_n_runs should be >= 50")
    if config.discovery_hypotheses_k < 1:
        raise ValueError("discovery_hypotheses_k must be >= 1")
    if not 0.0 < config.fdr_q < 1.0:
        raise ValueError("fdr_q must be between 0 and 1")
    if not 0.0 < config.nominal_alpha < 0.5:
        raise ValueError("nominal_alpha must be between 0 and 0.5")
    if not config.parameters_source.strip():
        raise ValueError("parameters_source must be non-empty")
    if not config.cost_parameters_source.strip():
        raise ValueError("cost_parameters_source must be non-empty")


def _standardized_t(
    rng: np.random.Generator,
    df: float,
    size: int | tuple[int, ...],
) -> np.ndarray:
    raw = rng.standard_t(df, size=size)
    return raw / math.sqrt(df / (df - 2.0))


def _ar1_paths(
    rng: np.random.Generator,
    *,
    days: int,
    paths: int,
    phi: float,
    df: float,
) -> np.ndarray:
    innovations = _standardized_t(rng, df, (days, paths))
    values = np.zeros((days, paths), dtype=float)
    scale = math.sqrt(1.0 - phi**2)
    for day in range(days):
        previous = values[day - 1] if day else 0.0
        values[day] = phi * previous + scale * innovations[day]
    return values


def simulate_pair_edges(
    config: SimulationConfig,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Simulate paired candidate-minus-control edge observations in risk units.

    Shape is (session-day, underlying, candidate/control pair).

    `effect_ru` is the gross injected edge. A non-negative stochastic
    incremental cost draw is subtracted from every pair, so the observed
    paired edge is gross effect minus incremental costs plus noise.

    `cross_underlying_edge_corr` is a stress parameter for common variation in
    paired edge across names on the same date. It is deliberately a parameter
    of paired EDGE, not raw return correlation.

    This remains a synthetic stress-test model until parameters_source and
    cost_parameters_source identify empirical Christiania cohorts.
    """
    _validate(config)

    days = config.days
    u = config.underlyings_per_day
    p = config.pairs_per_day
    rho_x = config.cross_underlying_edge_corr
    rho_w = config.within_day_corr

    shared_regime = _ar1_paths(
        rng,
        days=days,
        paths=1,
        phi=config.day_ar1,
        df=config.student_t_df,
    )
    underlying_regime = _ar1_paths(
        rng,
        days=days,
        paths=u,
        phi=config.day_ar1,
        df=config.student_t_df,
    )
    regime = (
        math.sqrt(rho_x) * shared_regime
        + math.sqrt(1.0 - rho_x) * underlying_regime
    )

    shared_intraday = _standardized_t(
        rng,
        config.student_t_df,
        (days, 1, 1),
    )
    underlying_intraday = _standardized_t(
        rng,
        config.student_t_df,
        (days, u, 1),
    )
    underlying_shared = (
        math.sqrt(rho_x) * shared_intraday
        + math.sqrt(1.0 - rho_x) * underlying_intraday
    )

    pair_idio = _standardized_t(
        rng,
        config.student_t_df,
        (days, u, p),
    )
    pair_noise = (
        math.sqrt(rho_w) * underlying_shared
        + math.sqrt(1.0 - rho_w) * pair_idio
    )

    if config.incremental_cost_sd_ru == 0.0:
        costs = np.full(
            (days, u, p),
            config.incremental_cost_mean_ru,
            dtype=float,
        )
    else:
        # Gamma is non-negative and can be parameterized to have the requested
        # mean and SD exactly. This avoids truncation shifting the configured
        # expected cost upward.
        shape = (config.incremental_cost_mean_ru / config.incremental_cost_sd_ru) ** 2
        scale = (config.incremental_cost_sd_ru**2) / config.incremental_cost_mean_ru
        costs = rng.gamma(shape, scale, size=(days, u, p))

    return (
        config.effect_ru
        - costs
        + config.common_scale * regime[:, :, None]
        + config.idiosyncratic_scale * pair_noise
    )


def simulate_underlying_day_paired_edges(
    config: SimulationConfig,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return one paired-edge mean per session-day and underlying."""
    return simulate_pair_edges(config, rng).mean(axis=2)


def simulate_daily_paired_edges(
    config: SimulationConfig,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return one portfolio-level paired-edge mean per session-day."""
    return simulate_underlying_day_paired_edges(config, rng).mean(axis=1)


def moving_block_bootstrap_mean_ci(
    daily_values: np.ndarray,
    *,
    block_length: int,
    bootstrap_samples: int,
    rng: np.random.Generator,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Legacy-compatible percentile moving-block bootstrap CI."""
    values = np.asarray(daily_values, dtype=float)
    if values.ndim != 1:
        raise ValueError("daily_values must be one-dimensional")
    if len(values) < 2:
        raise ValueError("at least two daily values are required")
    if block_length < 1:
        raise ValueError("block_length must be >= 1")

    n = len(values)
    block_length = min(block_length, n)
    max_start = n - block_length
    blocks_needed = math.ceil(n / block_length)

    starts = rng.integers(
        0,
        max_start + 1,
        size=(bootstrap_samples, blocks_needed),
    )
    offsets = np.arange(block_length)
    indices = starts[..., None] + offsets
    sampled = values[indices.reshape(bootstrap_samples, -1)[:, :n]]
    boot_means = sampled.mean(axis=1)

    lower = float(np.quantile(boot_means, alpha / 2.0))
    upper = float(np.quantile(boot_means, 1.0 - alpha / 2.0))
    return lower, upper


def lower_bound_statistic(
    daily_values: np.ndarray,
    *,
    block_length: int,
    bootstrap_samples: int,
    rng: np.random.Generator,
    nominal_alpha: float,
) -> float:
    """
    Dependence-aware statistic whose critical value is calibrated under H0.
    """
    lower, _ = moving_block_bootstrap_mean_ci(
        daily_values,
        block_length=block_length,
        bootstrap_samples=bootstrap_samples,
        rng=rng,
        alpha=2.0 * nominal_alpha,
    )
    return lower


def _single_statistic(
    config: SimulationConfig,
    *,
    run_seed: int,
) -> float:
    rng = np.random.default_rng(run_seed)
    daily = simulate_daily_paired_edges(config, rng)
    stat_rng = np.random.default_rng(run_seed ^ 0x5DEECE66D)
    return lower_bound_statistic(
        daily,
        block_length=resolved_block_length(config),
        bootstrap_samples=config.bootstrap_samples,
        rng=stat_rng,
        nominal_alpha=config.nominal_alpha,
    )


def calibrate_null(config: SimulationConfig) -> NullCalibration:
    """Self-calibrate the decision threshold under a synthetic H0."""
    _validate(config)
    # H0 is zero NET edge, not zero gross edge. With costs present, the gross
    # effect required for zero expected net edge equals the configured mean
    # incremental cost.
    null_config = replace(config, effect_ru=config.incremental_cost_mean_ru)

    calibration_rng = np.random.default_rng(config.seed ^ 0xA5A5A5A5)
    calibration_stats = np.empty(config.calibration_runs, dtype=float)

    for i in range(config.calibration_runs):
        run_seed = int(calibration_rng.integers(0, 2**63 - 1))
        calibration_stats[i] = _single_statistic(
            null_config,
            run_seed=run_seed,
        )

    critical_value = float(
        np.quantile(
            calibration_stats,
            1.0 - config.nominal_alpha,
            method="higher",
        )
    )

    validation_rng = np.random.default_rng(config.seed ^ 0xC3C3C3C3)
    false_positives = 0

    for _ in range(config.validation_runs):
        run_seed = int(validation_rng.integers(0, 2**63 - 1))
        statistic = _single_statistic(
            null_config,
            run_seed=run_seed,
        )
        if statistic > critical_value:
            false_positives += 1

    empirical_fpr = false_positives / config.validation_runs

    return NullCalibration(
        days=config.days,
        critical_value=critical_value,
        empirical_fpr=empirical_fpr,
        nominal_alpha=config.nominal_alpha,
        block_length=resolved_block_length(config),
        calibration_runs=config.calibration_runs,
        validation_runs=config.validation_runs,
        parameters_source=config.parameters_source,
        null_statistics=tuple(float(x) for x in np.sort(calibration_stats)),
    )


def empirical_one_sided_p_value(
    statistic: float,
    calibration: NullCalibration,
) -> float:
    """Finite-sample empirical upper-tail p-value from null calibration stats."""
    null_stats = np.asarray(calibration.null_statistics, dtype=float)
    exceedances = int(np.count_nonzero(null_stats >= statistic))
    return (exceedances + 1.0) / (len(null_stats) + 1.0)


def benjamini_hochberg_rejections(
    p_values: np.ndarray,
    *,
    q: float,
) -> np.ndarray:
    """Return a boolean rejection mask using Benjamini-Hochberg FDR control."""
    p = np.asarray(p_values, dtype=float)
    if p.ndim != 1 or len(p) == 0:
        raise ValueError("p_values must be a non-empty one-dimensional array")
    if not np.all((0.0 <= p) & (p <= 1.0)):
        raise ValueError("p_values must lie in [0, 1]")
    if not 0.0 < q < 1.0:
        raise ValueError("q must lie in (0, 1)")

    order = np.argsort(p)
    ranked = p[order]
    thresholds = q * np.arange(1, len(p) + 1) / len(p)
    passing = np.flatnonzero(ranked <= thresholds)
    rejected = np.zeros(len(p), dtype=bool)
    if len(passing):
        cutoff = ranked[passing[-1]]
        rejected = p <= cutoff
    return rejected


def estimate_power(
    config: SimulationConfig,
    *,
    calibration: NullCalibration | None = None,
) -> dict[str, float | str]:
    """Estimate single pre-specified-hypothesis detection probability."""
    _validate(config)
    calibration = calibration or calibrate_null(config)

    if calibration.days != config.days:
        raise ValueError("calibration days do not match config days")
    if calibration.parameters_source != config.parameters_source:
        raise ValueError("calibration parameter source does not match config")

    master_rng = np.random.default_rng(config.seed ^ 0x7F7F7F7F)
    detections = 0
    observed_means: list[float] = []

    for _ in range(config.monte_carlo_runs):
        run_seed = int(master_rng.integers(0, 2**63 - 1))
        rng = np.random.default_rng(run_seed)
        daily = simulate_daily_paired_edges(config, rng)
        observed_means.append(float(np.mean(daily)))

        stat_rng = np.random.default_rng(run_seed ^ 0x5DEECE66D)
        statistic = lower_bound_statistic(
            daily,
            block_length=calibration.block_length,
            bootstrap_samples=config.bootstrap_samples,
            rng=stat_rng,
            nominal_alpha=config.nominal_alpha,
        )

        if statistic > calibration.critical_value:
            detections += 1

    return {
        "days": float(config.days),
        "effect_ru": config.effect_ru,
        "estimated_power": detections / config.monte_carlo_runs,
        "mean_observed_effect_ru": float(np.mean(observed_means)),
        "expected_net_effect_ru": config.effect_ru - config.incremental_cost_mean_ru,
        "empirical_fpr": calibration.empirical_fpr,
        "nominal_alpha": calibration.nominal_alpha,
        "block_length": float(calibration.block_length),
        "parameters_source": config.parameters_source,
        "cost_parameters_source": config.cost_parameters_source,
    }


def estimate_discovery_power(
    config: SimulationConfig,
    *,
    calibration: NullCalibration | None = None,
) -> dict[str, float]:
    """
    Estimate discovery probability for one true family among k tested families.

    Family 0 receives config.effect_ru. Remaining families receive zero gross
    edge. Empirical p-values come from the calibrated null distribution and BH
    is applied within each simulated discovery experiment.
    """
    _validate(config)
    calibration = calibration or calibrate_null(config)
    k = config.discovery_hypotheses_k
    master_rng = np.random.default_rng(config.seed ^ 0xD4D4D4D4)

    true_family_detected = 0
    any_discovery = 0
    false_discoveries = 0
    total_discoveries = 0

    for _ in range(config.monte_carlo_runs):
        p_values = np.empty(k, dtype=float)
        for family in range(k):
            family_effect = (
                config.effect_ru
                if family == 0
                else config.incremental_cost_mean_ru
            )
            family_config = replace(config, effect_ru=family_effect)
            run_seed = int(master_rng.integers(0, 2**63 - 1))
            statistic = _single_statistic(family_config, run_seed=run_seed)
            p_values[family] = empirical_one_sided_p_value(
                statistic,
                calibration,
            )

        rejected = benjamini_hochberg_rejections(p_values, q=config.fdr_q)
        discoveries = int(rejected.sum())
        total_discoveries += discoveries
        false_discoveries += int(rejected[1:].sum())
        true_family_detected += int(rejected[0])
        any_discovery += int(discoveries > 0)

    return {
        "k": float(k),
        "fdr_q": config.fdr_q,
        "true_family_power": true_family_detected / config.monte_carlo_runs,
        "probability_any_discovery": any_discovery / config.monte_carlo_runs,
        "mean_false_discoveries": false_discoveries / config.monte_carlo_runs,
        "mean_total_discoveries": total_discoveries / config.monte_carlo_runs,
    }


def estimate_effective_n(config: SimulationConfig) -> EffectiveNResult:
    """
    Estimate iid-equivalent sample size via a variance ratio.

    N_eff = marginal variance of one paired observation / variance of the
    grand mean across the full dependent panel. The nominal count is
    days × underlyings × pairs. This intentionally quantifies how much nominal
    breadth is lost to within-day, cross-underlying, and temporal dependence.
    """
    _validate(config)
    null_config = replace(config, effect_ru=0.0, incremental_cost_mean_ru=0.0)
    rng = np.random.default_rng(config.seed ^ 0xE5E5E5E5)
    grand_means = np.empty(config.effective_n_runs, dtype=float)
    marginal_samples: list[float] = []

    for i in range(config.effective_n_runs):
        run_seed = int(rng.integers(0, 2**63 - 1))
        pairs = simulate_pair_edges(
            null_config,
            np.random.default_rng(run_seed),
        )
        grand_means[i] = float(pairs.mean())
        marginal_samples.extend(pairs.ravel()[: min(32, pairs.size)].tolist())

    marginal_var = float(np.var(marginal_samples, ddof=1))
    grand_mean_var = float(np.var(grand_means, ddof=1))
    nominal_n = config.days * config.underlyings_per_day * config.pairs_per_day

    effective_n = (
        marginal_var / grand_mean_var if grand_mean_var > 0.0 else float(nominal_n)
    )
    effective_n = min(max(effective_n, 1.0), float(nominal_n))

    return EffectiveNResult(
        nominal_pair_observations=nominal_n,
        effective_n=effective_n,
        efficiency_ratio=effective_n / nominal_n,
        marginal_pair_variance=marginal_var,
        grand_mean_variance=grand_mean_var,
        underlyings_per_day=config.underlyings_per_day,
        pairs_per_day=config.pairs_per_day,
        cross_underlying_edge_corr=config.cross_underlying_edge_corr,
        within_day_corr=config.within_day_corr,
        days=config.days,
        parameters_source=config.parameters_source,
    )


def calibration_grid(
    *,
    days_values: Iterable[int],
    base: SimulationConfig,
) -> dict[int, NullCalibration]:
    calibrations: dict[int, NullCalibration] = {}
    for days in days_values:
        config = replace(
            base,
            days=days,
            effect_ru=0.0,
            seed=base.seed + days,
        )
        calibrations[days] = calibrate_null(config)
    return calibrations


def grid(
    *,
    days_values: Iterable[int],
    effect_values: Iterable[float],
    base: SimulationConfig,
) -> list[dict[str, float | str]]:
    days_values = list(days_values)
    calibrations = calibration_grid(days_values=days_values, base=base)

    results: list[dict[str, float | str]] = []
    for days in days_values:
        calibration = calibrations[days]
        for effect in effect_values:
            config = replace(
                base,
                days=days,
                effect_ru=effect,
                seed=base.seed + days + int(effect * 10000),
            )
            results.append(estimate_power(config, calibration=calibration))
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Christiania Detectability v0.2 Pass 2. Synthetic, null-calibrated "
            "stress test with costs, multiplicity, effective N and breadth."
        )
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use fewer runs for a fast smoke test.",
    )
    return parser.parse_args()


def _print_cost_scenarios(base: SimulationConfig, quick: bool) -> None:
    print("COST SENSITIVITY — GROSS EDGE 0.050 RU, 120 DAYS")
    print("cost_mean  cost_sd  expected_net  est_power")
    for cost_mean, cost_sd in [(0.000, 0.000), (0.010, 0.005), (0.025, 0.010), (0.040, 0.015)]:
        cfg = replace(
            base,
            days=120,
            effect_ru=0.050,
            incremental_cost_mean_ru=cost_mean,
            incremental_cost_sd_ru=cost_sd,
            cost_parameters_source="SYNTHETIC_COST_SCENARIO",
            monte_carlo_runs=(100 if quick else 350),
            seed=base.seed + 120,
        )
        cal = calibrate_null(cfg)
        result = estimate_power(cfg, calibration=cal)
        print(
            f"{cost_mean:9.3f}  {cost_sd:7.3f}  "
            f"{float(result['expected_net_effect_ru']):12.3f}  "
            f"{float(result['estimated_power']):9.3f}"
        )


def _print_effective_n_surface(base: SimulationConfig, quick: bool) -> None:
    print("EFFECTIVE-N SURFACE — 120 DAYS, 5 PAIRS/UNDERLYING/DAY")
    print("underlyings  cross_corr  nominal_N  effective_N  efficiency")
    for u in [1, 2, 5, 10]:
        for rho_x in [0.0, 0.3, 0.6, 0.9]:
            cfg = replace(
                base,
                days=120,
                underlyings_per_day=u,
                cross_underlying_edge_corr=rho_x,
                pairs_per_day=5,
                effective_n_runs=(100 if quick else 350),
                seed=base.seed + 1000 * u + int(rho_x * 100),
            )
            result = estimate_effective_n(cfg)
            print(
                f"{u:11d}  {rho_x:10.2f}  "
                f"{result.nominal_pair_observations:9d}  "
                f"{result.effective_n:11.1f}  "
                f"{result.efficiency_ratio:10.3f}"
            )


def _print_multiplicity(base: SimulationConfig, quick: bool) -> None:
    print("DISCOVERY MULTIPLICITY — ONE TRUE FAMILY, 120 DAYS, GROSS EDGE 0.050 RU")
    print("k  fdr_q  true_family_power  mean_false_discoveries")
    for k in [1, 5, 10, 20]:
        cfg = replace(
            base,
            days=120,
            effect_ru=0.050,
            discovery_hypotheses_k=k,
            fdr_q=0.05,
            monte_carlo_runs=(80 if quick else 250),
            calibration_runs=(600 if quick else 1200),
            validation_runs=(400 if quick else 800),
            bootstrap_samples=(150 if quick else 350),
            seed=base.seed + 5000 + k,
        )
        calibration = calibrate_null(cfg)
        result = estimate_discovery_power(cfg, calibration=calibration)
        print(
            f"{k:2d}  {result['fdr_q']:5.2f}  "
            f"{result['true_family_power']:17.3f}  "
            f"{result['mean_false_discoveries']:22.3f}"
        )


def main() -> int:
    args = parse_args()

    base = SimulationConfig(
        days=20,
        effect_ru=0.0,
        monte_carlo_runs=(100 if args.quick else 450),
        calibration_runs=(300 if args.quick else 1000),
        validation_runs=(300 if args.quick else 1000),
        bootstrap_samples=(180 if args.quick else 450),
        effective_n_runs=(100 if args.quick else 350),
        parameters_source="SYNTHETIC",
        cost_parameters_source="SYNTHETIC_NONE",
    )

    day_grid = [20, 40, 60, 120, 250]
    effect_grid = [0.00, 0.01, 0.02, 0.03, 0.05, 0.10]

    print("Christiania Detectability Study v0.2 — Pass 2")
    print("NULL-CALIBRATED SYNTHETIC STRESS TEST")
    print("NOT an empirical edge or MDE estimate")
    print(f"PARAMETERS_SOURCE={base.parameters_source}")
    print(f"COST_PARAMETERS_SOURCE={base.cost_parameters_source}")
    print(f"NOMINAL_ONE_SIDED_ALPHA={base.nominal_alpha:.3f}")
    print()

    calibrations = calibration_grid(days_values=day_grid, base=base)

    print("NULL CALIBRATION")
    print("days  block  nominal_alpha  empirical_fpr  critical_value")
    for days in day_grid:
        cal = calibrations[days]
        print(
            f"{days:4d}  {cal.block_length:5d}  "
            f"{cal.nominal_alpha:13.3f}  "
            f"{cal.empirical_fpr:13.3f}  "
            f"{cal.critical_value:14.5f}"
        )

    print()
    print("POWER CONDITIONAL ON SYNTHETIC PARAMETERS — ZERO INCREMENTAL COST")
    print("days  gross_effect_ru  est_power  empirical_fpr  mean_observed_ru")
    for days in day_grid:
        calibration = calibrations[days]
        for effect in effect_grid:
            cfg = replace(
                base,
                days=days,
                effect_ru=effect,
                seed=base.seed + days + int(effect * 10000),
            )
            result = estimate_power(cfg, calibration=calibration)
            print(
                f"{days:4d}  {effect:15.3f}  "
                f"{float(result['estimated_power']):9.3f}  "
                f"{float(result['empirical_fpr']):13.3f}  "
                f"{float(result['mean_observed_effect_ru']):16.4f}"
            )

    print()
    _print_cost_scenarios(base, args.quick)
    print()
    _print_effective_n_surface(base, args.quick)
    print()
    _print_multiplicity(base, args.quick)

    print()
    print("INTERPRETATION GUARD")
    print("All outputs remain conditional on synthetic noise/cost/correlation inputs.")
    print("No real-market MDE claim is permitted until those inputs are estimated from empirical cohorts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
