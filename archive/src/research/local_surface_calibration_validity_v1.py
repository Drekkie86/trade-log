from __future__ import annotations
import hashlib,json
from collections import defaultdict,Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
from src.database.repository import get_connection

UTC=ZoneInfo('UTC'); VERSION='0.1.0'; NOMINAL=0.05
class CalibrationValidityError(RuntimeError): pass

def _dte_bucket(d):
    d=int(d)
    if 7<=d<=13:return 'DTE_07_13'
    if 14<=d<=20:return 'DTE_14_20'
    if 21<=d<=30:return 'DTE_21_30'
    if 31<=d<=45:return 'DTE_31_45'
    return 'OTHER'

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
def _episode_key(r):return f"{r['underlying']}|{r['expiration']}|{float(r['strike']):.8f}|{r['right']}|{r['session_date']}"

def _load_discovery_rows(connection, null_run_id):
    return connection.execute(
        """
        SELECT
            timing.*,
            v2.implied_volatility AS implied_volatility
        FROM v_local_surface_null_v1_discovery_membership_timing_v1 AS timing
        JOIN local_surface_residual_v2_observations AS v2
          ON v2.id = timing.v2_observation_id
        WHERE timing.null_run_id = ?
        ORDER BY timing.v2_observation_id
        """,
        (null_run_id,),
    ).fetchall()

def _linear_residuals(rows):
    out={}
    groups=defaultdict(list)
    for r in rows: groups[(r['research_run_id'],r['underlying'],r['expiration'],r['right'])].append(r)
    for g in groups.values():
        ordered=sorted([r for r in g if r['implied_volatility'] is not None],key=lambda r:float(r['strike']))
        for i,r in enumerate(ordered):
            if i==0 or i==len(ordered)-1: continue
            lo,hi=ordered[i-1],ordered[i+1]
            x=float(r['strike']); x0=float(lo['strike']); x1=float(hi['strike'])
            if x1==x0:continue
            y0=float(lo['implied_volatility']); y1=float(hi['implied_volatility'])
            fit=y0+(y1-y0)*(x-x0)/(x1-x0)
            out[int(r['v2_observation_id'])]=float(r['implied_volatility'])-fit
    return out

def fit_local_surface_calibration_validity_v1(*,db_path=None,persist=True):
    c=get_connection(db_path)
    try:
        cr=c.execute('SELECT * FROM local_surface_calibration_readiness_v1_runs ORDER BY id DESC LIMIT 1').fetchone()
        if cr is None: raise CalibrationValidityError('No v22 calibration-readiness run exists.')
        ts=c.execute('SELECT * FROM thetadata_timestamp_semantics_v1_runs ORDER BY id DESC LIMIT 1').fetchone()
        if ts is None: raise CalibrationValidityError('No timestamp-semantics validation run exists.')
        rr=c.execute('SELECT id FROM local_surface_robustness_v1_runs WHERE id=?',(cr['source_robustness_run_id'],)).fetchone()
        rows=_load_discovery_rows(c,cr['source_null_run_id'])
        cross=c.execute('SELECT * FROM local_surface_robustness_v1_cross_date WHERE robustness_run_id=? ORDER BY train_session_date,test_session_date,stratum_key',(cr['source_robustness_run_id'],)).fetchall()
    finally:c.close()
    if not rows: raise CalibrationValidityError('No discovery rows.')
    dates=sorted({str(r['session_date']) for r in rows})
    cfg={'version':VERSION,'unit':'CONTRACT_SESSION_EPISODE','nominal_transfer_tail':NOMINAL,'dte_14_20_instability_ratio':1.5,'model_comparison':'LOO_QUADRATIC_V2_vs_NEAREST_BRACKET_LINEAR','p_values':False,'fdr':False,'decision':False,'edge_claim':False}
    cfgj=json.dumps(cfg,sort_keys=True,separators=(',',':')); h=hashlib.sha256(cfgj.encode()).hexdigest()

    dte_transfer=[]
    grouped=defaultdict(list)
    for r in cross:
        parts=str(r['stratum_key']).split('|'); dte=next((p for p in parts if p.startswith('DTE_')),'OTHER')
        grouped[(r['train_session_date'],r['test_session_date'],dte)].append(r)
    for (train,test,dte),g in sorted(grouped.items()):
        n=sum(int(r['test_count']) for r in g); weighted=sum(float(r['test_tail_fraction'])*int(r['test_count']) for r in g)/n
        mx=max(float(r['test_tail_fraction']) for r in g); dte_transfer.append((train,test,dte,len(g),n,weighted,mx,weighted/NOMINAL))
    target=[x for x in dte_transfer if x[2]=='DTE_14_20']
    if not target: instability='NOT_EVALUABLE'
    elif max(x[7] for x in target)>1.5: instability='OBSERVED_UNSTABLE'
    else: instability='NO_INSTABILITY_OBSERVED'

    eps=defaultdict(list)
    for r in rows: eps[_episode_key(r)].append(r)
    episode_meta=[]
    for key,g in eps.items():
        vals=[float(r['centered_residual']) for r in g]
        strata=Counter(str(r['stratum_key']) for r in g); sk=strata.most_common(1)[0][0]; dte=next((p for p in sk.split('|') if p.startswith('DTE_')),_dte_bucket(g[0]['dte']))
        episode_meta.append({'key':key,'date':str(g[0]['session_date']),'dte':dte,'median':float(np.median(vals)),'peak':float(np.max(np.abs(vals))),'spread':float(np.median([float(r['spread_to_mid']) for r in g if r['spread_to_mid'] is not None])) if any(r['spread_to_mid'] is not None for r in g) else None,'ga':float(np.median([abs(float(r['effective_greek_age_seconds'])) for r in g if r['effective_greek_age_seconds'] is not None])) if any(r['effective_greek_age_seconds'] is not None for r in g) else None,'qg':float(np.median([abs(float(r['effective_quote_greek_skew_seconds'])) for r in g if r['effective_quote_greek_skew_seconds'] is not None])) if any(r['effective_quote_greek_skew_seconds'] is not None for r in g) else None,'ug':float(np.median([abs(float(r['effective_underlying_greek_skew_seconds'])) for r in g if r['effective_underlying_greek_skew_seconds'] is not None])) if any(r['effective_underlying_greek_skew_seconds'] is not None for r in g) else None})
    ep_transfer=[]
    for train in dates:
      for test in dates:
        if train==test:continue
        for dte in sorted({e['dte'] for e in episode_meta}):
            tr=[e['median'] for e in episode_meta if e['date']==train and e['dte']==dte]; te=[e['median'] for e in episode_meta if e['date']==test and e['dte']==dte]
            if len(tr)<20 or len(te)<20:continue
            lo,hi=np.quantile(np.asarray(tr,float),[.025,.975]); arr=np.asarray(te,float); tail=float(np.mean((arr<lo)|(arr>hi)))
            ep_transfer.append((train,test,dte,len(tr),len(te),float(lo),float(hi),tail))

    linear=_linear_residuals(rows); model=[]; by_dte=defaultdict(list)
    for r in rows:
        oid=int(r['v2_observation_id'])
        if oid in linear and r['centered_residual'] is not None:
            by_dte[_dte_bucket(r['dte'])].append((abs(float(r['centered_residual'])),abs(float(linear[oid]))))
    for dte,g in sorted(by_dte.items()):
        if dte=='OTHER' or len(g)<20:continue
        q=np.asarray([x[0] for x in g]); l=np.asarray([x[1] for x in g]); model.append((dte,len(g),float(np.median(q)),float(np.median(l)),float(np.quantile(q,.95)),float(np.quantile(l,.95)),float(np.mean(l<q))))

    qrows=[]; metrics=[('SPREAD_TO_MID',lambda e:_bucket_spread(e['spread'])),('GREEK_AGE_ABS',lambda e:_bucket_seconds(e['ga'])),('QUOTE_GREEK_SKEW_ABS',lambda e:_bucket_seconds(e['qg'])),('UNDERLYING_GREEK_SKEW_ABS',lambda e:_bucket_seconds(e['ug']))]
    for dte in sorted({e['dte'] for e in episode_meta}):
      if dte=='OTHER':continue
      subset=[e for e in episode_meta if e['dte']==dte]
      for name,fn in metrics:
        b=defaultdict(list)
        for e in subset:b[fn(e)].append(e)
        for bucket,g in sorted(b.items()):
            qrows.append((dte,name,bucket,len(g),float(np.median([abs(e['median']) for e in g])),float(np.quantile([e['peak'] for e in g],.95))))

    confidence=str(ts['confidence_state'])
    if len(dates)<5: ready='INSUFFICIENT_INDEPENDENT_DATES'
    elif confidence=='FAILED' or instability=='OBSERVED_UNSTABLE': ready='MODEL_INSTABILITY_UNRESOLVED'
    elif len(dates)<20:ready='EXPLORATORY_VALIDITY_ONLY'
    else:ready='READY_FOR_PREREGISTRATION_REVIEW_ONLY'
    if not persist:return {'dates':len(dates),'instability':instability,'timestamp_confidence':confidence,'readiness':ready,'dte_transfer':dte_transfer,'episode_transfer':ep_transfer,'model_comparison':model}
    c=get_connection(db_path)
    try:
      with c:
        cur=c.execute('''INSERT INTO local_surface_calibration_validity_v1_runs(validity_version,source_calibration_run_id,timestamp_semantics_run_id,fitted_at,distinct_session_dates,dte_14_20_instability_state,timestamp_confidence_state,readiness_state,config_hash,config_json,p_values_enabled,fdr_enabled,decision_enabled) VALUES(?,?,?,?,?,?,?,?,?,?,0,0,0)''',(VERSION,cr['id'],ts['id'],datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00','Z'),len(dates),instability,confidence,ready,h,cfgj)); rid=int(cur.lastrowid)
        c.executemany('''INSERT INTO local_surface_calibration_validity_v1_dte_transfer(validity_run_id,train_session_date,test_session_date,dte_bucket,stratum_count,test_observation_count,weighted_tail_fraction,max_stratum_tail_fraction,nominal_reference_tail,tail_inflation_ratio) VALUES(?,?,?,?,?,?,?,?,?,?)''',[(rid,*x[:7],NOMINAL,x[7]) for x in dte_transfer])
        c.executemany('''INSERT INTO local_surface_calibration_validity_v1_episode_transfer(validity_run_id,train_session_date,test_session_date,dte_bucket,train_episode_count,test_episode_count,train_q025,train_q975,test_tail_fraction) VALUES(?,?,?,?,?,?,?,?,?)''',[(rid,*x) for x in ep_transfer])
        c.executemany('''INSERT INTO local_surface_calibration_validity_v1_model_comparison(validity_run_id,dte_bucket,observation_count,quadratic_median_abs_residual,local_linear_median_abs_residual,quadratic_q95_abs_residual,local_linear_q95_abs_residual,local_linear_better_fraction) VALUES(?,?,?,?,?,?,?,?)''',[(rid,*x) for x in model])
        c.executemany('''INSERT INTO local_surface_calibration_validity_v1_quality_dte(validity_run_id,dte_bucket,metric_name,bucket_name,episode_count,median_abs_episode_median,q95_peak_abs_residual) VALUES(?,?,?,?,?,?,?)''',[(rid,*x) for x in qrows])
    finally:c.close()
    return {'run_id':rid,'dates':len(dates),'instability':instability,'timestamp_confidence':confidence,'readiness':ready,'dte_transfer_count':len(dte_transfer),'episode_transfer_count':len(ep_transfer),'model_comparison_count':len(model),'quality_rows':len(qrows)}
