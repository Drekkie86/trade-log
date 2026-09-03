from __future__ import annotations
import hashlib,json
from datetime import datetime
from zoneinfo import ZoneInfo
from src.database.repository import get_connection
from src.research.live_pipeline import parse_thetadata_market_timestamp
UTC=ZoneInfo("UTC")
METHOD_VERSION="PERSISTED_RAW_TIMING_RECONSTRUCTION_V1"

def _utc(raw:str)->datetime:
    p=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
    if p.tzinfo is None:p=p.replace(tzinfo=UTC)
    return p.astimezone(UTC)

def reconstruct_provider_timing_v1(*,db_path=None):
    c=get_connection(db_path)
    try:
        rows=c.execute("""
        SELECT pmo.id,pmo.ingested_at,pmo.observed_at,pmo.model_input_notes,oq.quote_at
        FROM provider_model_observations pmo
        JOIN option_quotes oq ON oq.id=pmo.option_quote_id
        WHERE pmo.provider='THETADATA'
          AND pmo.timing_diagnostic_version IS NULL
          AND NOT EXISTS(SELECT 1 FROM provider_model_timing_reconstruction_v1 x WHERE x.provider_model_observation_id=pmo.id)
        ORDER BY pmo.id
        """).fetchall()
    finally:c.close()
    cfg={"method_version":METHOD_VERSION,"native_rows_untouched":True,"provider_market_timezone":"America/New_York"}
    cfgj=json.dumps(cfg,sort_keys=True,separators=(",",":")); h=hashlib.sha256(cfgj.encode()).hexdigest()
    out=[]; counts={"COMPLETE":0,"PARTIAL":0,"UNAVAILABLE":0}
    for r in rows:
        notes={}
        try: notes=json.loads(r['model_input_notes'] or '{}')
        except Exception: pass
        grec=r['observed_at'] or notes.get('provider_raw_timestamp')
        q=r['quote_at']; u=notes.get('underlying_timestamp'); ing=r['ingested_at']
        ga=qg=ug=None; status=[]
        try: gt=parse_thetadata_market_timestamp(str(grec)) if grec else None
        except Exception: gt=None; status.append('GREEK_TIMESTAMP_INVALID')
        try: qt=parse_thetadata_market_timestamp(str(q)) if q else None
        except Exception: qt=None; status.append('QUOTE_TIMESTAMP_INVALID')
        try: ut=parse_thetadata_market_timestamp(str(u)) if u else None
        except Exception: ut=None; status.append('UNDERLYING_TIMESTAMP_INVALID')
        try: it=_utc(str(ing)) if ing else None
        except Exception: it=None; status.append('INGESTED_AT_INVALID')
        if gt is not None and it is not None: ga=(it-gt.astimezone(UTC)).total_seconds()
        if gt is not None and qt is not None: qg=(gt-qt).total_seconds()
        if gt is not None and ut is not None: ug=(gt-ut).total_seconds()
        n=sum(x is not None for x in (ga,qg,ug))
        state='COMPLETE' if n==3 else ('PARTIAL' if n else 'UNAVAILABLE'); counts[state]+=1
        ev={"status":status,"derivation":{"greek_age":"ingested_at - greek_timestamp","quote_greek_skew":"greek_timestamp - quote_timestamp","underlying_greek_skew":"greek_timestamp - underlying_timestamp"}}
        out.append((r['id'],state,ing,q,grec,u,ga,qg,ug,json.dumps(ev,sort_keys=True)))
    c=get_connection(db_path)
    try:
      with c:
        cur=c.execute("INSERT INTO provider_model_timing_reconstruction_v1_runs(method_version,fitted_at,eligible_count,reconstructed_count,partial_count,unavailable_count,config_hash,config_json) VALUES(?,?,?,?,?,?,?,?)",(METHOD_VERSION,datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00','Z'),len(rows),counts['COMPLETE'],counts['PARTIAL'],counts['UNAVAILABLE'],h,cfgj)); rid=int(cur.lastrowid)
        c.executemany("INSERT INTO provider_model_timing_reconstruction_v1(reconstruction_run_id,provider_model_observation_id,method_version,reconstruction_state,source_ingested_at,source_quote_at,source_greek_at,source_underlying_at,greek_age_seconds,quote_greek_skew_seconds,underlying_greek_skew_seconds,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",[(rid,x[0],METHOD_VERSION,*x[1:]) for x in out])
    finally:c.close()
    return {"run_id":rid,"eligible":len(rows),**{k.lower():v for k,v in counts.items()}}
