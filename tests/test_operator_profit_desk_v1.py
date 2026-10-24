"""Profit-first dashboard contract: never promote legacy butterfly scores."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from src.decision.operator_profit_desk_v1 import (
    build_trading_desk_state, load_underlying_source_coverage,
)
from src.decision.opportunity import VERDICT_SKIP, VERDICT_WORTH
from src.decision.unified_trade_ranker_v1 import (
    MANUAL_REQUOTE, MarketDecision, RankedOpportunity,
)


def row(at, verdict=VERDICT_SKIP, why="COSTS_EAT_EDGE"):
    idea = SimpleNamespace(
        as_of=at, underlying="ABC", expiration="2026-10-29",
        structure_id="LONG_1_2_1_BUTTERFLY", max_loss_usd=112.0,
    )
    assessment = SimpleNamespace(
        verdict=verdict, reason_code=why, models_favouring=3,
        net_edge_usd=50.0,
    )
    return idea, assessment


def fresh(now):
    return (now - timedelta(seconds=10)).isoformat()


def test_even_worth_legacy_butterfly_has_zero_trade_authority():
    now = datetime(2026, 10, 24, 19, tzinfo=UTC)
    out = build_trading_desk_state(
        [row(fresh(now), VERDICT_WORTH, "WORTH")],
        latest_session="2026-10-24", now=now,
    )
    assert out.verdict == "NO TRADE"
    assert out.promotable_trades == 0
    assert out.research_legacy_worth == 1
    assert out.source_fresh
    assert out.authority == "NONE"
    assert "UNIFIED_PROSPECTIVE_TRADE_RANKING_NOT_CONNECTED" in dict(
        out.no_trade_reasons
    )


def test_stale_source_vetoes_authoritative_manual_requote():
    now = datetime(2026, 10, 24, 19, tzinfo=UTC)
    candidate = RankedOpportunity(
        snapshot_id=42, underlying="ABC", expiration="2026-10-29",
        strategy_id="S03", source_reference="snapshot:42",
        lane="MAIN", state=MANUAL_REQUOTE, rank=1,
        conservative_net_ev_usd=None, risk_adjusted_score=None,
        assumed_worst_loss_usd=None,
        confirming_model_groups=2, opposing_model_groups=0,
        missing_evidence=(), model_net_ev_usd=(),
    )
    ranking = MarketDecision(
        state=MANUAL_REQUOTE, top=candidate,
        opportunities=(candidate,), rejected_count=0, provisional_count=1,
    )
    out = build_trading_desk_state(
        [row("2026-10-23T19:00:00+00:00")],
        latest_session="2026-10-23", authoritative=ranking, now=now,
    )
    assert out.verdict == "NO TRADE"
    assert out.promotable_trades == 0
    assert "NO_CURRENT_EXECUTABLE_MARKET_SNAPSHOT" in dict(
        out.no_trade_reasons
    )


def test_unavailable_or_future_timestamp_fails_closed():
    now = datetime(2026, 10, 24, 19, tzinfo=UTC)
    for t in (None, "", "2026-10-24T19:01:00Z",
              "2026-10-24T18:00:00Z", "bad-timestamp"):
        out = build_trading_desk_state(
            [] if t is None else [row(t)], latest_session=None, now=now,
        )
        assert out.verdict == "NO TRADE"
        assert not out.source_fresh


def test_no_fake_win_rate_or_realized_profit_is_in_operator_contract():
    now = datetime(2026, 10, 24, 19, tzinfo=UTC)
    out = build_trading_desk_state(
        [row(fresh(now)), row(fresh(now), why="COSTS_EAT_EDGE")],
        latest_session="2026-10-24", now=now,
    )
    assert out.research_proposals_reviewed == 2
    assert out.research_legacy_skip == 2
    assert dict(out.no_trade_reasons)["COSTS_EAT_EDGE"] == 2
    assert out.ranked_candidates == ()
    assert len(out.legacy_near_misses) == 2



def test_latest_run_independent_source_coverage_is_explicit(tmp_path):
    import sqlite3
    from tests.test_independent_family_read_model_v1 import seed

    path = tmp_path / "test.sqlite"
    seed(path)
    state = load_underlying_source_coverage(db_path=path)
    assert state.research_run_id == 11
    assert state.sampled_snapshots == 1
    assert state.independent_fresh_prices == 1
    assert state.state == "SOURCED"

    conn = sqlite3.connect(path)
    conn.execute("UPDATE market_snapshots SET underlying_source='UNKNOWN'")
    conn.commit()
    conn.close()
    broken = load_underlying_source_coverage(db_path=path)
    assert broken.independent_fresh_prices == 0
    assert broken.state == "NO_INDEPENDENT_STOCK_PRICES"


def test_stale_independent_underlying_is_not_qualified(tmp_path):
    import sqlite3
    from tests.test_independent_family_read_model_v1 import seed

    path = tmp_path / "test.sqlite"
    seed(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE market_snapshots SET underlying_at='2026-10-19T14:59:00Z'"
    )
    conn.commit()
    conn.close()
    broken = load_underlying_source_coverage(db_path=path)
    assert broken.independent_fresh_prices == 0
