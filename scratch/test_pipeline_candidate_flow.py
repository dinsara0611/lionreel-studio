import os, sys, json
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger, hamming_distance
from pet_detector import PetDetector
from auto_reframe import AutoReframeEngine

ledger = ClipLedger()
detector = PetDetector()
reframer = AutoReframeEngine(detector=detector)
video_path = "raw/cache_ByH9LuSILxU.mp4"

with ledger._get_conn() as conn:
    cur = conn.execute("""
        SELECT * FROM clips 
        WHERE animal_type = 'cat' AND times_used == 0 AND pending_short_id IS NULL
        ORDER BY funny_score DESC, quality_score DESC
    """)
    eligible = [dict(r) for r in cur.fetchall()]
    eligible = [c for c in eligible if os.path.exists(c["source_url_or_path"]) and not ledger.is_blocked_source(c["source_url_or_path"])]

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
            if abs(cand["start_s"] - prev["start_s"]) < 4.0:
                too_close = True
                break
    if too_close: continue

    selected.append(cand)
    selected_hashes.append(c_hashes)

print(f"Candidates selected for Stage A: {len(selected)}")
evaluated_passing = []
for idx, c in enumerate(selected):
    plan = reframer.plan_reframe(video_path, start_s=c["start_s"], dur_s=7.5, layout_mode="smart_crop")
    score = plan.get("framing_score", 0.0)
    sharp = plan.get("sharpness", 0.0)
    if score >= 0.88 and sharp >= 15.0:
        evaluated_passing.append({
            "candidate": idx + 1,
            "clip_id": c["clip_id"],
            "source": c["source_id"],
            "start_s": c["start_s"],
            "dur_s": 7.5,
            "score": score,
            "sharpness": sharp
        })
        print(f"  PASS: Cand {idx+1} ({c['clip_id']}) [{c['start_s']}s] score={score:.1%}, sharp={sharp:.1f}")

print(f"Total Stage A passing: {len(evaluated_passing)}")

# Apply NMS (10s window separation)
evaluated_passing.sort(key=lambda x: x["score"], reverse=True)
nms_passing = []
for cand in evaluated_passing:
    c_src = cand["source"]
    c_start = cand["start_s"]
    c_end = cand["start_s"] + cand["dur_s"]
    suppressed = False
    for kept in nms_passing:
        if kept["source"] == c_src:
            k_start = kept["start_s"]
            k_end = kept["start_s"] + kept["dur_s"]
            if abs(c_start - k_start) < 10.0 or not (c_end <= k_start or k_end <= c_start):
                suppressed = True
                print(f"  NMS SUPPRESSED: Cand {cand['candidate']} ({c_start}s, {cand['score']:.1%}) overlaps with Cand {kept['candidate']} ({k_start}s, {kept['score']:.1%})")
                break
    if not suppressed:
        nms_passing.append(cand)

print(f"\nFinal Post-NMS Passing Candidates: {len(nms_passing)}")
for p in nms_passing:
    print(f"  => Cand {p['candidate']} [{p['start_s']}s - {p['start_s']+p['dur_s']}s]: score={p['score']:.1%}, sharp={p['sharpness']:.1f}")
