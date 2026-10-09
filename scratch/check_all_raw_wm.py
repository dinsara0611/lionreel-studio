import os, sys
sys.path.insert(0, os.path.abspath("."))
from watermark_detector import WatermarkDetector

detector = WatermarkDetector()
raw_dir = "raw"
for f in os.listdir(raw_dir):
    if f.endswith(".mp4"):
        p = os.path.join(raw_dir, f)
        is_blocked, hit_count, details = detector.verify_source_watermark(p, n_windows=6)
        print(f"{f}: blocked={is_blocked}, hits={hit_count}/6, details={details}")
