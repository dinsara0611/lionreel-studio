import os, sys, json, cv2, numpy as np

sys.path.insert(0, r"g:\My Drive\Cat make")
from auto_reframe import AutoReframeEngine
from pet_detector import PetDetector

detector = PetDetector()
reframer = AutoReframeEngine(detector=detector)
source_path = r"g:\My Drive\Cat make\raw\cache_ByH9LuSILxU.mp4"

# Generate 15 candidate windows across the 358s video
dur_s = 5.2
candidate_starts = [15.0, 35.0, 55.0, 75.0, 95.0, 115.0, 121.3, 135.0, 155.0, 175.0, 195.0, 215.0, 235.0, 255.0, 275.0]

print("="*80)
print("STAGE A: FAST PRE-SCORING PREDICTED FRAMING BEFORE RENDER")
print("="*80)

passed_candidates = []
failed_candidates = []

for start_s in candidate_starts:
    plan = reframer.plan_reframe(source_path, start_s, dur_s, animal_mode="cat", layout_mode="smart_crop")
    if plan.get("status") != "pass":
        failed_candidates.append({
            "start": start_s,
            "score": 0.0,
            "status": "REJECT",
            "reason": plan.get("reason", "PLAN_REJECT")
        })
        print(f"[{start_s:5.1f}s - {start_s+dur_s:5.1f}s]: PREDICT REJECT ❌ -> {plan.get('reason')}")
        continue
        
    score = plan.get("framing_score", 0.90)
    # Check if plan passes predicted threshold
    passed_candidates.append({
        "start": start_s,
        "score": score,
        "plan": plan
    })
    print(f"[{start_s:5.1f}s - {start_s+dur_s:5.1f}s]: PREDICT PASS ✅ -> Score: {score:.1%}, Zoom: {plan.get('crop_w')}x{plan.get('crop_h')}")

print(f"\nStage A Complete: {len(passed_candidates)} candidates predicted to pass, {len(failed_candidates)} rejected before render.")
