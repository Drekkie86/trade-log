from src.research.thetadata_timestamp_semantics_v1 import validate_thetadata_timestamp_semantics_v1
from src.database.repository import get_connection

def test_documented_et_dst_contract_is_persisted(db_path):
    r=validate_thetadata_timestamp_semantics_v1(db_path=db_path)
    assert r['summer_offset_hours']==-4.0
    assert r['winter_offset_hours']==-5.0
    assert r['aware_conversion_pass'] is True
    assert r['dst_contract_pass'] is True
    assert r['confidence_state']=='DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED'
    c=get_connection(db_path)
    try:
        row=c.execute('SELECT * FROM thetadata_timestamp_semantics_v1_runs WHERE id=?',(r['run_id'],)).fetchone()
        assert row['decision_enabled']==0
        assert row['live_probe_state']=='NOT_RUN'
    finally:c.close()
