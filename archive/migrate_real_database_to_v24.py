from __future__ import annotations
import shutil, sqlite3, tempfile
from datetime import UTC, datetime
from pathlib import Path
from src.database.repository import DB_PATH

ROOT=Path(__file__).resolve().parent
MIG=ROOT/'migrations'/'024_model_governance_prospective_freeze.sql'

def version(p):
    c=sqlite3.connect(p)
    try:return c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]
    finally:c.close()

def apply(p):
    c=sqlite3.connect(p)
    try:
        c.executescript(MIG.read_text(encoding='utf-8')); c.commit()
        assert c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]==24
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
    finally:c.close()

def main():
    print('Christiania - real database migration to v24')
    print('---------------------------------------------')
    if not Path(DB_PATH).exists(): raise SystemExit('trade_log.db not found')
    v=version(DB_PATH); print(f'Current schema version: v{v}')
    if v!=23: raise SystemExit(f'Expected v23 before migration, found v{v}')
    print('Rehearsing migration on a temporary copy...')
    with tempfile.TemporaryDirectory() as td:
        cp=Path(td)/'trade_log.db'; shutil.copy2(DB_PATH,cp); apply(cp)
    print('Rehearsal successful.')
    stamp=datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    backup=ROOT/f'trade_log_before_v24_{stamp}.db'; shutil.copy2(DB_PATH,backup); print(f'Backup created: {backup.name}')
    apply(DB_PATH)
    print('Migration successful.')
    print('Database schema: v24')
    print('SQLite integrity_check: ok')
    print('Foreign-key check: clean')
    print('Model-governance and prospective-freeze objects installed; scientific firewall remains disabled.')

if __name__=='__main__': main()
