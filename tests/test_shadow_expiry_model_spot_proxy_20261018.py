"""Historical model-spot diagnostics never become validated trading outcomes."""
from __future__ import annotations

from src.research.shadow_expiry_model_spot_proxy_v1 import (
    PROXY_ROLE,
    select_model_spot_proxy,
    load_expiry_model_proxy_report,
)
from src.database.repository import get_connection
from tests.test_shadow_outcome_collector import seed_active_candidate
from tests.test_shadow_expiry_outcome_v1 import _insert_run, _insert_snapshot


CAPTURE = "2026-09-18T19:45:00Z"


def _rows(price=108.0, n=9):
    return [
        {
            "model_observation_id": i + 200,
            "option_quote_id": i + 100,
            "model_underlying_price": price,
            "ingested_at": "2026-09-18T19:44:58Z",
            "provider": "THETADATA",
            "source": "PROVIDER_DERIVED",
        }
        for i in range(n)
    ]


def test_same_provider_concordance_is_not_called_independent_price():
    x = select_model_spot_proxy(_rows(), captured_at=CAPTURE)
    assert x is not None and x["proxy_price"] == 108.0
    assert x["distinct_option_contracts"] == 9
    assert x["measurement_role"] == PROXY_ROLE
    assert "not independent" in x["disclaimer"]


def test_insufficient_distinct_contracts_rejected():
    assert select_model_spot_proxy(_rows(n=7),captured_at=CAPTURE) is None
    repeated = _rows()
    for r in repeated:
        r["option_quote_id"] = 1
    assert select_model_spot_proxy(repeated,captured_at=CAPTURE) is None


def test_stale_future_wrong_provider_and_disagreeing_models_rejected():
    data = _rows()
    for r in data:
        r["ingested_at"] = "2026-09-18T19:40:00Z"
    assert select_model_spot_proxy(data,captured_at=CAPTURE) is None
    data = _rows()
    data[0]["model_underlying_price"] = 125.0
    assert select_model_spot_proxy(data,captured_at=CAPTURE) is None
    data = _rows()
    data[0]["source"] = "UNKNOWN"
    assert select_model_spot_proxy(data,captured_at=CAPTURE) is not None
    for r in data:
        r["provider"] = "UNKNOWN"
    assert select_model_spot_proxy(data,captured_at=CAPTURE) is None


def test_read_only_expiry_model_proxy_resolves_candidate_without_mutating_source(db_path):
    candidate_id, _ = seed_active_candidate(db_path)
    c=get_connection(db_path)
    try:
        expiry_run = _insert_run(
            c,started="2026-09-18T19:45:00Z",session_date="2026-09-18"
        )
        snapshot = int(c.execute(
            """INSERT INTO market_snapshots(
                 captured_at,underlying,provider,research_run_id,
                 us_session_date,us_session_state,underlying_source,fx_source
                 ) VALUES (?,'AAPL','THETADATA',?,'2026-09-18',
                           'INTRADAY','UNKNOWN','UNKNOWN')""",
            (CAPTURE,expiry_run),
        ).lastrowid)
        for i in range(10):
            qid = c.execute(
                """INSERT INTO option_quotes(
                       snapshot_id,provider_contract_id,right,strike,expiration,
                       bid_source,ask_source,last_source,iv_source,delta_source,
                       gamma_source,theta_source,vega_source,volume_source,
                       open_interest_source
                   ) VALUES (?,?,'C',?,?,'UNKNOWN','UNKNOWN','UNKNOWN',
                             'UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN',
                             'UNKNOWN','UNKNOWN')""",
                (snapshot,f"THETA:EXPIRY_{i}",101.0+i,"2026-09-18"),
            ).lastrowid
            c.execute(
                """INSERT INTO provider_model_observations(
                   option_quote_id,provider,ingested_at,observed_at,
                   source,model_name,model_underlying_price,implied_volatility
                   ) VALUES (?,'THETADATA',?,'2026-09-18T15:44:58',
                             'PROVIDER_DERIVED','THETA_TEST',108.0,0.20)""",
                (qid,"2026-09-18T19:44:58Z"),
            )
        c.commit()
    finally:
        c.close()

    report=load_expiry_model_proxy_report(db_path=db_path,as_of_day="2026-09-21")
    assert report["modeled_proxy_count"] == 1
    row=report["rows"][0]
    assert row["candidate_id"] == candidate_id
    assert row["proxy_price"] == 108.0
    assert row["distinct_model_option_contracts"] == 10
    assert row["verified_trading_outcome"] is False
    assert row["modeled_net_pnl_usd_minor"] > 0

    c=get_connection(db_path)
    try:
        assert c.execute("SELECT underlying_price FROM market_snapshots WHERE id=?",(snapshot,)).fetchone()[0] is None
        assert c.execute("SELECT COUNT(*) FROM shadow_expiry_outcomes_v1").fetchone()[0] == 0
    finally:
        c.close()


def test_missing_expiry_snapshot_is_explicitly_unresolved(db_path):
    candidate_id,_=seed_active_candidate(db_path)
    report=load_expiry_model_proxy_report(db_path=db_path,as_of_day="2026-09-21")
    assert report["total_expired_admitted"] == 1
    assert report["modeled_proxy_count"] == 0
    assert report["unresolved_count"] == 1
    assert report["rows"][0]["candidate_id"] == candidate_id
    assert report["rows"][0]["reason_code"] == "NO_CONSISTENT_ASOF_PROVIDER_MODEL_SPOT"
