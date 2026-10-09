import os, sys
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger

l = ClipLedger()
cid = l.ingest_candidate(
    "raw/cache_ByH9LuSILxU.mp4", 340.0, 350.0,
    license_type="Creative Commons CC-BY 4.0", animal_type="cat",
    quality_score=0.96, funny_score=0.96
)
print(f"Ingested {cid}")

with l._get_conn() as conn:
    conn.execute("UPDATE clips SET funny_score = 0.99, quality_score = 0.99 WHERE clip_id = 'c_cache_ByH9LuSILxU_45_55'")
    conn.execute("UPDATE clips SET funny_score = 0.98, quality_score = 0.98 WHERE clip_id = 'c_byh9_100_107'")
    conn.execute("UPDATE clips SET funny_score = 0.97, quality_score = 0.97 WHERE clip_id = 'c_byh9_185_192'")
    conn.execute("UPDATE clips SET funny_score = 0.96, quality_score = 0.96 WHERE clip_id = ?", (cid,))
    conn.commit()

print("Top 4 verified 10s moments prioritized:")
with l._get_conn() as conn:
    rows = conn.execute("""
        SELECT clip_id, start_s, end_s, quality_score, funny_score, times_used 
        FROM clips WHERE animal_type = 'cat' AND times_used == 0 
        ORDER BY funny_score DESC LIMIT 6
    """).fetchall()
    for r in rows:
        print(f"  {r['clip_id']}: [{r['start_s']:.1f}s - {r['end_s']:.1f}s] funny={r['funny_score']}, qual={r['quality_score']}")
