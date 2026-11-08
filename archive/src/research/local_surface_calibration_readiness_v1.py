from __future__ import annotations
import hashlib,json
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
from src.database.repository import get_connection
UTC=ZoneInfo('UTC'); VERSION='0.1.0'
class CalibrationReadinessError(RuntimeError):pass

def _episode_key(r):return f"{r['underlying']}|{r['expiration']}|{float(r['strike']):.8f}|{r['right']}|{r['session_date']}"
def _contract_key(r):return f"{r['underlying']}|{r['expiration']}|{float(r['strike']):.8f}|{r['right']}"
def _readiness(n):
    if n<5:return 'INSUFFICIENT_INDEPENDENT_DATES'
    if n<20:return 'EXPLORATORY_STABILITY_ONLY'
    return 'READY_FOR_PREREGISTRATION_REVIEW_ONLY'
def _med(vals):return None if not vals else float(np.median(np.asarray(vals,float)))
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

def fit_local_surface_calibration_readiness_v1(*,db_path=None,persist=True):
    c=get_connection(db_path)
    try:
        rr=c.execute("SELECT id,source_null_run_id FROM local_surface_robustness_v1_runs ORDER BY id DESC LIMIT 1").fetchone()
        if rr is None: raise CalibrationReadinessError('No v21 robustness run exists.')
        rows=c.execute("SELECT * FROM v_local_surface_null_v1_discovery_membership_timing_v1 WHERE null_run_id=? ORDER BY v2_observation_id",(rr['source_null_run_id'],)).fetchall()
    finally:c.close()
    if not rows:raise CalibrationReadinessError('No discovery rows.')
    dates=sorted({str(r['session_date']) for r in rows}); eps=defaultdict(list)
    for r in rows:eps[_episode_key(r)].append(r)
    by_contract=defaultdict(list)
    for k,g in eps.items():by_contract[_contract_key(g[0])].append(g)
    cross={k:v for k,v in by_contract.items() if len({str(g[0]['session_date']) for g in v})>=2}
    src=[str(r['effective_timing_source'] or 'UNAVAILABLE') for r in rows]
    native=src.count('NATIVE_V18'); recon=src.count('RECONSTRUCTED_FROM_PERSISTED_RAW_V1'); unavailable=len(src)-native-recon
    cfg={'version':VERSION,'episode_unit':'CONTRACT_SESSION','timing_view':'EFFECTIVE_NATIVE_OR_RECONSTRUCTED_V1','p_values':False,'fdr':False,'decision':False,'edge_claim':False,'independent_date_thresholds':[5,20]}
    cfgj=json.dumps(cfg,sort_keys=True,separators=(',',':')); h=hashlib.sha256(cfgj.encode()).hexdigest(); ready=_readiness(len(dates))
    if not persist:return {'observations':len(rows),'dates':len(dates),'episodes':len(eps),'cross_day_contracts':len(cross),'native':native,'reconstructed':recon,'unavailable':unavailable,'readiness':ready}
    c=get_connection(db_path)
    try:
      with c:
        old=c.execute("SELECT id FROM local_surface_calibration_readiness_v1_runs WHERE source_robustness_run_id=? AND calibration_version=? AND config_hash=?",(rr['id'],VERSION,h)).fetchone()
        if old:raise CalibrationReadinessError(f"Calibration run already exists: {old['id']}")
        cur=c.execute("INSERT INTO local_surface_calibration_readiness_v1_runs(calibration_version,source_robustness_run_id,source_null_run_id,config_hash,config_json,fitted_at,observation_count,distinct_session_dates,episode_count,cross_day_contract_count,native_timing_count,reconstructed_timing_count,unavailable_timing_count,readiness_state,p_values_enabled,fdr_enabled,decision_enabled) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0)",(VERSION,rr['id'],rr['source_null_run_id'],h,cfgj,datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00','Z'),len(rows),len(dates),len(eps),len(cross),native,recon,unavailable,ready)); rid=int(cur.lastrowid)
        episode_rows=[]
        for key,g in sorted(eps.items()):
            vals=np.asarray([float(r['centered_residual']) for r in g]); med=float(np.median(vals)); peak=float(np.max(np.abs(vals))); persistence=0.0 if peak==0 else min(1.0,abs(med)/peak)
            pos=int(np.sum(vals>0)); neg=int(np.sum(vals<0)); nz=pos+neg; sign=1.0 if nz==0 else max(pos,neg)/nz
            spreads=[float(r['spread_to_mid']) for r in g if r['spread_to_mid'] is not None]
            ga=[abs(float(r['effective_greek_age_seconds'])) for r in g if r['effective_greek_age_seconds'] is not None]
            qg=[abs(float(r['effective_quote_greek_skew_seconds'])) for r in g if r['effective_quote_greek_skew_seconds'] is not None]
            ug=[abs(float(r['effective_underlying_greek_skew_seconds'])) for r in g if r['effective_underlying_greek_skew_seconds'] is not None]
            ss=[str(r['effective_timing_source'] or 'UNAVAILABLE') for r in g]
            rec=(rid,key,g[0]['session_date'],g[0]['underlying'],g[0]['expiration'],g[0]['strike'],g[0]['right'],len(g),med,peak,persistence,sign,_med(spreads),_med(ga),_med(qg),_med(ug),ss.count('NATIVE_V18'),ss.count('RECONSTRUCTED_FROM_PERSISTED_RAW_V1'),len(ss)-ss.count('NATIVE_V18')-ss.count('RECONSTRUCTED_FROM_PERSISTED_RAW_V1'))
            c.execute("INSERT INTO local_surface_calibration_readiness_v1_episodes(calibration_run_id,episode_key,session_date,underlying,expiration,strike,right,observation_count,median_centered_residual,peak_abs_centered_residual,persistence_ratio,sign_consistency_fraction,median_spread_to_mid,median_abs_greek_age_seconds,median_abs_quote_greek_skew_seconds,median_abs_underlying_greek_skew_seconds,native_timing_observation_count,reconstructed_timing_observation_count,unavailable_timing_observation_count) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",rec)
            episode_rows.append({'key':key,'median':med,'peak':peak,'persistence':persistence,'spread':_med(spreads),'ga':_med(ga),'qg':_med(qg),'ug':_med(ug)})
        for key,groups in sorted(cross.items()):
            daily=[]; total=0
            for g in groups:
                total+=len(g); daily.append(float(np.median([float(r['centered_residual']) for r in g])))
            arr=np.asarray(daily); nz=arr[arr!=0]; pos=int(np.sum(nz>0)); neg=int(np.sum(nz<0)); agreement=1.0 if len(nz)==0 else max(pos,neg)/len(nz); same=1 if (len(nz)==0 or pos==len(nz) or neg==len(nz)) else 0
            g0=groups[0][0]
            c.execute("INSERT INTO local_surface_calibration_readiness_v1_cross_day_contracts(calibration_run_id,contract_key,underlying,expiration,strike,right,session_date_count,total_observation_count,median_of_daily_medians,max_abs_daily_median,daily_median_range,same_sign_all_nonzero_days,sign_agreement_fraction) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(rid,key,g0['underlying'],g0['expiration'],g0['strike'],g0['right'],len(groups),total,float(np.median(arr)),float(np.max(np.abs(arr))),float(np.max(arr)-np.min(arr)),same,float(agreement)))
        metrics=[('SPREAD_TO_MID',lambda e:_bucket_spread(e['spread'])),('GREEK_AGE_ABS',lambda e:_bucket_seconds(e['ga'])),('QUOTE_GREEK_SKEW_ABS',lambda e:_bucket_seconds(e['qg'])),('UNDERLYING_GREEK_SKEW_ABS',lambda e:_bucket_seconds(e['ug']))]
        for name,fn in metrics:
            b=defaultdict(list)
            for e in episode_rows:b[fn(e)].append(e)
            for bucket,g in sorted(b.items()):
                med_abs=float(np.median([abs(e['median']) for e in g])); q95=float(np.quantile([e['peak'] for e in g],.95)); mp=float(np.median([e['persistence'] for e in g]))
                c.execute("INSERT INTO local_surface_calibration_readiness_v1_quality_episode_summary(calibration_run_id,metric_name,bucket_name,episode_count,median_abs_episode_median,q95_peak_abs_residual,median_persistence_ratio) VALUES(?,?,?,?,?,?,?)",(rid,name,bucket,len(g),med_abs,q95,mp))
    finally:c.close()
    return {'run_id':rid,'observations':len(rows),'dates':len(dates),'episodes':len(eps),'cross_day_contracts':len(cross),'native':native,'reconstructed':recon,'unavailable':unavailable,'readiness':ready}
