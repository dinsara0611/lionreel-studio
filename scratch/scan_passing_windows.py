import os, sys
sys.path.insert(0, os.path.abspath("."))
import cv2
from pet_detector import PetDetector
from auto_reframe import AutoReframeEngine

detector = PetDetector()
reframer = AutoReframeEngine(detector=detector)
video_path = "raw/cache_ByH9LuSILxU.mp4"

# Let's test 10s windows every 10 seconds from 0 to 350s
results = []
for start_s in range(5, 345, 10):
    dur_s = 10.0
    plan = reframer.plan_reframe(video_path, start_s=float(start_s), dur_s=dur_s, layout_mode="smart_crop")
    score = plan.get("framing_score", 0.0)
    sharp = plan.get("sharpness", 0.0)
    status = plan.get("status", "reject")
    if score >= 0.88 and sharp >= 15.0:
        results.append((start_s, start_s + dur_s, score, sharp, status))
        print(f"[{start_s}s - {start_s+dur_s}s]: SCORE={score:.1%}, SHARP={sharp:.1f} => PASS!")

print(f"\nTotal passing 10s windows found: {len(results)}")
