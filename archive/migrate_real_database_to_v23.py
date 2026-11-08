from __future__ import annotations
import sqlite3,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent; DB=ROOT/'trade_log.db'; MIG=ROOT/'migrations/023_calibration_validity_v1.sql'; BEFORE=22; AFTER=23
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
 need={'thetadata_timestamp_semantics_v1_runs','local_surface_calibration_validity_v1_runs','local_surface_calibration_validity_v1_dte_transfer','local_surface_calibration_validity_v1_episode_transfer','local_surface_calibration_validity_v1_model_comparison','local_surface_calibration_validity_v1_quality_dte'}
 if not need<=names:raise RuntimeError(f'Missing v23 objects: {sorted(need-names)}')
def main():
 print('Christiania - real database migration to v23'); print('---------------------------------------------')
 sql=MIG.read_text(encoding='utf-8'); c=connect(DB); cur=version(c); c.close(); print(f'Current schema version: v{cur}')
 if cur==AFTER:
  c=connect(DB); verify(c); c.close(); print('Database is already valid v23.'); return 0
 if cur!=BEFORE: print(f'Expected v{BEFORE}; found v{cur}.'); return 1
 print('Rehearsing migration on a temporary copy...')
 with tempfile.TemporaryDirectory() as td:
  q=Path(td)/'r.db'; backup(DB,q); c=connect(q); c.executescript(sql); verify(c); c.close()
 print('Rehearsal successful.')
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'); b=ROOT/f'trade_log_before_v23_{stamp}.db'; backup(DB,b); print(f'Backup created: {b.name}')
 c=connect(DB)
 try:c.executescript(sql); verify(c); c.commit()
 except Exception:
  c.close(); backup(b,DB); print('Migration failed. Original database restored.'); raise
 c.close(); print('Migration successful.'); print('Database schema: v23'); print('SQLite integrity_check: ok'); print('Foreign-key check: clean'); print('Calibration validity objects installed; inferential flags remain disabled.'); return 0
if __name__=='__main__':sys.exit(main())
