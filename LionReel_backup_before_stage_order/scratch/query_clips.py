import os, sys
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger

ledger = ClipLedger()
with ledger._get_conn() as conn:
    rows = conn.execute("SELECT clip_id, source_id, start_s, end_s, times_used FROM clips WHERE source_id='cache_ByH9LuSILxU' AND start_s BETWEEN 30 AND 70").fetchall()
    print("Clips between 30s and 70s:", [dict(r) for r in rows])
