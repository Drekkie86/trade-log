from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.database.repository import get_connection

def test_v23_objects_exist_and_schema_is_current(db_path):
    c=get_connection(db_path)
    try:
        assert c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]==EXPECTED_SCHEMA_VERSION
        names={r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required={'thetadata_timestamp_semantics_v1_runs','local_surface_calibration_validity_v1_runs','local_surface_calibration_validity_v1_dte_transfer','local_surface_calibration_validity_v1_episode_transfer','local_surface_calibration_validity_v1_model_comparison','local_surface_calibration_validity_v1_quality_dte'}
        assert required<=names
    finally:c.close()

def test_v23_firewall_is_database_enforced(db_path):
    c=get_connection(db_path)
    try:
        # Foreign keys are deliberately not populated; CHECK should still reject enabled flags first.
        try:
            c.execute("INSERT INTO local_surface_calibration_validity_v1_runs(validity_version,source_calibration_run_id,timestamp_semantics_run_id,fitted_at,distinct_session_dates,dte_14_20_instability_state,timestamp_confidence_state,readiness_state,config_hash,config_json,p_values_enabled,fdr_enabled,decision_enabled) VALUES('x',1,1,'x',2,'NOT_EVALUABLE','x','INSUFFICIENT_INDEPENDENT_DATES','h','{}',1,0,0)")
        except Exception as exc:
            assert 'CHECK constraint failed' in str(exc)
        else:
            raise AssertionError('p_values_enabled=1 should be rejected')
    finally:c.close()
