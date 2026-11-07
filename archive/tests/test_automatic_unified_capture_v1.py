"""End-to-end automatic snapshot capture produces one immutable disposition."""
from datetime import UTC, datetime, timedelta
import sqlite3

from src.database.repository import get_connection
from src.decision.operator_profit_desk_v1 import load_underlying_source_coverage
from src.research.automatic_unified_capture_v1 import capture_frozen_snapshot
from src.research.independent_runner import run_independent_research
from tests.test_unified_prospective_ledger_v1 import seed_frozen_chain, iso
from tests.test_independent_runner import FakeMassive, FakeTheta


def complete_lcrs(db_path, run_id: int, snapshot_id: int, *, with_reference=True):
    """Reference multipliers must be evidenced from actual listing identities."""
    with get_connection(db_path) as conn:
        now = iso(datetime.now(UTC))
        for right in ("C", "P"):
            for strike in (90, 95, 100, 105, 110):
                if (right,strike) not in {("C",100),("C",105),("P",100)}:
                    conn.execute(
                        """INSERT INTO option_quotes (
                           snapshot_id,right,strike,expiration,quote_at,
                           bid,bid_source,bid_at,ask,ask_source,ask_at,
                           last_source,iv_source,delta_source,gamma_source,
                           theta_source,vega_source,volume_source,
                           open_interest_source,shares_per_contract)
                           SELECT ?,?,?,expiration,quote_at,
                                  1,'FETCHED',quote_at,1.1,'FETCHED',quote_at,
                                  'UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN',
                                  'UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN',100
                           FROM option_quotes WHERE snapshot_id=? LIMIT 1""",
                        (snapshot_id,right,strike,snapshot_id),
                    )
        if not with_reference:
            return
        rows=conn.execute(
            "SELECT right,strike,expiration FROM option_quotes "
            "WHERE snapshot_id=? ORDER BY right,strike",(snapshot_id,)
        ).fetchall()
        for q in rows:
            already=conn.execute(
                """SELECT COUNT(*) FROM listing_reference_contracts
                   WHERE research_run_id=? AND underlying='XYZ'
                     AND expiration=? AND right=? AND strike=?""",
                (run_id,q["expiration"],q["right"],q["strike"]),
            ).fetchone()[0]
            if already:
                continue
            symbol=f"TEST_{q['right']}_{q['strike']}"
            conn.execute(
                """INSERT INTO listing_reference_contracts
                  (research_run_id,provider,underlying,provider_contract_id,
                   expiration,strike,right,shares_per_contract,
                   observed_at,ingested_at)
                  VALUES (?,'MASSIVE','XYZ',?,?,?,?,100,?,?)""",
                (run_id,symbol,q["expiration"],q["strike"],q["right"],now,now),
            )


def test_sourced_real_snapshot_freezes_seven_no_trade_proposals(db_path):
    run_id,candidates=seed_frozen_chain(db_path)
    sid=candidates[0].snapshot_id
    complete_lcrs(db_path,run_id,sid)
    output=capture_frozen_snapshot(
        research_run_id=run_id,snapshot_id=sid,db_path=db_path
    )
    assert output.status=="FROZEN_NO_TRADE",output
    assert output.structures_compared==7
    assert output.decisions_frozen==7
    assert output.authority=="NONE"
    coverage=load_underlying_source_coverage(db_path=db_path)
    assert coverage.research_run_id==run_id
    assert coverage.capture_attempts==1
    assert coverage.prospective_decisions_frozen==7
    assert coverage.independent_fresh_prices==1
    assert coverage.capture_failures==0
    with get_connection(db_path) as conn:
        rows=conn.execute(
            "SELECT strategy_id,state FROM unified_candidate_decisions_v1 "
            "WHERE snapshot_id=? ORDER BY strategy_id",(sid,)
        ).fetchall()
        assert len(rows)==7
        assert all(r["state"]=="NO_TRADE" for r in rows)
    second=capture_frozen_snapshot(
        research_run_id=run_id,snapshot_id=sid,db_path=db_path
    )
    assert second==output


def test_missing_stock_is_audited_without_option_work(db_path):
    run_id,candidates=seed_frozen_chain(db_path,stock_source="DERIVED")
    sid=candidates[0].snapshot_id
    output=capture_frozen_snapshot(
        research_run_id=run_id,snapshot_id=sid,db_path=db_path
    )
    assert output.status=="NO_SOURCE"
    assert output.structures_compared==0
    assert output.decisions_frozen==0
    with get_connection(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM unified_candidate_decisions_v1"
        ).fetchone()[0]==0


def test_delayed_snapshot_is_not_reconstructed_as_a_new_prospective_prediction(
    db_path,
):
    run_id,candidates=seed_frozen_chain(db_path,age_seconds=1000)
    receipt=capture_frozen_snapshot(
        research_run_id=run_id,snapshot_id=candidates[0].snapshot_id,
        db_path=db_path,
    )
    assert receipt.status=="OUTSIDE_PROSPECTIVE_WINDOW"
    assert receipt.decisions_frozen==0


def test_missing_listing_multipliers_records_evidence_failure_not_fake_trades(
    db_path,
):
    run_id,candidates=seed_frozen_chain(db_path)
    complete_lcrs(
        db_path,run_id,candidates[0].snapshot_id,with_reference=False,
    )
    receipt=capture_frozen_snapshot(
        research_run_id=run_id,snapshot_id=candidates[0].snapshot_id,
        db_path=db_path,
    )
    assert receipt.status=="EVIDENCE_REJECTED"
    assert receipt.decisions_frozen==0


def test_historical_research_fixtures_get_capture_reason_not_backfilled(
    db_path,
):
    historical=datetime(2026,8,31,18,0,5,tzinfo=UTC)
    result=run_independent_research(
        symbols=["AAPL"],massive_client=FakeMassive(),
        theta_client=FakeTheta(),observed_at=historical,
        observation_clock=lambda: historical,db_path=db_path,
        min_dte=7,max_dte=45,code_git_sha="v38-automatic-fixture",
        max_underlying_recovery_retries=0,
    )
    assert result.status=="COMPLETED"
    with get_connection(db_path) as conn:
        rows=conn.execute(
            "SELECT state,reason_code,decisions_frozen "
            "FROM unified_capture_dispositions_v1 "
            "WHERE research_run_id=?",(result.run_id,)
        ).fetchall()
        assert len(rows)==1
        assert rows[0]["state"]=="OUTSIDE_PROSPECTIVE_WINDOW"
        assert rows[0]["decisions_frozen"]==0


def test_liquid_multiexpiry_chain_is_bounded_without_discarding_every_strategy(
    db_path,
):
    """More than 2,500 true option quotes must not mean zero evaluated trades."""
    from datetime import date
    from zoneinfo import ZoneInfo

    run_id,candidates=seed_frozen_chain(db_path)
    sid=candidates[0].snapshot_id
    complete_lcrs(db_path,run_id,sid)
    session=datetime.now(ZoneInfo("America/New_York")).date()
    now=iso(datetime.now(UTC))
    with get_connection(db_path) as conn:
        for dte in range(7,46,3):
            expiry=(session+timedelta(days=dte)).isoformat()
            if expiry==candidates[0].expiration:
                continue
            for right in ("C","P"):
                for strike in range(25,175):
                    symbol=f"BIG_{expiry}_{right}_{strike}"
                    conn.execute(
                        """INSERT INTO option_quotes
                        (snapshot_id,right,strike,expiration,quote_at,
                        bid,bid_source,bid_at,ask,ask_source,ask_at,
                        last_source,iv_source,delta_source,gamma_source,
                        theta_source,vega_source,volume_source,
                        open_interest_source,shares_per_contract)
                        SELECT ?,?,?,?,quote_at,
                               1,'FETCHED',quote_at,1.1,'FETCHED',quote_at,
                               'UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN',
                               'UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN',100
                        FROM option_quotes WHERE snapshot_id=? LIMIT 1""",
                        (sid,right,strike,expiry,sid),
                    )
                    conn.execute(
                        """INSERT INTO listing_reference_contracts
                          (research_run_id,provider,underlying,
                           provider_contract_id,expiration,strike,right,
                           shares_per_contract,observed_at,ingested_at)
                          VALUES (?,'MASSIVE','XYZ',?,?,?,?,100,?,?)""",
                        (run_id,symbol,expiry,strike,right,now,now),
                    )
        count=conn.execute(
            "SELECT COUNT(*) FROM option_quotes WHERE snapshot_id=?",(sid,)
        ).fetchone()[0]
    assert count > 2500
    result=capture_frozen_snapshot(
        research_run_id=run_id,snapshot_id=sid,db_path=db_path
    )
    assert result.status=="FROZEN_NO_TRADE",result
    assert 7 <= result.decisions_frozen <= 42
    assert result.structures_compared==result.decisions_frozen
