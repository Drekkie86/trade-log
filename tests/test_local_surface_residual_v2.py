import json

import pytest

from src.database.provider_evidence import create_provider_model_observation
from src.database.repository import create_market_snapshot, get_connection
from src.research.local_surface_residual_v2 import scan_local_surface_residual_v2


def create_completed_run(db_path):
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO research_runs (
                cohort_id, preregistration_hash, code_git_sha, started_at, ended_at,
                us_session_date, us_session_state, status
            ) VALUES (
                'INDEPENDENT_RESEARCH_RUNNER_V1', 'hash', 'sha',
                '2026-09-03T18:00:00Z', '2026-09-03T18:01:00Z',
                '2026-09-03', 'INTRADAY', 'COMPLETED'
            );
            """
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def add_contract(*, db_path, run_id, strike, iv, delta=0.5):
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO listing_reference_contracts (
                research_run_id, provider, underlying, provider_contract_id,
                expiration, strike, right, observed_at, ingested_at
            ) VALUES (?, 'MASSIVE', 'AAPL', ?, '2026-09-18', ?, 'C',
                      '2026-09-03T18:00:00Z', '2026-09-03T18:00:00Z');
            """,
            (run_id, f"MASSIVE:{strike}", strike),
        )
        reference_id = int(cursor.lastrowid)
        conn.commit()
    finally:
        conn.close()

    snapshot_id = create_market_snapshot(
        {
            "captured_at": "2026-09-03T18:00:05Z",
            "underlying": "AAPL",
            "provider": "THETADATA",
            "research_run_id": run_id,
            "us_session_date": "2026-09-03",
            "us_session_state": "INTRADAY",
            "underlying_price": 100.0,
            "underlying_source": "FETCHED",
            "underlying_at": "2026-09-03T14:00:04",
            "fx_to_eur": None,
            "fx_source": "UNKNOWN",
            "fx_at": None,
        },
        [{
            "provider_contract_id": f"THETA:{strike}",
            "option_symbol": None,
            "right": "C",
            "strike": strike,
            "expiration": "2026-09-18",
            "quote_at": "2026-09-03T14:00:02",
            "bid": 4.9,
            "bid_source": "FETCHED",
            "bid_at": "2026-09-03T14:00:02",
            "ask": 5.1,
            "ask_source": "FETCHED",
            "ask_at": "2026-09-03T14:00:02",
            "last": None, "last_source": "UNKNOWN", "last_at": None,
            "implied_volatility": None, "iv_source": "UNKNOWN", "iv_at": None,
            "delta": delta, "delta_source": "FETCHED", "delta_at": "2026-09-03T14:00:02",
            "gamma": None, "gamma_source": "UNKNOWN", "gamma_at": None,
            "theta": None, "theta_source": "UNKNOWN", "theta_at": None,
            "vega": None, "vega_source": "UNKNOWN", "vega_at": None,
            "volume": 100, "volume_source": "FETCHED", "volume_at": "2026-09-03T14:00:02",
            "open_interest": 500, "open_interest_source": "FETCHED", "open_interest_at": "2026-09-03T14:00:02",
        }],
        db_path=db_path,
    )
    conn = get_connection(db_path)
    try:
        quote_id = int(conn.execute("SELECT id FROM option_quotes WHERE snapshot_id = ?;", (snapshot_id,)).fetchone()[0])
    finally:
        conn.close()

    create_provider_model_observation(
        option_quote_id=quote_id,
        provider="THETADATA",
        implied_volatility=iv,
        delta=delta,
        gamma=None,
        theta=None,
        vega=None,
        ingested_at="2026-09-03T18:00:05Z",
        observed_at="2026-09-03T14:00:02",
        model_input_notes=json.dumps({"iv_error": 0}),
        db_path=db_path,
    )
    return reference_id, quote_id


def true_iv(strike):
    return 0.20 + 0.001 * (strike - 97.5) ** 2


def test_loo_quadratic_residual_excludes_target_from_its_own_fit(db_path):
    run_id = create_completed_run(db_path)
    for strike in (95, 96, 97, 98, 99, 100):
        iv = true_iv(strike)
        if strike == 98:
            iv += 0.04
        add_contract(db_path=db_path, run_id=run_id, strike=strike, iv=iv)

    result = scan_local_surface_residual_v2(research_run_id=run_id, persist=True, db_path=db_path)
    target = next(item for item in result.observations if item.strike == 98)

    assert target.observation_state == "EVALUATED_OBSERVATIONAL"
    assert target.fit_point_count == 5
    assert target.fit_dof == 2
    assert target.fitted_iv == pytest.approx(true_iv(98), abs=1e-12)
    assert target.loo_residual == pytest.approx(0.04, abs=1e-12)
    assert target.abs_loo_residual == pytest.approx(0.04, abs=1e-12)
    assert result.evaluable_count == 6


def test_v2_persists_no_surface_decision_or_p_value(db_path):
    run_id = create_completed_run(db_path)
    for strike in (95, 96, 97, 98, 99):
        add_contract(db_path=db_path, run_id=run_id, strike=strike, iv=true_iv(strike))

    result = scan_local_surface_residual_v2(research_run_id=run_id, persist=True, db_path=db_path)
    conn = get_connection(db_path)
    try:
        run = conn.execute("SELECT * FROM local_surface_residual_v2_runs WHERE id = ?;", (result.persisted_model_run_id,)).fetchone()
        assert run["surfaced_count"] == 0
        assert run["decision_enabled"] == 0
        row = conn.execute("SELECT * FROM local_surface_residual_v2_observations WHERE model_run_id = ? LIMIT 1;", (result.persisted_model_run_id,)).fetchone()
        evidence = json.loads(row["evidence_json"])
        assert evidence["surface_classification"] is False
        assert evidence["p_value"] is None
        assert evidence["fdr_decision"] is None
        assert "SURFACED" not in row["observation_state"]
    finally:
        conn.close()


def test_v2_requires_at_least_five_usable_strikes_for_one_df_or_more(db_path):
    run_id = create_completed_run(db_path)
    for strike in (95, 96, 97, 98):
        add_contract(db_path=db_path, run_id=run_id, strike=strike, iv=true_iv(strike))

    result = scan_local_surface_residual_v2(research_run_id=run_id, persist=False, db_path=db_path)
    assert result.evaluable_count == 0
    assert {item.reason_code for item in result.observations} == {"INSUFFICIENT_USABLE_STRIKES"}


def test_discovery_view_exposes_null_model_covariates(db_path):
    run_id = create_completed_run(db_path)
    for strike in (95, 96, 97, 98, 99):
        add_contract(db_path=db_path, run_id=run_id, strike=strike, iv=true_iv(strike))
    scan_local_surface_residual_v2(research_run_id=run_id, persist=True, db_path=db_path)

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM v_local_surface_residual_v2_discovery_dataset WHERE research_run_id = ? AND strike = 97;",
            (run_id,),
        ).fetchone()
        assert row["underlying"] == "AAPL"
        assert row["dte"] == 15
        assert row["spread_to_mid"] == pytest.approx(0.04)
        assert row["fit_dof"] == 1
        assert "loo_residual" in row.keys()
        assert "greek_age_seconds" in row.keys()
    finally:
        conn.close()
