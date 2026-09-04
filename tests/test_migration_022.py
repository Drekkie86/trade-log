import sqlite3
from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.database.repository import get_connection

def test_v22_objects_exist_and_schema_is_current(db_path):
    c=get_connection(db_path)
    try:
        assert c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]==EXPECTED_SCHEMA_VERSION
        names={r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        required={'provider_model_timing_reconstruction_v1_runs','provider_model_timing_reconstruction_v1','v_provider_model_timing_effective_v1','v_local_surface_null_v1_discovery_membership_timing_v1','local_surface_calibration_readiness_v1_runs','local_surface_calibration_readiness_v1_episodes','local_surface_calibration_readiness_v1_cross_day_contracts','local_surface_calibration_readiness_v1_quality_episode_summary'}
        assert required<=names
    finally:c.close()
