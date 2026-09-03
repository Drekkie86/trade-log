import sqlite3

from src.research.local_surface_calibration_validity_v1 import _dte_bucket,_linear_residuals,_load_discovery_rows

def test_dte_buckets_preserve_14_20_as_its_own_region():
    assert _dte_bucket(13)=='DTE_07_13'
    assert _dte_bucket(14)=='DTE_14_20'
    assert _dte_bucket(20)=='DTE_14_20'
    assert _dte_bucket(21)=='DTE_21_30'

def test_nearest_bracket_linear_residual_excludes_target_from_fit():
    rows=[]
    for oid,strike,iv in [(1,100,0.20),(2,105,0.25),(3,110,0.30)]:
        rows.append({'research_run_id':1,'underlying':'X','expiration':'2026-10-01','right':'C','implied_volatility':iv,'strike':strike,'v2_observation_id':oid})
    out=_linear_residuals(rows)
    assert abs(out[2])<1e-12

def test_nearest_bracket_linear_residual_detects_local_perturbation():
    rows=[]
    for oid,strike,iv in [(1,100,0.20),(2,105,0.28),(3,110,0.30)]:
        rows.append({'research_run_id':1,'underlying':'X','expiration':'2026-10-01','right':'C','implied_volatility':iv,'strike':strike,'v2_observation_id':oid})
    out=_linear_residuals(rows)
    assert abs(out[2]-0.03)<1e-12


def test_discovery_loader_joins_persisted_v2_implied_volatility():
    connection=sqlite3.connect(':memory:')
    connection.row_factory=sqlite3.Row
    connection.execute('CREATE TABLE v_local_surface_null_v1_discovery_membership_timing_v1 (null_run_id INTEGER, v2_observation_id INTEGER, underlying TEXT)')
    connection.execute('CREATE TABLE local_surface_residual_v2_observations (id INTEGER PRIMARY KEY, implied_volatility REAL)')
    connection.execute("INSERT INTO v_local_surface_null_v1_discovery_membership_timing_v1 VALUES (1, 7, 'IWM')")
    connection.execute('INSERT INTO local_surface_residual_v2_observations VALUES (7, 0.314159)')
    rows=_load_discovery_rows(connection,1)
    assert len(rows)==1
    assert rows[0]['v2_observation_id']==7
    assert rows[0]['implied_volatility']==0.314159
    connection.close()
