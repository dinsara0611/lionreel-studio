import os, sys
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger

ledger = ClipLedger()
with ledger._get_conn() as conn:
    rows = conn.execute("SELECT clip_id, start_s, end_s, quality_score, funny_score, times_used FROM clips WHERE source_id='cache_ByH9LuSILxU' ORDER BY start_s").fetchall()
    print(f"Total clips in cache_ByH9LuSILxU: {len(rows)}")
    for r in rows:
        print(f"  {r['clip_id']:<30} [{r['start_s']:>5.1f}s - {r['end_s']:>5.1f}s] qual={r['quality_score']:<5} funny={r['funny_score']:<5} used={r['times_used']}")
