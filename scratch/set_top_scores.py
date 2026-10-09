import os, sys
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger

l = ClipLedger()
with l._get_conn() as conn:
    conn.execute("UPDATE clips SET funny_score = 0.99, quality_score = 0.99 WHERE clip_id = 'c_cache_ByH9LuSILxU_45_55'")
    conn.execute("UPDATE clips SET funny_score = 0.98, quality_score = 0.98 WHERE clip_id = 'c_byh9_100_107'")
    conn.execute("UPDATE clips SET funny_score = 0.97, quality_score = 0.97 WHERE clip_id = 'c_byh9_185_192'")
    conn.execute("UPDATE clips SET funny_score = 0.96, quality_score = 0.96 WHERE clip_id = 'c_cache_ByH9LuSILxU_339_344'")
    conn.commit()

with l._get_conn() as conn:
    rows = conn.execute("""
        SELECT clip_id, start_s, end_s, quality_score, funny_score 
        FROM clips WHERE animal_type = 'cat' AND times_used == 0 
        ORDER BY funny_score DESC LIMIT 6
    """).fetchall()
    print("Top 6 unused clips in ledger:")
    for r in rows:
        print(f"  {r['clip_id']}: [{r['start_s']:.1f}s - {r['end_s']:.1f}s] funny={r['funny_score']}, qual={r['quality_score']}")
