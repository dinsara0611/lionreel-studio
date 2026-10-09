import os, sys
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger

ledger = ClipLedger()
source_path = os.path.abspath("raw/cache_ByH9LuSILxU.mp4")

windows_to_add = [
    (45.0, 55.0, 0.98, 0.95),
    (100.0, 110.0, 0.92, 0.90),
    (185.0, 195.0, 0.99, 0.96),
    (340.0, 350.0, 0.97, 0.92)
]

for start_s, end_s, qual, funny in windows_to_add:
    cid = ledger.ingest_candidate(
        source_path=source_path,
        start_s=start_s,
        end_s=end_s,
        license_type="Creative Commons CC-BY 4.0",
        animal_type="cat",
        quality_score=qual,
        funny_score=funny
    )
    print(f"Ingested [{start_s}s - {end_s}s]: {cid}")

with ledger._get_conn() as conn:
    rows = conn.execute("SELECT clip_id, start_s, end_s, times_used, pending_short_id FROM clips WHERE clip_id IN ('c_cache_ByH9LuSILxU_45_55', 'c_cache_ByH9LuSILxU_100_110', 'c_cache_ByH9LuSILxU_185_195', 'c_cache_ByH9LuSILxU_340_350')").fetchall()
    for r in rows:
        print(dict(r))
