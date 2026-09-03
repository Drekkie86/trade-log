import json
from datetime import datetime,timezone
from pathlib import Path
from src.database.repository import get_connection

def main():
 c=get_connection()
 try:
  run=dict(c.execute('SELECT * FROM local_surface_calibration_validity_v1_runs ORDER BY id DESC LIMIT 1').fetchone())
  ts=dict(c.execute('SELECT * FROM thetadata_timestamp_semantics_v1_runs WHERE id=?',(run['timestamp_semantics_run_id'],)).fetchone())
  d=[dict(r) for r in c.execute('SELECT * FROM local_surface_calibration_validity_v1_dte_transfer WHERE validity_run_id=? ORDER BY train_session_date,test_session_date,dte_bucket',(run['id'],))]
  e=[dict(r) for r in c.execute('SELECT * FROM local_surface_calibration_validity_v1_episode_transfer WHERE validity_run_id=? ORDER BY train_session_date,test_session_date,dte_bucket',(run['id'],))]
  m=[dict(r) for r in c.execute('SELECT * FROM local_surface_calibration_validity_v1_model_comparison WHERE validity_run_id=? ORDER BY dte_bucket',(run['id'],))]
  q=[dict(r) for r in c.execute('SELECT * FROM local_surface_calibration_validity_v1_quality_dte WHERE validity_run_id=? ORDER BY dte_bucket,metric_name,bucket_name',(run['id'],))]
 finally:c.close()
 obj={'run':run,'timestamp_semantics':ts,'dte_transfer':d,'episode_transfer':e,'model_comparison':m,'quality_by_dte':q,'guardrail':'Discovery-only calibration validity diagnostics. No p-values, FDR/BH, candidate/admission decision, or edge claim.'}
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'); root=Path.home()/'Downloads'; j=root/f'Christiania_Calibration_Validity_V1_{stamp}.json'; md=root/f'Christiania_Calibration_Validity_V1_{stamp}.md'; j.write_text(json.dumps(obj,indent=2),encoding='utf-8')
 lines=['# Christiania CALIBRATION_VALIDITY_V1','',f"- dates: **{run['distinct_session_dates']}**",f"- timestamp confidence: **{run['timestamp_confidence_state']}**",f"- DTE 14–20 state: **{run['dte_14_20_instability_state']}**",f"- readiness: **{run['readiness_state']}**",'- p-values/FDR/decision: **disabled**','','## Raw-row DTE transfer','| train | test | DTE | N | weighted tail | inflation |','|---|---|---|---:|---:|---:|']
 for r in d:lines.append(f"| {r['train_session_date']} | {r['test_session_date']} | {r['dte_bucket']} | {r['test_observation_count']} | {r['weighted_tail_fraction']:.4f} | {r['tail_inflation_ratio']:.2f}x |")
 lines += ['','## Episode-level transfer','| train | test | DTE | train episodes | test episodes | tail fraction |','|---|---|---|---:|---:|---:|']
 for r in e:lines.append(f"| {r['train_session_date']} | {r['test_session_date']} | {r['dte_bucket']} | {r['train_episode_count']} | {r['test_episode_count']} | {r['test_tail_fraction']:.4f} |")
 lines += ['','## Model-form comparison','| DTE | N | quad median | linear median | quad q95 | linear q95 | linear better |','|---|---:|---:|---:|---:|---:|---:|']
 for r in m:lines.append(f"| {r['dte_bucket']} | {r['observation_count']} | {r['quadratic_median_abs_residual']:.6f} | {r['local_linear_median_abs_residual']:.6f} | {r['quadratic_q95_abs_residual']:.6f} | {r['local_linear_q95_abs_residual']:.6f} | {r['local_linear_better_fraction']:.3f} |")
 lines += ['','## Guardrail','Discovery only. No inferential or trading decision is enabled.']
 md.write_text('\n'.join(lines)+'\n',encoding='utf-8'); print(md); print(j)
if __name__=='__main__':main()
