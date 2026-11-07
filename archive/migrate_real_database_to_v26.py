import sqlite3
from pathlib import Path
from src.database.repository import resolve_db_path
ROOT=Path(__file__).resolve().parent; MIGRATION=ROOT/'migrations'/'026_shadow_risk_plan_lifecycle.sql'
db=resolve_db_path(); c=sqlite3.connect(db)
try:
 cur=c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]
 if int(cur)!=25: raise RuntimeError(f'Expected schema 25 before migration 026; found {cur}.')
 c.executescript(MIGRATION.read_text(encoding='utf-8')); now=c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]
 if int(now)!=26: raise RuntimeError(f'Migration 026 did not reach schema 26; found {now}.')
 print(f'Christiania database migrated: 25 -> 26 ({db})')
finally:c.close()
