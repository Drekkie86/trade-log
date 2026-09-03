import sqlite3
from src.database.repository import get_connection
def test_v21_objects_and_firewall(db_path):
 c=get_connection(db_path); assert c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]==24; names={r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}; assert 'local_surface_robustness_v1_runs' in names and 'v_local_surface_robustness_v1_episode_summary' in names
 try:
  c.execute("INSERT INTO local_surface_robustness_v1_runs (robustness_version,source_null_run_id,config_hash,config_json,fitted_at,observation_count,distinct_session_dates,episode_count,repeated_episode_count,readiness_state,p_values_enabled,fdr_enabled,decision_enabled) VALUES ('x',1,'h','{}','x',1,1,1,0,'CROSS_DATE_DESCRIPTIVE_ONLY',1,0,0)"); assert False
 except sqlite3.IntegrityError: pass
 c.close()
