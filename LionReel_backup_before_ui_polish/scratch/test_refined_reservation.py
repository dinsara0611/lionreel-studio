import os, sys
sys.path.insert(0, os.path.abspath("."))
import json
from clip_ledger import ClipLedger, hamming_distance

ledger = ClipLedger()

def simulate_refined_reserve(count=20, animal_type="cat", short_id="test_sim"):
    with ledger._get_conn() as conn:
        cur = conn.execute("""
            SELECT * FROM clips 
            WHERE animal_type = ? AND times_used == 0 AND (pending_short_id IS NULL OR pending_short_id = ?)
            ORDER BY funny_score DESC, quality_score DESC
        """, (animal_type, short_id))
        eligible = [dict(r) for r in cur.fetchall()]
        eligible = [c for c in eligible if os.path.exists(c["source_url_or_path"]) and not ledger.is_blocked_source(c["source_url_or_path"])]

    print(f"Total eligible on disk: {len(eligible)}")
    source_groups = {}
    for cand in eligible:
        src_id = cand.get("source_id") or os.path.basename(cand["source_url_or_path"])
        source_groups.setdefault(src_id, []).append(cand)

    # Sort each group by funny_score DESC, quality_score DESC (do not shuffle!)
    for src_id in source_groups:
        source_groups[src_id].sort(key=lambda c: (c.get("funny_score", 0.0), c.get("quality_score", 0.0)), reverse=True)

    selected = []
    selected_hashes = []
    source_keys = list(source_groups.keys())

    actual_count = min(count, len(eligible))
    while len(selected) < actual_count:
        progress_made = False
        for src_id in source_keys:
            if len(selected) >= actual_count:
                break
            group = source_groups[src_id]
            if not group:
                continue

            cand = group.pop(0)
            try:
                c_hashes = json.loads(cand["fingerprint"])
            except:
                c_hashes = []

            # Check near-duplicates
            is_near_dup = False
            for ex_hashes in selected_hashes:
                if c_hashes and ex_hashes:
                    matches = sum(1 for ch in c_hashes for rh in ex_hashes if hamming_distance(ch, rh) <= 4)
                    if matches >= 4:
                        is_near_dup = True
                        break
            if is_near_dup:
                print(f"Skipped {cand['clip_id']} [{cand['start_s']:.1f}-{cand['end_s']:.1f}]: near-dup fingerprint")
                continue

            # Reservation deduplication threshold: 4.0s
            c_start = cand["start_s"]
            c_end = cand["end_s"]
            too_close = False
            for prev in selected:
                if prev.get("source_url_or_path") == cand["source_url_or_path"] or prev.get("source_id") == cand.get("source_id"):
                    p_start = prev["start_s"]
                    p_end = prev["end_s"]
                    if abs(c_start - p_start) < 4.0:
                        too_close = True
                        print(f"Skipped {cand['clip_id']} [{c_start:.1f}-{c_end:.1f}]: too close to {prev['clip_id']} [{p_start:.1f}-{p_end:.1f}]")
                        break
            if too_close:
                continue

            selected.append(cand)
            selected_hashes.append(c_hashes)

        # Check if any candidates remain across any group
        if not any(len(g) > 0 for g in source_groups.values()):
            break

    return selected

selected = simulate_refined_reserve(count=24)
print(f"Refined reserve selected: {len(selected)} clips")
for i, s in enumerate(selected):
    print(f"  [{i+1:02d}] {s['clip_id']}: {s['source_id']} [{s['start_s']:.1f}s - {s['end_s']:.1f}s] funny={s['funny_score']}")
