from src.database.repository import get_connection


def test_v24_objects_and_schema(db_path):
    c=get_connection(db_path)
    try:
        assert c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]==24
        names={r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        assert {'research_model_registry_v1','prospective_research_freeze_v1_runs','prospective_research_hypotheses_v1','prospective_model_dte_baseline_v1','v_local_surface_v2_prospective_partition_v1'}<=names
    finally:c.close()


def test_v24_firewall_is_database_enforced(db_path):
    c=get_connection(db_path)
    try:
        try:
            c.execute("INSERT INTO research_model_registry_v1(model_key,model_version,model_family,governance_role,evidence_use_enabled,admission_enabled,decision_enabled,notes) VALUES('x','x','x','RESERVED_NOT_IMPLEMENTED',0,1,0,'x')")
        except Exception as exc:
            assert 'CHECK constraint failed' in str(exc)
        else: raise AssertionError('admission_enabled=1 should be rejected')
    finally:c.close()
