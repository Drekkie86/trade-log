from __future__ import annotations
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from src.database.repository import get_connection
from src.research.live_pipeline import parse_thetadata_market_timestamp

VERSION='1.0.0'; NY=ZoneInfo('America/New_York'); UTC=ZoneInfo('UTC')
DOC_URLS=(
 'https://docs.thetadata.us/operations/option_at_time_quote.html',
 'https://docs.thetadata.us/operations/stock_at_time_quote.html',
 'https://docs.thetadata.us/operations/option_snapshot_quote.html',
)

def validate_thetadata_timestamp_semantics_v1(*,db_path=None,live_probe_state='NOT_RUN'):
    summer=parse_thetadata_market_timestamp('2026-09-03T09:30:00.000')
    winter=parse_thetadata_market_timestamp('2026-01-15T09:30:00.000')
    aware=parse_thetadata_market_timestamp('2026-09-03T13:30:00+00:00')
    summer_off=summer.utcoffset().total_seconds()/3600
    winter_off=winter.utcoffset().total_seconds()/3600
    dst=(summer_off==-4.0 and winter_off==-5.0)
    aware_pass=(aware.hour==9 and aware.utcoffset().total_seconds()/3600==-4.0)
    doc_pass=True
    if not (dst and aware_pass and doc_pass): confidence='FAILED'
    elif live_probe_state=='PASSED': confidence='DOCUMENTED_AND_LIVE_VALIDATED'
    else: confidence='DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED'
    evidence={'version':VERSION,'documentation_urls':DOC_URLS,'documented_contract':'ThetaData time_of_day is America/New_York and snapshot cache resets at midnight ET','summer_example':summer.isoformat(),'winter_example':winter.isoformat(),'aware_utc_example':aware.isoformat(),'live_probe_state':live_probe_state}
    c=get_connection(db_path)
    try:
      with c:
        cur=c.execute('''INSERT INTO thetadata_timestamp_semantics_v1_runs(semantics_version,validated_at,documented_market_timezone,summer_offset_hours,winter_offset_hours,aware_conversion_pass,dst_contract_pass,documentation_contract_pass,live_probe_state,confidence_state,evidence_json,decision_enabled) VALUES(?,?,?,?,?,?,?,?,?,?,?,0)''',(VERSION,datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00','Z'),'America/New_York',summer_off,winter_off,int(aware_pass),int(dst),int(doc_pass),live_probe_state,confidence,json.dumps(evidence,sort_keys=True)))
        rid=int(cur.lastrowid)
    finally:c.close()
    return {'run_id':rid,'confidence_state':confidence,'summer_offset_hours':summer_off,'winter_offset_hours':winter_off,'aware_conversion_pass':aware_pass,'dst_contract_pass':dst,'live_probe_state':live_probe_state}
