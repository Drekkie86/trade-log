from __future__ import annotations
import hashlib, json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
from src.database.repository import get_connection
UTC=ZoneInfo('UTC')
ROBUSTNESS_VERSION='0.1.0'; SOURCE_NULL_VERSION='0.1.0'; SCALE=1.4826
class LocalSurfaceRobustnessError(RuntimeError): pass
@dataclass(frozen=True)
class RobustnessResult:
    robustness_run_id:int|None; source_null_run_id:int; observation_count:int; distinct_session_dates:int; episode_count:int; repeated_episode_count:int; readiness_state:str

def _readiness(n:int)->str:
    if n<2:return 'INSUFFICIENT_FOR_CROSS_DATE'
    if n<5:return 'CROSS_DATE_DESCRIPTIVE_ONLY'
    if n<20:return 'EXPLORATORY_STABILITY_ONLY'
    return 'READY_FOR_PREREGISTRATION_REVIEW_ONLY'
def _bucket_spread(x):
    if x is None:return 'MISSING'
    if x<.05:return 'LT_05'
    if x<.10:return '05_10'
    if x<.20:return '10_20'
    return 'GE_20'
def _bucket_seconds(x):
    if x is None:return 'MISSING'
    x=abs(float(x))
    if x<=1:return 'LE_1S'
    if x<=5:return '1_5S'
    if x<=30:return '5_30S'
    return 'GT_30S'
def _stats(vals):
    a=np.asarray(vals,float); med=float(np.median(a)); mad=float(np.median(np.abs(a-med)))
    lo,hi=np.quantile(a,[.025,.975],method='linear')
    return med,float(SCALE*mad),float(lo),float(hi)
def _abs_stats(rows):
    a=np.asarray([float(r['abs_centered_residual']) for r in rows])
    return len(rows),float(np.median(a)),float(np.quantile(a,.95)),float(np.quantile(a,.99))
def _episode_key(r): return f"{r['underlying']}|{r['expiration']}|{float(r['strike']):.8f}|{r['right']}|{r['session_date']}"

def fit_local_surface_robustness_v1(*,persist=True,db_path=None):
    c=get_connection(db_path)
    try:
        nr=c.execute("SELECT id FROM local_surface_null_v1_runs WHERE null_model_version=? ORDER BY id DESC LIMIT 1",(SOURCE_NULL_VERSION,)).fetchone()
        if nr is None: raise LocalSurfaceRobustnessError('No v20 empirical-null run exists.')
        null_id=int(nr['id'])
        rows=c.execute("SELECT * FROM v_local_surface_null_v1_discovery_membership WHERE null_run_id=? ORDER BY v2_observation_id",(null_id,)).fetchall()
    finally:c.close()
    if not rows: raise LocalSurfaceRobustnessError('No discovery membership rows.')
    dates=sorted({str(r['session_date']) for r in rows}); episodes=defaultdict(list)
    for r in rows: episodes[_episode_key(r)].append(r)
    repeated=sum(len(v)>1 for v in episodes.values()); readiness=_readiness(len(dates))
    if not persist:return RobustnessResult(None,null_id,len(rows),len(dates),len(episodes),repeated,readiness)
    cfg={'version':ROBUSTNESS_VERSION,'source_null_version':SOURCE_NULL_VERSION,'date_readiness':[2,5,20],'p_values':False,'fdr':False,'decision':False,'edge_claim':False}
    cfgj=json.dumps(cfg,sort_keys=True,separators=(',',':')); cfgh=hashlib.sha256(cfgj.encode()).hexdigest()
    c=get_connection(db_path)
    try:
      with c:
        old=c.execute("SELECT id FROM local_surface_robustness_v1_runs WHERE source_null_run_id=? AND robustness_version=? AND config_hash=?",(null_id,ROBUSTNESS_VERSION,cfgh)).fetchone()
        if old: raise LocalSurfaceRobustnessError(f"Robustness run already exists: {old['id']}")
        cur=c.execute("INSERT INTO local_surface_robustness_v1_runs (robustness_version,source_null_run_id,config_hash,config_json,fitted_at,observation_count,distinct_session_dates,episode_count,repeated_episode_count,readiness_state,p_values_enabled,fdr_enabled,decision_enabled) VALUES (?,?,?,?,?,?,?,?,?,?,0,0,0)",(ROBUSTNESS_VERSION,null_id,cfgh,cfgj,datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00','Z'),len(rows),len(dates),len(episodes),repeated,readiness)); rid=int(cur.lastrowid)
        for key,g in sorted(episodes.items()):
            g=sorted(g,key=lambda r:int(r['v2_observation_id'])); peak=max(g,key=lambda r:float(r['abs_centered_residual']))
            spreads=[float(r['spread_to_mid']) for r in g if r['spread_to_mid'] is not None]
            c.execute("INSERT INTO local_surface_robustness_v1_episodes (robustness_run_id,episode_key,session_date,underlying,expiration,strike,right,observation_count,first_research_run_id,last_research_run_id,median_centered_residual,peak_abs_centered_residual,max_spread_to_mid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",(rid,key,g[0]['session_date'],g[0]['underlying'],g[0]['expiration'],g[0]['strike'],g[0]['right'],len(g),g[0]['research_run_id'],g[-1]['research_run_id'],float(np.median([float(r['centered_residual']) for r in g])),float(peak['abs_centered_residual']),max(spreads) if spreads else None))
        ds=defaultdict(list)
        for r in rows: ds[(str(r['session_date']),str(r['stratum_key']))].append(r)
        for (d,s),g in sorted(ds.items()):
            med,sc,lo,hi=_stats([float(r['centered_residual']) for r in g]); c.execute("INSERT INTO local_surface_robustness_v1_daily_strata (robustness_run_id,session_date,stratum_key,observation_count,median_centered_residual,robust_scale,q025,q975) VALUES (?,?,?,?,?,?,?,?)",(rid,d,s,len(g),med,sc,lo,hi))
        for train in dates:
          for test in dates:
            if train==test: continue
            keys=sorted({s for (d,s) in ds if d==train})
            for s in keys:
                tr=ds[(train,s)]; te=ds.get((test,s),[])
                if len(tr)<20 or len(te)<20: continue
                tm,ts,lo,hi=_stats([float(r['centered_residual']) for r in tr]); xm,xs,_,_=_stats([float(r['centered_residual']) for r in te]); arr=np.asarray([float(r['centered_residual']) for r in te]); below=int(np.sum(arr<lo)); above=int(np.sum(arr>hi))
                c.execute("INSERT INTO local_surface_robustness_v1_cross_date (robustness_run_id,train_session_date,test_session_date,stratum_key,train_count,test_count,train_median,train_robust_scale,train_q025,train_q975,test_median,test_robust_scale,test_below_q025_count,test_above_q975_count,test_tail_fraction) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(rid,train,test,s,len(tr),len(te),tm,ts,lo,hi,xm,xs,below,above,(below+above)/len(te)))
        metrics=[('SPREAD_TO_MID',lambda r:_bucket_spread(r['spread_to_mid'])),('GREEK_AGE_ABS',lambda r:_bucket_seconds(r['greek_age_seconds'])),('QUOTE_GREEK_SKEW_ABS',lambda r:_bucket_seconds(r['quote_greek_skew_seconds'])),('UNDERLYING_GREEK_SKEW_ABS',lambda r:_bucket_seconds(r['underlying_greek_skew_seconds']))]
        for name,fn in metrics:
            b=defaultdict(list)
            for r in rows:b[fn(r)].append(r)
            for bucket,g in sorted(b.items()):
                n,m,q95,q99=_abs_stats(g); c.execute("INSERT INTO local_surface_robustness_v1_quality_sensitivity (robustness_run_id,metric_name,bucket_name,observation_count,median_abs_centered_residual,q95_abs_centered_residual,q99_abs_centered_residual) VALUES (?,?,?,?,?,?,?)",(rid,name,bucket,n,m,q95,q99))
    finally:c.close()
    return RobustnessResult(rid,null_id,len(rows),len(dates),len(episodes),repeated,readiness)
