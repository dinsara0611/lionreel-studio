import os, sys
sys.path.insert(0, os.path.abspath("."))
from auto_reframe import AutoReframeEngine
from pet_detector import PetDetector

engine = AutoReframeEngine(detector=PetDetector())
src = "raw/cache_ByH9LuSILxU.mp4"
candidates = [
    (338.0, 10.0),
    (340.0, 10.0),
    (342.0, 10.0),
    (115.0, 10.0),
    (116.0, 10.0),
    (117.0, 10.0),
    (118.0, 10.0),
    (16.0, 10.0),
    (60.0, 10.0),
    (178.0, 10.0)
]
for st, dur in candidates:
    p = engine.plan_reframe(src, st, dur, layout_mode="smart_crop")
    status = p.get("status")
    score = p.get("framing_score", 0.0)
    sharp = p.get("sharpness", 0.0)
    reason = p.get("reason", "")
    print(f"Window {st:.1f}s-{st+dur:.1f}s ({dur:.1f}s): status={status}, framing={score:.1%}, sharp={sharp:.1f}, reason={reason}")
