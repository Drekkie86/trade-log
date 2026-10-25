"""One authoritative immutable decision book feeding the Trade Desk."""
from dataclasses import replace
from datetime import UTC,datetime,timedelta
from decimal import Decimal as D
import sqlite3

import pytest

from src.decision.operator_profit_desk_v1 import build_trading_desk_state
from src.decision.unified_frozen_read_model_v1 import load_latest_frozen_book
from src.decision.unified_prospective_ledger_v1 import freeze_market_decisions
from src.decision.unified_trade_ranker_v1 import NO_TRADE
from tests.test_unified_prospective_ledger_v1 import seed_frozen_chain


def test_decisions_read_back_from_one_book_with_one_verdict(db_path):
    run_id,candidates=seed_frozen_chain(db_path)
    freeze_market_decisions(
        research_run_id=run_id,candidates=candidates,db_path=db_path
    )
    book=load_latest_frozen_book(db_path=db_path)
    assert book.records==2
    assert book.last_run_id==run_id
    assert book.latest_snapshot_at
    assert book.decision.state==NO_TRADE
    assert book.decision.rejected_count==2
    assert book.decision.provisional_count==0
    assert {x.strategy_id for x in book.decision.opportunities}=={"S03","S06"}
    assert all("NO_INDEPENDENT_FORECAST_MODELS" in x.missing_evidence
               for x in book.decision.opportunities)
    assert not any(x.broker_order_authority for x in
                   book.decision.opportunities)
    desk=build_trading_desk_state(
        [],latest_session=None,authoritative=book.decision,
        authoritative_latest_snapshot_at=book.latest_snapshot_at,
        now=datetime.now(UTC),
    )
    assert desk.source_fresh
    assert desk.verdict=="NO TRADE"
    assert desk.promotable_trades==0
    assert desk.authority=="NONE"


def test_book_expiry_never_promotes_stale_candidates(db_path):
    run_id,candidates=seed_frozen_chain(db_path)
    freeze_market_decisions(
        research_run_id=run_id,candidates=candidates,db_path=db_path
    )
    future=datetime.now(UTC)+timedelta(hours=1)
    book=load_latest_frozen_book(db_path=db_path,now=future)
    assert book.decision.state==NO_TRADE
    desk=build_trading_desk_state(
        [],latest_session=None,authoritative=book.decision,
        authoritative_latest_snapshot_at=book.latest_snapshot_at,
        now=future,
    )
    assert desk.verdict=="NO TRADE"
    assert not desk.source_fresh


def test_different_model_or_cost_inputs_cannot_rewrite_same_economic_bet(db_path):
    run_id,candidates=seed_frozen_chain(db_path)
    freeze_market_decisions(
        research_run_id=run_id,candidates=candidates,db_path=db_path
    )
    changed=replace(
        candidates[0],
        cost_policy=replace(
            candidates[0].cost_policy,
            additional_round_trip_cost_usd=D("4"),
        ),
    )
    with pytest.raises(sqlite3.IntegrityError,match="UNIQUE"):
        freeze_market_decisions(
            research_run_id=run_id,
            candidates=(changed,),
            db_path=db_path,
        )
    book=load_latest_frozen_book(db_path=db_path)
    assert book.records==2


def test_latest_run_without_decisions_cannot_reuse_older_candidate_rank(db_path):
    from src.database.repository import get_connection
    run_id,candidates=seed_frozen_chain(db_path)
    freeze_market_decisions(
        research_run_id=run_id,candidates=candidates,db_path=db_path,
    )
    assert load_latest_frozen_book(db_path=db_path).records==2
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO research_runs
              (cohort_id,preregistration_hash,code_git_sha,started_at,
               us_session_date,us_session_state,status)
               VALUES ('LATER_EMPTY','LATER_HASH','LATER_SHA',?,
                       '2026-10-24','INTRADAY','STARTED')""",
            (datetime.now(UTC).isoformat(),),
        )
        last_id=int(conn.execute(
            "SELECT last_insert_rowid()"
        ).fetchone()[0])
    book=load_latest_frozen_book(db_path=db_path)
    assert book.last_run_id==last_id
    assert book.records==0
    assert book.decision is None
    assert book.latest_snapshot_at is None
