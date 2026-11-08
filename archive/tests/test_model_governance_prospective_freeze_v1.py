import json
from src.database.repository import get_connection
from src.research.model_governance_prospective_freeze_v1 import freeze_model_governance_v1


def _seed_minimum(c):
    # Existing fixture has full migrated schema but no validity data. Create only the dependency chain needed by v24.
    c.execute("INSERT INTO local_surface_calibration_readiness_v1_runs(id,calibration_version,source_null_run_id,source_robustness_run_id,fitted_at,observation_count,episode_count,cross_day_contract_count,distinct_session_dates,native_timing_count,reconstructed_timing_count,unavailable_timing_count,readiness_state,config_hash,config_json,p_values_enabled,fdr_enabled,decision_enabled) VALUES(1,'x',1,1,'x',1,1,0,2,0,1,0,'INSUFFICIENT_INDEPENDENT_DATES','h','{}',0,0,0)")
    c.execute("INSERT INTO thetadata_timestamp_semantics_v1_runs(id,semantics_version,validated_at,documented_market_timezone,summer_offset_hours,winter_offset_hours,aware_conversion_pass,dst_contract_pass,documentation_contract_pass,live_probe_state,confidence_state,evidence_json,decision_enabled) VALUES(1,'x','x','America/New_York',-4,-5,1,1,1,'NOT_RUN','DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED','{}',0)")
    c.execute("INSERT INTO local_surface_calibration_validity_v1_runs(id,validity_version,source_calibration_run_id,timestamp_semantics_run_id,fitted_at,distinct_session_dates,dte_14_20_instability_state,timestamp_confidence_state,readiness_state,config_hash,config_json,p_values_enabled,fdr_enabled,decision_enabled) VALUES(1,'x',1,1,'x',2,'OBSERVED_UNSTABLE','DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED','INSUFFICIENT_INDEPENDENT_DATES','h','{}',0,0,0)")
    c.execute("INSERT INTO local_surface_calibration_readiness_v1_episodes(calibration_run_id,episode_key,session_date,underlying,expiration,strike,right,observation_count,median_centered_residual,peak_abs_centered_residual,persistence_ratio,sign_consistency_fraction,native_timing_observation_count,reconstructed_timing_observation_count,unavailable_timing_observation_count) VALUES(1,'k','2026-09-03','SPY','2026-09-18',500,'C',1,.01,.01,1,1,0,1,0)")
    for dte,lb in [('DTE_07_13',.55),('DTE_14_20',.67)]:
        c.execute("INSERT INTO local_surface_calibration_validity_v1_model_comparison(validity_run_id,dte_bucket,observation_count,quadratic_median_abs_residual,local_linear_median_abs_residual,quadratic_q95_abs_residual,local_linear_q95_abs_residual,local_linear_better_fraction) VALUES(1,?,100,.001,.0005,.006,.005,?)",(dte,lb))
        c.execute("INSERT INTO local_surface_calibration_validity_v1_dte_transfer(validity_run_id,train_session_date,test_session_date,dte_bucket,stratum_count,test_observation_count,weighted_tail_fraction,max_stratum_tail_fraction,nominal_reference_tail,tail_inflation_ratio) VALUES(1,'2026-09-02','2026-09-03',?,1,100,.05,.1,.05,2)",(dte,))
        c.execute("INSERT INTO local_surface_calibration_validity_v1_episode_transfer(validity_run_id,train_session_date,test_session_date,dte_bucket,train_episode_count,test_episode_count,train_q025,train_q975,test_tail_fraction) VALUES(1,'2026-09-02','2026-09-03',?,10,10,-.01,.01,.08)",(dte,))


def test_freeze_is_idempotent_and_reserves_future_models(db_path):
    c=get_connection(db_path)
    try:
        c.execute('PRAGMA foreign_keys=OFF')
        _seed_minimum(c)
        c.commit()
    finally:c.close()
    a=freeze_model_governance_v1(db_path); b=freeze_model_governance_v1(db_path)
    assert a['freeze_run_id']==b['freeze_run_id']
    assert a['frozen_through_session_date']=='2026-09-03'
    assert a['prospective_start_session_date']=='2026-09-04'
    c=get_connection(db_path)
    try:
        models={r['model_key']:dict(r) for r in c.execute('SELECT * FROM research_model_registry_v1')}
        assert models['BLACK_SCHOLES_MERTON_BENCHMARK']['governance_role']=='RESERVED_NOT_IMPLEMENTED'
        assert models['BLACK_SCHOLES_MERTON_BENCHMARK']['evidence_use_enabled']==0
        assert models['BAYESIAN_PERSISTENCE_MODEL']['decision_enabled']==0
        assert c.execute('SELECT COUNT(*) FROM prospective_research_hypotheses_v1').fetchone()[0]==4
        state=c.execute("SELECT review_state FROM prospective_model_dte_baseline_v1 WHERE dte_bucket='DTE_14_20'").fetchone()[0]
        assert state=='KNOWN_INSTABILITY_PROSPECTIVE_RETEST_REQUIRED'
    finally:c.close()
