"""The v38 decision ledger must be append-only, timely, cross-strategy."""
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from src.database.repository import EXPECTED_SCHEMA_VERSION, get_connection
from src.decision.unified_prospective_ledger_v1 import freeze_market_decisions
from src.decision.unified_trade_ranker_v1 import OptionCandidate
from src.research.strategy_falsification_v1 import Leg, QuoteCostPolicy, Structure

SESSION = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
EXPIRY = (datetime.now(ZoneInfo("America/New_York")).date()
          + timedelta(days=14)).isoformat()


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


def seed_frozen_chain(db_path, *, age_seconds=2, stock_source='FETCHED'):
    now = datetime.now(UTC).replace(microsecond=0)
    cut = now - timedelta(seconds=age_seconds)
    source = cut - timedelta(seconds=2)
    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO research_runs (
            cohort_id,preregistration_hash,code_git_sha,started_at,
            us_session_date,us_session_state,status
            ) VALUES ('V38','V38_HASH','V38_COMMIT',?, ?,
                      'INTRADAY','STARTED')""",
            (iso(cut),SESSION),
        )
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO market_snapshots
             (research_run_id,captured_at,underlying,provider,
              underlying_price,underlying_source,underlying_at,
              fx_source,notes,us_session_date,us_session_state)
             VALUES (?,?, 'XYZ','THETADATA',100,?,?,'UNKNOWN',
             'stock price source=MASSIVE_OPTION_CHAIN_UNDERLYING_ASSET_LAST; '
             || 'test immutable receipt', ?,'INTRADAY')""",
            (run_id,iso(cut),stock_source,iso(source),SESSION),
        )
        sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        ids = {}
        for kind,strike,bid,ask in (
            ("C",100,4.9,5), ("C",105,3,3.1), ("P",100,0.9,1),
        ):
            conn.execute(
                """INSERT INTO option_quotes
                (snapshot_id,right,strike,expiration,quote_at,
                 bid,bid_source,bid_at,ask,ask_source,ask_at,
                 last_source,iv_source,delta_source,gamma_source,theta_source,
                 vega_source,volume_source,open_interest_source,
                 shares_per_contract)
                 VALUES (?,?,?,?,? ,?,'FETCHED',? ,?,'FETCHED',?,
                 'UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN',
                 'UNKNOWN','UNKNOWN','UNKNOWN',100)""",
                (sid,kind,strike,EXPIRY,iso(source),
                 bid,iso(source),ask,iso(source)),
            )
            ids[(kind,strike)] = conn.execute(
                "SELECT last_insert_rowid()"
            ).fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    policy = QuoteCostPolicy(
        option_cost_per_contract_side_usd=D("1"),
        stock_round_trip_cost_usd=None,eur_to_usd=D("1.1"),
        cost_provenance="TEST_ASSUMED_NOT_EXECUTABLE",
        fx_provenance="TEST_PRIOR_FX",
        max_quote_age_seconds=15,max_leg_quote_skew_seconds=15,
        bankroll_eur=D("500"),
        additional_round_trip_cost_usd=D("2"),tax_cost_usd=D("1"),
        fx_observed_at=iso(source),
    )
    def l(kind,side,strike,bid,ask):
        return Leg(
            "CALL" if kind=="C" else "PUT",side,1,D("100"),
            D(str(strike)),EXPIRY,D(str(bid)),D(str(ask)),
            iso(source),D("10"),D("10"),str(ids[(kind,strike)]),
        )
    spread = Structure(
        "S03","FROZEN_TEST",iso(cut),
        (l("C","BUY",100,4.9,5),l("C","SELL",105,3,3.1)),
        f"snapshot:{sid}:XYZ:S03",
    )
    long_vol = Structure(
        "S06","FROZEN_TEST",iso(cut),
        (l("C","BUY",100,4.9,5),l("P","BUY",100,.9,1)),
        f"snapshot:{sid}:XYZ:S06",
    )
    return run_id,(
        OptionCandidate(sid,"XYZ",EXPIRY,spread,policy,()),
        OptionCandidate(sid,"XYZ",EXPIRY,long_vol,policy,()),
    )


def test_schema_38_exposes_immutable_unified_decision_book(db_path):
    assert EXPECTED_SCHEMA_VERSION == 38
    conn = get_connection(db_path)
    try:
        assert conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()[0] == 38
        assert conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name='unified_candidate_decisions_v1'"
        ).fetchone()
    finally:
        conn.close()


def test_freeze_two_strategies_before_outcomes_and_preserve_all_inputs(db_path):
    run_id,candidates = seed_frozen_chain(db_path)
    receipt = freeze_market_decisions(
        research_run_id=run_id,candidates=candidates,db_path=db_path
    )
    assert receipt.newly_inserted == 2
    assert receipt.models_promoted_to_live_trading == 0
    assert len(receipt.candidate_ids) == 2
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM unified_candidate_decisions_v1 "
            "WHERE research_run_id=? ORDER BY strategy_id",(run_id,)
        ).fetchall()
        assert [x["strategy_id"] for x in rows] == ["S03","S06"]
        assert all(x["state"]=="NO_TRADE" for x in rows)
        assert all(x["provenance_tier"]=="UNPROVEN_MODEL" for x in rows)
        assert all(len(x["input_sha256"])==64 for x in rows)
        assert all("NO_INDEPENDENT_FORECAST_MODELS" in
                   json.loads(x["blockers_json"]) for x in rows)
        assert all(json.loads(x["input_json"])["model_inputs"]==[]
                   for x in rows)
        with pytest.raises(sqlite3.DatabaseError,match="immutable"):
            conn.execute(
                "UPDATE unified_candidate_decisions_v1 SET state='NO_TRADE'"
            )
        with pytest.raises(sqlite3.DatabaseError,match="immutable"):
            conn.execute("DELETE FROM unified_candidate_decisions_v1")
        conn.rollback()
    finally:
        conn.close()


def test_repeated_identical_freeze_does_not_double_count_decisions(db_path):
    run_id,candidates = seed_frozen_chain(db_path)
    first = freeze_market_decisions(
        research_run_id=run_id,candidates=candidates,db_path=db_path
    )
    second = freeze_market_decisions(
        research_run_id=run_id,candidates=candidates,db_path=db_path
    )
    assert first.candidate_ids == second.candidate_ids
    assert second.newly_inserted == 0


def test_old_snapshot_cannot_be_misrepresented_as_prospective(db_path):
    run_id,candidates=seed_frozen_chain(db_path,age_seconds=1200)
    with pytest.raises(ValueError,match="NOT_FROZEN_PROSPECTIVELY"):
        freeze_market_decisions(
            research_run_id=run_id,candidates=candidates,db_path=db_path
        )
    conn=get_connection(db_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM unified_candidate_decisions_v1"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_same_snapshot_source_and_provenance_are_mandatory(db_path):
    run_id,candidates=seed_frozen_chain(db_path,stock_source="DERIVED")
    with pytest.raises(ValueError,match="STOCK_REFERENCE_NOT_EVIDENCED"):
        freeze_market_decisions(
            research_run_id=run_id,candidates=candidates,db_path=db_path
        )


def test_atomic_fail_closed_if_one_candidate_borrows_wrong_snapshot(db_path):
    run_id,candidates=seed_frozen_chain(db_path)
    wrong=replace(candidates[1],snapshot_id=999999)
    with pytest.raises(ValueError,match="SOURCE_SNAPSHOT_NOT_FOUND"):
        freeze_market_decisions(
            research_run_id=run_id,candidates=(candidates[0],wrong),
            db_path=db_path,
        )
    conn=get_connection(db_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM unified_candidate_decisions_v1"
        ).fetchone()[0] == 0
    finally:
        conn.close()
