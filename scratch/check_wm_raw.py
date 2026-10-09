import os, sys
sys.path.insert(0, os.path.abspath("."))
from watermark_detector import WatermarkDetector
detector = WatermarkDetector()

for f in ["raw_x_rBfKdlGyQ_1791108652.mp4", "cache_hY7m5jjJ9mM.mp4", "cache_ByH9LuSILxU.mp4"]:
    path = os.path.join("raw", f)
    if os.path.exists(path):
        is_blocked, hit_count, details = detector.verify_source_watermark(path, n_windows=6)
        print(f"{f}: is_blocked={is_blocked}, hit_count={hit_count}/6, details={details}")
