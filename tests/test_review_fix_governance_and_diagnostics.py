from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest

from src.research.edge_statement_validation import DiscoveryWindow, validate_edge_statement
from src.research.thetadata_empirical_diagnostics_v3 import MatchedPairV3
from src.research.thetadata_history_staging import initialize_staging_db, create_run, fail_run, reset_failed_run


def prereg_doc():
    return {
        "schema_version":"1.0","status":"PREREGISTERED","candidate_id":"C1","family_id":"F1",
        "created_from_discovery_data_end":"2026-08-31",
        "setup":{"structure":"CALL_SPREAD","direction":"LONG","entry_rule":"R","exit_rule":"E","max_holding_period":"5D"},
        "estimand":{"primary_metric":"NET_EV","comparator":"CONTROL","cost_provenance":"QUOTED"},
        "confirmation":{"data_start":"2026-09-01","data_end":"2026-10-01","independence_unit":"underlying_session","minimum_independent_units":20,"test":"T","alpha_or_q":0.05,"multiplicity_method":"PREREGISTERED_SINGLE_HYPOTHESIS","effect_size_floor":0.01},
        "searched_family":{"hypothesis_count":2},"edge_statement":"x","results":{"locked_until_confirmation":True}
    }


def test_same_observation_crossing_is_separate_from_holding_return():
    p=MatchedPairV3("AAPL","2026-08-27","2026-08-28","2026-09-25",200,"CALL",0.8,1.0,1.2,1.4)
    assert p.entry_quoted_crossing_fraction_of_ask == pytest.approx(0.2)
    assert p.ask_to_bid_return == pytest.approx(0.2)
    # Numerically equal here by construction, but conceptually separate properties.


def test_programme_budget_unfrozen_blocks_preregistration():
    r=validate_edge_statement(prereg_doc(), discovery_windows=(), hypothesis_counts={"F1":2}, programme_budget={"status":"UNFROZEN"})
    assert not r.ok
    assert any("not FROZEN" in e for e in r.errors)


def test_hypothesis_count_must_match_log():
    r=validate_edge_statement(prereg_doc(), discovery_windows=(), hypothesis_counts={"F1":3}, programme_budget={"status":"FROZEN","family_ids":["F1"]})
    assert not r.ok
    assert any("derived log count 3" in e for e in r.errors)


def test_holdout_access_blocks_confirmation():
    w=(DiscoveryWindow("LOOKED","2026-09-15","2026-09-20","manual inspection"),)
    r=validate_edge_statement(prereg_doc(), discovery_windows=(), holdout_windows=w, hypothesis_counts={"F1":2}, programme_budget={"status":"FROZEN","family_ids":["F1"]})
    assert not r.ok
    assert any("contaminated holdout-access" in e for e in r.errors)


def test_failed_staging_run_can_be_explicitly_reset(tmp_path):
    db=tmp_path/'x.db'; initialize_staging_db(db)
    with sqlite3.connect(db) as c:
        run=create_run(c,symbol='AAPL',trading_date=date(2026,8,28),max_dte=45,started_at_utc='x')
        fail_run(c,run_id=run,completed_at_utc='y',error_text='boom')
        reset_failed_run(c,run_id=run,started_at_utc='z')
        status=c.execute('select status,error_text,row_count from thetadata_eod_runs where run_id=?',(run,)).fetchone()
    assert status == ('RUNNING',None,None)
