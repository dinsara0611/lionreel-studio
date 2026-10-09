import os, sys, json
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger
from pet_detector import PetDetector
from auto_reframe import AutoReframeEngine
from lion_automate_v97 import compute_clip_window

ledger = ClipLedger()
detector = PetDetector()
reframer = AutoReframeEngine(detector=detector)

reserved = ledger.reserve_clips(target_count=24, animal_mode="cat", short_id="test_acc_sim", min_required=4)
print(f"Reserved {len(reserved)} clips")

passing = []
for idx, c in enumerate(reserved):
    src = c["source_url_or_path"]
    win_start, win_end, win_ok = compute_clip_window(src, c["start_s"], c["end_s"], 10.0, tolerance=0.5)
    if not win_ok:
        print(f"Cand {idx+1} ({c['clip_id']}): win_ok=False")
        continue
    dur = win_end - win_start
    plan = reframer.plan_reframe(src, win_start, dur, layout_mode="smart_crop")
    score = plan.get("framing_score", 0.0)
    sharp = plan.get("sharpness", 0.0)
    status = plan.get("status")
    print(f"Cand {idx+1:02d} ({c['clip_id']}) [{win_start:.1f}s-{win_end:.1f}s]: status={status}, framing={score:.1%}, sharp={sharp:.1f}")
    if status == "pass":
        passing.append({
            "cand": idx + 1, "clip_id": c["clip_id"], "source": c["source_id"],
            "start_s": win_start, "dur_s": dur, "score": score, "sharpness": sharp
        })

print(f"\nStage A Passing: {len(passing)}")

# NMS
passing.sort(key=lambda x: x["score"], reverse=True)
nms_passing = []
for cand in passing:
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
                print(f"  NMS SUPPRESSED: Cand {cand['cand']} ({c_start:.1f}s) overlaps with Cand {kept['cand']} ({k_start:.1f}s)")
                break
    if not suppressed:
        nms_passing.append(cand)

print(f"\nPost-NMS Passing: {len(nms_passing)}")
for p in nms_passing:
    print(f"  => Cand {p['cand']} ({p['clip_id']}) [{p['start_s']:.1f}s - {p['start_s']+p['dur_s']:.1f}s]: framing={p['score']:.1%}, sharp={p['sharpness']:.1f}")

ledger.release_reservation("test_acc_sim")
