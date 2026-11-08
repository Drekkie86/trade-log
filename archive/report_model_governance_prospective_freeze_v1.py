from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
from src.database.repository import DB_PATH, get_connection


def report(db_path=DB_PATH):
    c=get_connection(db_path)
    try:
        run=c.execute('SELECT * FROM prospective_research_freeze_v1_runs ORDER BY id DESC LIMIT 1').fetchone()
        if run is None: raise RuntimeError('No prospective freeze run exists.')
        rid=run['id']
        models=[dict(r) for r in c.execute('SELECT * FROM research_model_registry_v1 ORDER BY id')]
        hyps=[dict(r) for r in c.execute('SELECT * FROM prospective_research_hypotheses_v1 WHERE freeze_run_id=? ORDER BY hypothesis_key',(rid,))]
        baselines=[dict(r) for r in c.execute('SELECT * FROM prospective_model_dte_baseline_v1 WHERE freeze_run_id=? ORDER BY dte_bucket',(rid,))]
        phases=[dict(r) for r in c.execute('SELECT evidence_phase,COUNT(*) AS n FROM v_local_surface_v2_prospective_partition_v1 GROUP BY evidence_phase ORDER BY evidence_phase')]
        payload={'run':dict(run),'models':models,'hypotheses':hyps,'dte_baselines':baselines,'current_evidence_partition':phases,
                 'guardrail':'Prospective observation-only protocol. No p-values, FDR/BH, admission, candidate creation, model auto-selection, or trading decision.'}
    finally:c.close()
    stamp=datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    out=Path.home()/'Downloads'
    jp=out/f'Christiania_Model_Governance_Prospective_Freeze_V1_{stamp}.json'
    mp=out/f'Christiania_Model_Governance_Prospective_Freeze_V1_{stamp}.md'
    jp.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding='utf-8')
    lines=['# Christiania MODEL_GOVERNANCE_PROSPECTIVE_FREEZE_V1','',f"- freeze run: **{run['id']}**",f"- frozen through: **{run['frozen_through_session_date']}**",f"- prospective starts: **{run['prospective_start_session_date']}**",f"- source readiness: **{run['source_readiness_state']}**",f"- DTE 14–20: **{run['source_dte_14_20_state']}**",'- p-values/FDR/admission/decision: **disabled**','','## Model registry','| model | role | evidence enabled |','|---|---|---:|']
    for m in models: lines.append(f"| {m['model_key']} | {m['governance_role']} | {m['evidence_use_enabled']} |")
    lines += ['','## Frozen prospective hypotheses','| key | minimum independent dates | unit |','|---|---:|---|']
    for h in hyps: lines.append(f"| {h['hypothesis_key']} | {h['minimum_independent_dates']} | {h['primary_unit']} |")
    lines += ['','## DTE baseline carried into prospective phase','| DTE | linear better | raw max inflation | episode tail range | state |','|---|---:|---:|---:|---|']
    for b in baselines: lines.append(f"| {b['dte_bucket']} | {b['local_linear_better_fraction']:.3f} | {b['raw_transfer_max_inflation']:.2f}x | {b['episode_transfer_min_tail']:.3f}–{b['episode_transfer_max_tail']:.3f} | {b['review_state']} |")
    lines += ['','## Current evidence partition']
    for p in phases: lines.append(f"- {p['evidence_phase']}: **{p['n']}** rows")
    lines += ['','## Guardrail','',payload['guardrail']]
    mp.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(mp); print(jp)
    return payload

if __name__=='__main__': report()
