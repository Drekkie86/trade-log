"""Real as-of strategy comparison must fail closed before it enters recommendations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.database.repository import get_connection
from src.decision.trade_ideas import load_current_ideas
from src.research.strategy_competition_v1 import (
    RESEARCH_ONLY, _fx_asof, compare_real_snapshot_strategies,
)
from tests.test_trade_ideas import seed_scenario, EXPIRY


def _seed_quote_cuts(db_path, *, add_puts=True, quote_at_override=None,
                     fx_future=False):
    ids = seed_scenario(
        db_path, with_v2=True,
        quote_at=quote_at_override or "2026-09-01T18:00:02Z",
    )
    conn = get_connection(db_path)
    try:
        snapshot_id = ids["snapshot_id"]
        snap = conn.execute(
            "SELECT captured_at,underlying FROM market_snapshots WHERE id=?",
            (snapshot_id,),
        ).fetchone()
        capture = datetime.fromisoformat(snap["captured_at"].replace("Z", "+00:00"))
        quote_at = (capture - timedelta(seconds=3)).isoformat().replace("+00:00", "Z")
        if add_puts:
            for strike, bid, ask in ((95, 1.2, 1.4), (100, 3.5, 3.7), (105, 6.0, 6.2)):
                conn.execute(
                    """INSERT INTO option_quotes (
                          snapshot_id,provider_contract_id,right,strike,
                          expiration,quote_at,bid,ask,shares_per_contract,
                          bid_source,ask_source,last_source,iv_source,
                          delta_source,gamma_source,theta_source,vega_source,
                          volume_source,open_interest_source
                    ) VALUES (?,?,'P',?,?,?, ?,?,100,
                          'FETCHED','FETCHED','UNKNOWN','UNKNOWN',
                          'UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN',
                          'UNKNOWN','UNKNOWN')""",
                    (snapshot_id, f"TEST:P:{strike}", strike, EXPIRY,
                     quote_at_override or quote_at, bid, ask),
                )
        conn.execute(
            """INSERT INTO fx_observations
                 (provider,base_currency,quote_currency,rate,reference_date,
                  observed_at,provenance)
               VALUES ('ECB','EUR','USD',1.10,'2026-09-01',?,
                       'ECB_REFERENCE_FIXTURE')""",
            ("2026-10-18T00:00:00Z" if fx_future else quote_at,),
        )
        conn.commit()
    finally:
        conn.close()
    ideas, errors, _ = load_current_ideas(db_path=db_path)
    assert not errors and len(ideas) == 1
    return ids, ideas


def test_debit_spreads_and_original_fly_use_same_frozen_snapshot(db_path):
    ids, ideas = _seed_quote_cuts(db_path)
    r = compare_real_snapshot_strategies(ideas, allocated_eur="500", db_path=db_path)
    assert len(r) == 7
    assert [x.strategy_id for x in r] == ["S03", "S04", "S06", "S07", "S09", "S10", "S08"]
    assert {x.snapshot_id for x in r} == {ids["snapshot_id"]}
    assert {x.decision_at for x in r} == {ideas[0].as_of}
    assert all(x.comparison_state == RESEARCH_ONLY for x in r), [(x.strategy_id, x.comparison_state, x.reasons) for x in r]
    assert all(x.signal_evidence != "INDEPENDENT_CONFIRMED" for x in r)
    assert all("NO_PROSPECTIVE_STRATEGY_SPECIFIC_EDGE_EVIDENCE" in x.reasons for x in r)
    # Stock/day metadata and spot are not manufactured to establish edge.
    assert all(x.feasibility is not None for x in r)
    assert all(x.feasibility.state == "INSUFFICIENT_EVIDENCE" for x in r)
    assert all(x.feasibility.gross_max_loss_usd is not None for x in r)
    assert all(x.feasibility.conservative_capital_eur is None for x in r)
    assert {int(x) for entry in r for x in entry.source_quote_ids}.issuperset(
        {int(qid) for qid in ids["qid"].values() if qid in r[6].source_quote_ids}
    )
    assert "Source quote IDs" in r[0].display_row()


def test_missing_put_quotes_cannot_be_fabricated(db_path):
    _, ideas = _seed_quote_cuts(db_path, add_puts=False)
    r = compare_real_snapshot_strategies(ideas, allocated_eur="500", db_path=db_path)
    assert r[0].feasibility is not None
    assert r[1].feasibility is None
    assert r[1].reasons == ("MISSING_SAME_SNAPSHOT_QUOTE",)
    assert r[6].feasibility is not None


def test_quote_from_future_cannot_be_used(db_path):
    ids, ideas = _seed_quote_cuts(db_path, quote_at_override="2026-12-01T10:00:00Z")
    rows = compare_real_snapshot_strategies(ideas, allocated_eur="500", db_path=db_path)
    assert "FUTURE_QUOTE_LEAKAGE" in rows[0].feasibility.reasons
    assert "FUTURE_QUOTE_LEAKAGE" in rows[6].feasibility.reasons
    assert all(x.comparison_state != "RECOMMENDED" for x in rows)


def test_missing_or_future_fx_never_enters_budget_conversion(db_path):
    ids, ideas = _seed_quote_cuts(db_path, fx_future=True)
    rows = compare_real_snapshot_strategies(ideas, allocated_eur="500", db_path=db_path)
    assert all("FX_PROVENANCE_OR_RATE_MISSING" in x.feasibility.reasons for x in rows)
    assert all(x.feasibility.conservative_capital_eur is None for x in rows)


def test_no_hypothesis_or_invalid_allocation_never_promotes_trades(db_path):
    assert compare_real_snapshot_strategies([], allocated_eur="500", db_path=db_path) == ()
    with pytest.raises(ValueError, match="BUDGET_OUTSIDE"):
        compare_real_snapshot_strategies([], allocated_eur="501", db_path=db_path)
    with pytest.raises(ValueError, match="BUDGET_OUTSIDE"):
        compare_real_snapshot_strategies([], allocated_eur="0", db_path=db_path)


def test_ambiguous_duplicate_contract_fails_closed(db_path):
    ids, ideas = _seed_quote_cuts(db_path)
    conn = get_connection(db_path)
    try:
        q = conn.execute(
            "SELECT * FROM option_quotes WHERE id=?", (ids["qid"][95],)
        ).fetchone()
        conn.execute(
            """INSERT INTO option_quotes
               (snapshot_id,provider_contract_id,right,strike,expiration,quote_at,
                bid,ask,shares_per_contract,bid_source,ask_source,last_source,
                iv_source,delta_source,gamma_source,theta_source,vega_source,
                volume_source,open_interest_source)
               VALUES (?,?,?, ?,?,?, ?,?,?,
                       'FETCHED','FETCHED','UNKNOWN','UNKNOWN','UNKNOWN',
                       'UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN')""",
            (ids["snapshot_id"], "TEST:duplicate-95", "C", 95,
             q["expiration"], q["quote_at"], q["bid"], q["ask"], 100),
        )
        conn.commit()
    finally:
        conn.close()
    rows = compare_real_snapshot_strategies(ideas, allocated_eur="500", db_path=db_path)
    assert rows[0].feasibility is None
    assert rows[0].reasons == ("AMBIGUOUS_SAME_SNAPSHOT_CONTRACT",)
    assert rows[6].source_quote_ids == tuple(l.option_quote_id for l in ideas[0].legs)


def test_no_lookahead_fx_selection(db_path):
    ids, ideas = _seed_quote_cuts(db_path)
    conn = get_connection(db_path)
    try:
        snap = conn.execute("SELECT captured_at FROM market_snapshots WHERE id=?",
                            (ids["snapshot_id"],)).fetchone()
        rate, observed, source = _fx_asof(conn, snap["captured_at"])
        assert rate == pytest.approx(1.10)
        assert "ECB_REFERENCE_FIXTURE" in source
        assert observed <= snap["captured_at"]
    finally:
        conn.close()


def test_thetadata_new_york_market_timestamp_is_converted_without_mutation():
    from src.research.strategy_competition_v1 import _quote_time_asof
    assert _quote_time_asof("2026-10-16T09:45:07.614") == (
        "2026-10-16T13:45:07.614000+00:00"
    )
    assert _quote_time_asof("2026-01-16T09:45:07.614") == (
        "2026-01-16T14:45:07.614000+00:00"
    )
    assert _quote_time_asof("2026-10-16T13:45:07Z") == (
        "2026-10-16T13:45:07+00:00"
    )
    with pytest.raises(ValueError, match="DST_TIMESTAMP"):
        _quote_time_asof("2026-11-01T01:30:00")


def test_missing_quote_multiplier_reads_authoritative_contract_reference_only():
    from src.research.strategy_competition_v1 import _quote_leg
    row = {
        "id": 101, "right": "C", "strike": 100, "expiration": "2026-10-30",
        "bid": 2, "ask": 2.1, "quote_at": "2026-10-16T09:45:07",
        "quote_multiplier": None, "reference_multiplier": 100,
    }
    assert _quote_leg(row, side="BUY").multiplier == 100
    with pytest.raises(ValueError, match="MULTIPLIER_NOT_EVIDENCED"):
        _quote_leg({**row, "reference_multiplier": None}, side="BUY")
    with pytest.raises(ValueError, match="MULTIPLIER_DISAGREE"):
        _quote_leg({**row, "quote_multiplier": 10}, side="BUY")



def test_trade_ideas_exposes_bounded_comparison_without_promoting_signals(
    db_path, monkeypatch,
):
    from pathlib import Path
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    _seed_quote_cuts(db_path)
    monkeypatch.setenv("CHRISTIANIA_DB_PATH", str(db_path))
    st.cache_data.clear()
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app.py"), default_timeout=90)
    app.run(timeout=90)
    assert not app.exception, app.exception
    before = [m.value for m in app.metric if m.label == "Worth a look"]
    toggles = [x for x in app.get("toggle")
               if x.label == "Compare strategies using the same recorded market quotes"]
    assert len(toggles) == 1
    toggles[0].set_value(True).run(timeout=90)
    assert not app.exception, app.exception
    after = [m.value for m in app.metric if m.label == "Worth a look"]
    assert after == before
    assert any("frozen comparisons" in cap.value for cap in app.caption)
    assert any(
        len(d.value) == 7 and "Strategy" in d.value.columns
        for d in app.dataframe
    )
