"""Historical model-spot diagnostics never become validated trading outcomes."""
from __future__ import annotations

from src.research.shadow_expiry_model_spot_proxy_v1 import (
    PROXY_ROLE,
    select_model_spot_proxy,
    load_expiry_model_proxy_report,
    modeled_expiry_payoff_mechanism,
    _economic_bet_key,
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
    assert row["modeled_payoff_mechanism"] == "MODELED_NET_POSITIVE_AFTER_FEES"
    assert row["gross_after_entry_spread_before_fees_usd_minor"] == (
        row["entry_cashflow_usd_minor"] + row["terminal_intrinsic_usd_minor"]
    )
    assert report["distinct_economic_bet_shapes"] == 1
    assert report["modeled_payoff_mechanism_counts"] == {
        "MODELED_NET_POSITIVE_AFTER_FEES": 1
    }
    assert sum(report["modeled_structure_family_counts"].values()) == 1

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


def test_shadow_lab_proxy_table_exposes_original_capture_time_in_local_timezone():
    """A proxy's age must be visible alongside its candidate and source snapshot."""
    from pathlib import Path
    from src.ui.datetime_display import format_local_datetime

    app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8"
    )
    assert '"Source captured (Brussels)": format_local_datetime(' in app_source
    assert 'r.get("snapshot_captured_at")' in app_source
    assert format_local_datetime("2026-10-16T19:45:00Z") == (
        "16 Oct 2026, 21:45 CEST"
    )



def test_proxy_loss_mechanisms_do_not_confuse_spread_with_fees():
    classify = modeled_expiry_payoff_mechanism
    assert classify(entry_cashflow_usd_minor=-700, terminal_intrinsic_usd_minor=600,
                    assumed_fees_usd_minor=24) == "GROSS_LOSS_AFTER_ENTRY_SPREAD_BEFORE_FEES"
    assert classify(entry_cashflow_usd_minor=-500, terminal_intrinsic_usd_minor=500,
                    assumed_fees_usd_minor=24) == "ZERO_GROSS_PAYOFF_ERODED_BY_FEES"
    assert classify(entry_cashflow_usd_minor=-450, terminal_intrinsic_usd_minor=460,
                    assumed_fees_usd_minor=24) == "POSITIVE_GROSS_PAYOFF_OVERTURNED_BY_FEES"
    assert classify(entry_cashflow_usd_minor=-450, terminal_intrinsic_usd_minor=474,
                    assumed_fees_usd_minor=24) == "MODELED_BREAK_EVEN_AFTER_FEES"
    assert classify(entry_cashflow_usd_minor=-400, terminal_intrinsic_usd_minor=500,
                    assumed_fees_usd_minor=24) == "MODELED_NET_POSITIVE_AFTER_FEES"


def test_economic_bet_shape_ignores_quote_identity_not_leg_geometry():
    legs = [
        {"right": "C", "strike": 95.0, "side": "BUY", "quantity": 1,
         "shares_per_contract": 100, "option_quote_id": 1001},
        {"right": "C", "strike": 100.0, "side": "SELL", "quantity": 2,
         "shares_per_contract": 100, "option_quote_id": 1002},
        {"right": "C", "strike": 105.0, "side": "BUY", "quantity": 1,
         "shares_per_contract": 100, "option_quote_id": 1003},
    ]
    a = {"structure_id": "LONG_1_2_1_BUTTERFLY", "legs": legs}
    b = {"structure_id": "LONG_1_2_1_BUTTERFLY",
         "legs": [{**leg, "option_quote_id": leg["option_quote_id"] + 20}
                  for leg in reversed(legs)]}
    assert _economic_bet_key("AAPL", "2026-10-16", a) == _economic_bet_key(
        "AAPL", "2026-10-16", b
    )
    assert _economic_bet_key("AAPL", "2026-10-16", a) != _economic_bet_key(
        "AAPL", "2026-10-23", b
    )
