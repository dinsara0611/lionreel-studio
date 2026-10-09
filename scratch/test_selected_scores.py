import os, sys
sys.path.insert(0, os.path.abspath("."))
from pet_detector import PetDetector
from auto_reframe import AutoReframeEngine

detector = PetDetector()
reframer = AutoReframeEngine(detector=detector)
video_path = "raw/cache_ByH9LuSILxU.mp4"

clips = [
    ("c_cache_ByH9LuSILxU_45_55", 45.0, 10.0),
    ("c_byh9_95_102", 95.0, 7.5),
    ("c_byh9_120_127", 120.0, 7.5),
    ("c_byh9_185_192", 185.0, 7.5),
    ("c_byh9_16_23", 16.0, 7.5),
    ("c_byh9_106_113", 106.0, 7.5),
    ("c_byh9_135_142", 135.0, 7.5),
    ("c_byh9_166_173", 166.0, 7.5),
    ("c_cache_ByH9LuSILxU_347_352", 347.1, 5.2),
    ("c_cache_ByH9LuSILxU_227_232", 227.8, 5.2),
]

for cid, start_s, dur_s in clips:
    plan = reframer.plan_reframe(video_path, start_s=start_s, dur_s=dur_s, layout_mode="smart_crop")
    score = plan.get("framing_score", 0.0)
    sharp = plan.get("sharpness", 0.0)
    status = plan.get("status", "reject")
    res = "PASS" if score >= 0.88 and sharp >= 15.0 else "REJECT"
    print(f"{cid} [{start_s}s - {start_s+dur_s}s]: {res} (score={score:.1%}, sharp={sharp:.1f})")
