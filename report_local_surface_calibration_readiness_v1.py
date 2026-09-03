from __future__ import annotations
import json
from datetime import datetime,timezone
from pathlib import Path
from src.database.repository import get_connection

def main():
 c=get_connection()
 try:
  r=c.execute('SELECT * FROM local_surface_calibration_readiness_v1_runs ORDER BY id DESC LIMIT 1').fetchone()
  if r is None:raise SystemExit('No v22 calibration-readiness run found.')
  eps=c.execute('SELECT * FROM local_surface_calibration_readiness_v1_episodes WHERE calibration_run_id=? ORDER BY peak_abs_centered_residual DESC LIMIT 40',(r['id'],)).fetchall()
  cd=c.execute('SELECT * FROM local_surface_calibration_readiness_v1_cross_day_contracts WHERE calibration_run_id=? ORDER BY max_abs_daily_median DESC LIMIT 40',(r['id'],)).fetchall()
  qs=c.execute('SELECT * FROM local_surface_calibration_readiness_v1_quality_episode_summary WHERE calibration_run_id=? ORDER BY metric_name,bucket_name',(r['id'],)).fetchall()
  tr=c.execute('SELECT * FROM provider_model_timing_reconstruction_v1_runs ORDER BY id DESC LIMIT 1').fetchone()
 finally:c.close()
 def d(x):return dict(x) if x is not None else None
 payload={'run':d(r),'timing_reconstruction_run':d(tr),'top_episodes':[d(x) for x in eps],'cross_day_contracts':[d(x) for x in cd],'quality_episode_summary':[d(x) for x in qs],'guardrail':'Discovery-only calibration-readiness diagnostics. No p-values, FDR/BH, candidate/admission decision, or edge claim.'}
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'); out=Path.home()/'Downloads'; out.mkdir(exist_ok=True)
 jp=out/f'Christiania_Calibration_Readiness_V1_{stamp}.json'; mp=out/f'Christiania_Calibration_Readiness_V1_{stamp}.md'; jp.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding='utf-8')
 lines=['# Christiania CALIBRATION_READINESS_V1','',f"- observations: **{r['observation_count']}**",f"- dates: **{r['distinct_session_dates']}**",f"- episodes: **{r['episode_count']}**",f"- cross-day contracts: **{r['cross_day_contract_count']}**",f"- timing native/reconstructed/unavailable: **{r['native_timing_count']} / {r['reconstructed_timing_count']} / {r['unavailable_timing_count']}**",f"- readiness: **{r['readiness_state']}**",'- p-values/FDR/decision: **disabled**','','## Top persistent/large episodes','| underlying | expiry | strike | right | date | obs | median | peak | persistence | sign consistency |','|---|---|---:|---|---|---:|---:|---:|---:|---:|']
 for x in eps:lines.append(f"| {x['underlying']} | {x['expiration']} | {x['strike']} | {x['right']} | {x['session_date']} | {x['observation_count']} | {x['median_centered_residual']:.6f} | {x['peak_abs_centered_residual']:.6f} | {x['persistence_ratio']:.3f} | {x['sign_consistency_fraction']:.3f} |")
 lines += ['','## Cross-day recurring contracts','| underlying | expiry | strike | right | dates | obs | median daily | max abs daily | range | same sign | agreement |','|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|']
 for x in cd:lines.append(f"| {x['underlying']} | {x['expiration']} | {x['strike']} | {x['right']} | {x['session_date_count']} | {x['total_observation_count']} | {x['median_of_daily_medians']:.6f} | {x['max_abs_daily_median']:.6f} | {x['daily_median_range']:.6f} | {x['same_sign_all_nonzero_days']} | {x['sign_agreement_fraction']:.3f} |")
 lines += ['','## Episode-level quality sensitivity','| metric | bucket | episodes | median abs episode median | q95 peak | median persistence |','|---|---|---:|---:|---:|---:|']
 for x in qs:lines.append(f"| {x['metric_name']} | {x['bucket_name']} | {x['episode_count']} | {x['median_abs_episode_median']:.6f} | {x['q95_peak_abs_residual']:.6f} | {x['median_persistence_ratio']:.3f} |")
 lines += ['','## Guardrail','','These are discovery-only calibration-readiness diagnostics. Reconstructed timing values are derived from persisted raw evidence and retain explicit provenance. No inferential or trading decision is enabled.']
 mp.write_text('\n'.join(lines)+'\n',encoding='utf-8'); print(mp); print(jp)
if __name__=='__main__':main()
