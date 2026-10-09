import os, sys
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger

ledger = ClipLedger()
with ledger._get_conn() as conn:
    rows = conn.execute("SELECT * FROM blocked_sources").fetchall()
    print("Blocked sources table:", [dict(r) for r in rows])
