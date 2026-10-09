import os, sys
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger
import cv2

ledger = ClipLedger()
with ledger._get_conn() as conn:
    rows = conn.execute("SELECT clip_id, source_id, start_s, end_s, quality_score, funny_score, times_used, pending_short_id, pool_cycle FROM clips WHERE source_id='cache_ByH9LuSILxU' ORDER BY start_s").fetchall()
    print(f"Total clips for cache_ByH9LuSILxU: {len(rows)}")
    for r in rows:
        print(f"  {r['clip_id']}: [{r['start_s']:.1f}s - {r['end_s']:.1f}s], dur={r['end_s']-r['start_s']:.1f}s, qual={r['quality_score']}, used={r['times_used']}, cycle={r['pool_cycle']}, pending={r['pending_short_id']}")
