import json
import sqlite3
from src.database.repository import get_connection
from src.research.provider_timing_reconstruction_v1 import reconstruct_provider_timing_v1
from src.research.local_surface_calibration_readiness_v1 import fit_local_surface_calibration_readiness_v1
from src.research.local_surface_empirical_null_v1 import fit_empirical_null_v1
from src.research.local_surface_robustness_v1 import fit_local_surface_robustness_v1
from tests.test_local_surface_empirical_null_v1 import seed_v2_discovery_rows


def _seed_pre_v18_model_observations(db_path):
    c=get_connection(db_path)
    try:
      with c:
        quotes=c.execute("SELECT oq.id,oq.quote_at,ms.us_session_date FROM option_quotes oq JOIN market_snapshots ms ON ms.id=oq.snapshot_id ORDER BY oq.id").fetchall()
        for q in quotes:
            date=str(q['us_session_date'])
            c.execute("""
              INSERT INTO provider_model_observations(
                option_quote_id,provider,ingested_at,observed_at,source,model_name,
                implied_volatility,delta,model_input_notes
              ) VALUES(?, 'THETADATA', ?, ?, 'PROVIDER_DERIVED','legacy-test',0.20,0.50,?)
            """,(q['id'],f'{date}T18:00:05Z',f'{date}T14:00:03',json.dumps({'underlying_timestamp':f'{date}T14:00:01','provider_raw_timestamp':f'{date}T14:00:03'})))
    finally:c.close()


def test_historical_timing_reconstruction_preserves_native_rows_and_recovers_metrics(db_path):
    seed_v2_discovery_rows(db_path,session_date='2026-09-03',count=120)
    _seed_pre_v18_model_observations(db_path)
    result=reconstruct_provider_timing_v1(db_path=db_path)
    assert result['eligible']==120
    assert result['complete']==120
    c=get_connection(db_path)
    try:
        row=c.execute("SELECT * FROM v_provider_model_timing_effective_v1 WHERE provider='THETADATA' ORDER BY provider_model_observation_id LIMIT 1").fetchone()
        assert row['timing_source']=='RECONSTRUCTED_FROM_PERSISTED_RAW_V1'
        assert row['greek_age_seconds']==2.0
        assert row['quote_greek_skew_seconds']==1.0
        assert row['underlying_greek_skew_seconds']==2.0
        pmo=c.execute('SELECT timing_diagnostic_version,greek_age_seconds FROM provider_model_observations ORDER BY id LIMIT 1').fetchone()
        assert pmo['timing_diagnostic_version'] is None
        assert pmo['greek_age_seconds'] is None
    finally:c.close()


def test_calibration_readiness_collapses_episodes_and_tracks_cross_day_contracts(db_path):
    seed_v2_discovery_rows(db_path,session_date='2026-09-02',count=120)
    seed_v2_discovery_rows(db_path,session_date='2026-09-03',count=120)
    _seed_pre_v18_model_observations(db_path)
    reconstruct_provider_timing_v1(db_path=db_path)
    null=fit_empirical_null_v1(persist=True,db_path=db_path)
    assert null.observation_count==240
    rob=fit_local_surface_robustness_v1(persist=True,db_path=db_path)
    assert rob.distinct_session_dates==2
    out=fit_local_surface_calibration_readiness_v1(db_path=db_path,persist=True)
    assert out['dates']==2
    assert out['readiness']=='INSUFFICIENT_INDEPENDENT_DATES'
    assert out['episodes']==240
    assert out['cross_day_contracts']==120
    assert out['reconstructed']==240
    assert out['unavailable']==0
    c=get_connection(db_path)
    try:
        run=c.execute('SELECT * FROM local_surface_calibration_readiness_v1_runs WHERE id=?',(out['run_id'],)).fetchone()
        assert run['p_values_enabled']==0 and run['fdr_enabled']==0 and run['decision_enabled']==0
        ep=c.execute('SELECT * FROM local_surface_calibration_readiness_v1_episodes WHERE calibration_run_id=? LIMIT 1',(out['run_id'],)).fetchone()
        assert 0<=ep['persistence_ratio']<=1
        assert .5<=ep['sign_consistency_fraction']<=1
        cd=c.execute('SELECT COUNT(*) FROM local_surface_calibration_readiness_v1_cross_day_contracts WHERE calibration_run_id=?',(out['run_id'],)).fetchone()[0]
        assert cd==120
        qs=c.execute('SELECT metric_name,bucket_name FROM local_surface_calibration_readiness_v1_quality_episode_summary WHERE calibration_run_id=?',(out['run_id'],)).fetchall()
        assert any(r['metric_name']=='GREEK_AGE_ABS' and r['bucket_name']!='MISSING' for r in qs)
    finally:c.close()


def test_v22_schema_firewall_refuses_inferential_flags(db_path):
    c=get_connection(db_path)
    try:
        assert c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]==22
        try:
            c.execute("INSERT INTO local_surface_calibration_readiness_v1_runs(calibration_version,source_robustness_run_id,source_null_run_id,config_hash,config_json,fitted_at,observation_count,distinct_session_dates,episode_count,cross_day_contract_count,native_timing_count,reconstructed_timing_count,unavailable_timing_count,readiness_state,p_values_enabled,fdr_enabled,decision_enabled) VALUES('x',1,1,'h','{}','x',1,1,1,0,0,0,1,'INSUFFICIENT_INDEPENDENT_DATES',1,0,0)")
            assert False
        except sqlite3.IntegrityError:
            pass
    finally:c.close()
