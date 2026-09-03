import json

import pytest

from src.database.repository import create_market_snapshot, get_connection
from src.research.local_surface_empirical_null_v1 import (
    LocalSurfaceEmpiricalNullError,
    NullSourceObservation,
    estimate_dependence,
    estimate_strata,
    fit_empirical_null_v1,
)


def make_source(*, i, right="C", dte=15, abs_delta=0.5, residual=0.0, date="2026-09-03"):
    return NullSourceObservation(
        observation_id=i,
        research_run_id=1,
        session_date=date,
        underlying="AAPL",
        expiration="2026-09-18",
        strike=90.0 + i,
        right=right,
        abs_delta=abs_delta,
        dte=dte,
        spread_to_mid=0.04,
        loo_residual=residual,
    )


def test_strata_use_robust_scale_and_shrink_sparse_cells_toward_parent():
    rows = []
    for i in range(100):
        rows.append(make_source(i=i, right="C", dte=15, abs_delta=0.5, residual=((i % 11) - 5) * 0.001))
    for i in range(100, 105):
        rows.append(make_source(i=i, right="C", dte=35, abs_delta=0.7, residual=0.05 + (i - 102) * 0.002))

    strata = {item.stratum_key: item for item in estimate_strata(rows)}
    sparse = strata["C|DTE_31_45|ABSDELTA_60_80"]

    assert sparse.observation_count == 5
    assert sparse.shrinkage_weight == pytest.approx(5 / 55)
    assert sparse.raw_median > sparse.parent_location
    assert sparse.parent_location < sparse.shrunk_location < sparse.raw_median
    assert sparse.raw_robust_scale >= 0
    assert sparse.q025 <= sparse.q50 <= sparse.q975


def test_empirical_null_refuses_tiny_discovery_sample():
    rows = [make_source(i=i, residual=i * 0.001) for i in range(20)]
    with pytest.raises(LocalSurfaceEmpiricalNullError, match="at least 100"):
        estimate_strata(rows)


def test_dependence_proxy_recognizes_repeated_contract_session_observations():
    rows = []
    # 20 contract/session clusters with five repeated observations each.
    for contract in range(20):
        for repeat in range(5):
            rows.append(
                NullSourceObservation(
                    observation_id=len(rows) + 1,
                    research_run_id=repeat + 1,
                    session_date="2026-09-03",
                    underlying="AAPL",
                    expiration="2026-09-18",
                    strike=90.0 + contract,
                    right="C",
                    abs_delta=0.5,
                    dte=15,
                    spread_to_mid=0.04,
                    loo_residual=contract * 0.002 + repeat * 0.0001,
                )
            )
    diagnostics = {item.cluster_dimension: item for item in estimate_dependence(rows)}
    contract = diagnostics["CONTRACT_SESSION"]
    assert contract.raw_observation_count == 100
    assert contract.cluster_count == 20
    assert contract.repeated_cluster_count == 20
    assert contract.mean_cluster_size == pytest.approx(5.0)
    assert contract.icc_oneway is not None
    assert contract.design_effect_proxy is not None and contract.design_effect_proxy >= 1.0
    assert contract.effective_n_proxy is not None
    assert 0 < contract.effective_n_proxy <= contract.raw_observation_count


def _quote(strike, right, delta):
    return {
        "provider_contract_id": f"THETA:{right}:{strike}",
        "option_symbol": None,
        "right": right,
        "strike": strike,
        "expiration": "2026-09-18",
        "quote_at": "2026-09-03T14:00:02",
        "bid": 4.9,
        "bid_source": "FETCHED",
        "bid_at": "2026-09-03T14:00:02",
        "ask": 5.1,
        "ask_source": "FETCHED",
        "ask_at": "2026-09-03T14:00:02",
        "last": None,
        "last_source": "UNKNOWN",
        "last_at": None,
        "implied_volatility": None,
        "iv_source": "UNKNOWN",
        "iv_at": None,
        "delta": delta if right == "C" else -delta,
        "delta_source": "FETCHED",
        "delta_at": "2026-09-03T14:00:02",
        "gamma": None,
        "gamma_source": "UNKNOWN",
        "gamma_at": None,
        "theta": None,
        "theta_source": "UNKNOWN",
        "theta_at": None,
        "vega": None,
        "vega_source": "UNKNOWN",
        "vega_at": None,
        "volume": 100,
        "volume_source": "FETCHED",
        "volume_at": "2026-09-03T14:00:02",
        "open_interest": 500,
        "open_interest_source": "FETCHED",
        "open_interest_at": "2026-09-03T14:00:02",
    }


def seed_v2_discovery_rows(db_path, *, session_date="2026-09-03", count=120):
    conn = get_connection(db_path)
    try:
        run_id = int(conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id, preregistration_hash, code_git_sha, started_at, ended_at,
                us_session_date, us_session_state, status
            ) VALUES ('NULL_TEST', 'hash', 'sha', ?, ?, ?, 'INTRADAY', 'COMPLETED');
            """,
            (f"{session_date}T18:00:00Z", f"{session_date}T18:01:00Z", session_date),
        ).lastrowid)
        conn.commit()
    finally:
        conn.close()

    quotes = []
    for i in range(count):
        right = "C" if i % 2 == 0 else "P"
        delta = 0.15 + (i % 60) / 100.0
        quotes.append(_quote(80.0 + i * 0.5, right, delta))
    snapshot_id = create_market_snapshot(
        {
            "captured_at": f"{session_date}T18:00:05Z",
            "underlying": "AAPL",
            "provider": "THETADATA",
            "research_run_id": run_id,
            "us_session_date": session_date,
            "us_session_state": "INTRADAY",
            "underlying_price": 100.0,
            "underlying_source": "FETCHED",
            "underlying_at": f"{session_date}T14:00:04",
            "fx_to_eur": None,
            "fx_source": "UNKNOWN",
            "fx_at": None,
        },
        quotes,
        db_path=db_path,
    )
    conn = get_connection(db_path)
    try:
        quote_rows = conn.execute("SELECT id, strike, right, delta FROM option_quotes WHERE snapshot_id = ? ORDER BY id;", (snapshot_id,)).fetchall()
        for row in quote_rows:
            conn.execute(
                """
                INSERT INTO listing_reference_contracts (
                    research_run_id, provider, underlying, provider_contract_id,
                    expiration, strike, right, observed_at, ingested_at
                ) VALUES (?, 'MASSIVE', 'AAPL', ?, '2026-09-18', ?, ?, ?, ?);
                """,
                (run_id, f"MASSIVE:{row['right']}:{row['strike']}", row["strike"], row["right"], f"{session_date}T18:00:00Z", f"{session_date}T18:00:00Z"),
            )
        model_run_id = int(conn.execute(
            """
            INSERT INTO local_surface_residual_v2_runs (
                research_run_id, model_family_id, model_version, fit_spec_version,
                config_hash, config_json, observed_at, structural_input_count,
                reference_mapped_count, evaluable_count, surfaced_count, decision_enabled
            ) VALUES (?, 'LOCAL_SURFACE_RESIDUAL_V2', '0.1.0', 'LOO_QUADRATIC_CENTERED_V1',
                      'cfg', '{}', ?, ?, ?, ?, 0, 0);
            """,
            (run_id, f"{session_date}T18:01:00Z", count, count, count),
        ).lastrowid)
        refs = conn.execute(
            "SELECT id, strike, right FROM listing_reference_contracts WHERE research_run_id = ? ORDER BY id;",
            (run_id,),
        ).fetchall()
        ref_by_key = {(float(r["strike"]), str(r["right"])): int(r["id"]) for r in refs}
        for i, row in enumerate(quote_rows):
            residual = ((i % 13) - 6) * 0.001 + (0.0005 if row["right"] == "P" else 0.0)
            conn.execute(
                """
                INSERT INTO local_surface_residual_v2_observations (
                    model_run_id, reference_contract_id, option_quote_id, underlying,
                    expiration, strike, right, delta, implied_volatility,
                    usable_strike_count, fit_point_count, fit_dof, fitted_iv,
                    loo_residual, abs_loo_residual, fit_sse, fit_rmse,
                    design_condition_number, observation_state, reason_code, evidence_json
                ) VALUES (?, ?, ?, 'AAPL', '2026-09-18', ?, ?, ?, 0.20,
                          10, 9, 6, 0.20, ?, ?, 0.001, 0.01, 10.0,
                          'EVALUATED_OBSERVATIONAL', 'LOO_QUADRATIC_RESIDUAL_MEASURED', '{}');
                """,
                (
                    model_run_id,
                    ref_by_key[(float(row["strike"]), str(row["right"]))],
                    int(row["id"]),
                    float(row["strike"]),
                    str(row["right"]),
                    float(row["delta"]),
                    residual,
                    abs(residual),
                ),
            )
        conn.commit()
        return run_id
    finally:
        conn.close()


def test_fit_uses_registered_discovery_dates_and_persists_firewalled_model(db_path):
    seed_v2_discovery_rows(db_path, session_date="2026-09-03", count=120)
    seed_v2_discovery_rows(db_path, session_date="2026-09-04", count=120)

    result = fit_empirical_null_v1(persist=True, db_path=db_path)
    assert result.observation_count == 120
    assert result.source_first_session_date == "2026-09-03"
    assert result.source_last_session_date == "2026-09-03"
    assert result.stratum_count > 1

    conn = get_connection(db_path)
    try:
        run = conn.execute("SELECT * FROM local_surface_null_v1_runs WHERE id = ?;", (result.null_run_id,)).fetchone()
        assert run["model_state"] == "ESTIMATED_DISCOVERY_ONLY"
        assert run["p_values_enabled"] == 0
        assert run["fdr_enabled"] == 0
        assert run["decision_enabled"] == 0
        assert conn.execute("SELECT COUNT(*) FROM local_surface_null_v1_membership WHERE null_run_id = ?;", (result.null_run_id,)).fetchone()[0] == 120
        view_count = conn.execute("SELECT COUNT(*) FROM v_local_surface_null_v1_discovery_membership WHERE null_run_id = ?;", (result.null_run_id,)).fetchone()[0]
        assert view_count == 120
    finally:
        conn.close()


def test_same_discovery_snapshot_cannot_be_persisted_twice(db_path):
    seed_v2_discovery_rows(db_path, count=120)
    first = fit_empirical_null_v1(persist=True, db_path=db_path)
    assert first.null_run_id is not None
    with pytest.raises(LocalSurfaceEmpiricalNullError, match="already persisted"):
        fit_empirical_null_v1(persist=True, db_path=db_path)
