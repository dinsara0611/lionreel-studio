import sqlite3
import os

db_path = 'clip_ledger.db'
if not os.path.exists(db_path):
    db_path = 'data/clip_ledger.db'

print(f"Opening DB: {db_path}")
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)

for t in tables:
    cur.execute(f"PRAGMA table_info({t})")
    cols = [(c[1], c[2]) for c in cur.fetchall()]
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    cnt = cur.fetchone()[0]
    print(f"\nTable: {t} (rows: {cnt})")
    for col_name, col_type in cols:
        print(f"  {col_name} ({col_type})")
