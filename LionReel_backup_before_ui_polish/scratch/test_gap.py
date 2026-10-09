import os, sys, json
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger, hamming_distance

ledger = ClipLedger()
with ledger._get_conn() as conn:
    cur = conn.execute("""
        SELECT * FROM clips 
        WHERE animal_type = 'cat' AND times_used == 0 AND pending_short_id IS NULL
        ORDER BY funny_score DESC, quality_score DESC
    """)
    eligible = [dict(r) for r in cur.fetchall()]
    eligible = [c for c in eligible if os.path.exists(c["source_url_or_path"]) and not ledger.is_blocked_source(c["source_url_or_path"])]

for min_gap in [10.0, 7.5, 5.0, 3.0]:
    selected = []
    selected_hashes = []
    for cand in eligible:
        try: c_hashes = json.loads(cand["fingerprint"])
        except: c_hashes = []
        
        is_dup = False
        for eh in selected_hashes:
            if c_hashes and eh:
                matches = sum(1 for ch in c_hashes for rh in eh if hamming_distance(ch, rh) <= 4)
                if matches >= 4:
                    is_dup = True
                    break
        if is_dup: continue

        too_close = False
        for prev in selected:
            if prev["source_id"] == cand["source_id"]:
                if abs(cand["start_s"] - prev["start_s"]) < min_gap:
                    too_close = True
                    break
        if too_close: continue

        selected.append(cand)
        selected_hashes.append(c_hashes)
    print(f"min_gap = {min_gap}s => {len(selected)} clips selected")
