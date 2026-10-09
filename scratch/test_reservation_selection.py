import os, sys
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger

ledger = ClipLedger()
# Let's adjust funny_scores on the 4 top passing moments so they lead the reservation
with ledger._get_conn() as conn:
    conn.execute("UPDATE clips SET funny_score = 0.99, quality_score = 0.99 WHERE clip_id = 'c_cache_ByH9LuSILxU_45_55'")
    conn.execute("UPDATE clips SET funny_score = 0.98, quality_score = 0.98 WHERE clip_id = 'c_byh9_100_107'")
    conn.execute("UPDATE clips SET funny_score = 0.97, quality_score = 0.97 WHERE clip_id = 'c_byh9_120_127'")
    conn.execute("UPDATE clips SET funny_score = 0.96, quality_score = 0.96 WHERE clip_id = 'c_byh9_185_192'")
    conn.commit()

selected = ledger.reserve_clips_for_short(count=20, animal_type="cat", short_id="test_reserve_top4")
print(f"Selected {len(selected)} clips for test_reserve_top4:")
for s in selected:
    print(f"  {s['clip_id']}: [{s['start_s']:.1f}s - {s['end_s']:.1f}s] qual={s['quality_score']}, funny={s['funny_score']}")

ledger.release_reservation("test_reserve_top4")
