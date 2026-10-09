import os, sys
sys.path.insert(0, os.path.abspath("."))
from pet_detector import PetDetector
from auto_reframe import AutoReframeEngine

detector = PetDetector()
reframer = AutoReframeEngine(detector=detector)
video_path = "raw/cache_ByH9LuSILxU.mp4"

# Let's test 10s windows every 5 seconds
passing_windows = []
for start_s in range(0, 345, 5):
    dur_s = 10.0
    plan = reframer.plan_reframe(video_path, start_s=float(start_s), dur_s=dur_s, layout_mode="smart_crop")
    score = plan.get("framing_score", 0.0)
    sharp = plan.get("sharpness", 0.0)
    if score >= 0.88 and sharp >= 15.0:
        passing_windows.append({
            "start_s": float(start_s),
            "end_s": float(start_s + dur_s),
            "score": score,
            "sharpness": sharp
        })
        print(f"PASS: [{start_s:.1f}s - {start_s+dur_s:.1f}s] score={score:.1%}, sharp={sharp:.1f}")

print(f"\nTotal passing windows: {len(passing_windows)}")
# Filter with 10s non-overlap:
non_overlapping = []
for w in sorted(passing_windows, key=lambda x: x["score"], reverse=True):
    overlap = False
    for kept in non_overlapping:
        if abs(w["start_s"] - kept["start_s"]) < 10.0 or not (w["end_s"] <= kept["start_s"] or kept["end_s"] <= w["start_s"]):
            overlap = True
            break
    if not overlap:
        non_overlapping.append(w)

print(f"Non-overlapping passing windows (>= 10s apart): {len(non_overlapping)}")
for w in non_overlapping:
    print(f"  [{w['start_s']}s - {w['end_s']}s] score={w['score']:.1%}, sharp={w['sharpness']:.1f}")
