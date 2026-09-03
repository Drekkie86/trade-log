from __future__ import annotations
import sqlite3,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent; DB=ROOT/'trade_log.db'; MIG=ROOT/'migrations/022_calibration_readiness_and_timing_recovery.sql'; BEFORE=21; AFTER=22
def connect(p):
 c=sqlite3.connect(p); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
def version(c):return int(c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0])
def backup(a,b):
 s=connect(a); d=connect(b); s.backup(d); d.commit(); d.close(); s.close()
def verify(c):
 assert version(c)==AFTER
 assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
 names={r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
 need={'provider_model_timing_reconstruction_v1_runs','provider_model_timing_reconstruction_v1','v_provider_model_timing_effective_v1','v_local_surface_null_v1_discovery_membership_timing_v1','local_surface_calibration_readiness_v1_runs','local_surface_calibration_readiness_v1_episodes','local_surface_calibration_readiness_v1_cross_day_contracts','local_surface_calibration_readiness_v1_quality_episode_summary'}
 if not need<=names:raise RuntimeError(f'Missing v22 objects: {sorted(need-names)}')
def main():
 print('Christiania - real database migration to v22'); print('---------------------------------------------')
 sql=MIG.read_text(encoding='utf-8'); c=connect(DB); cur=version(c); c.close(); print(f'Current schema version: v{cur}')
 if cur==AFTER:
  c=connect(DB); verify(c); c.close(); print('Database is already valid v22.'); return 0
 if cur!=BEFORE: print(f'Expected v{BEFORE}; found v{cur}.'); return 1
 print('Rehearsing migration on a temporary copy...')
 with tempfile.TemporaryDirectory() as td:
  q=Path(td)/'r.db'; backup(DB,q); c=connect(q); c.executescript(sql); verify(c); c.close()
 print('Rehearsal successful.')
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'); b=ROOT/f'trade_log_before_v22_{stamp}.db'; backup(DB,b); print(f'Backup created: {b.name}')
 c=connect(DB)
 try:c.executescript(sql); verify(c); c.commit()
 except Exception:
  c.close(); backup(b,DB); print('Migration failed. Original database restored.'); raise
 c.close(); print('Migration successful.'); print('Database schema: v22'); print('SQLite integrity_check: ok'); print('Foreign-key check: clean'); print('Historical timing recovery is provenance-preserving; inferential flags remain disabled.'); return 0
if __name__=='__main__':sys.exit(main())
