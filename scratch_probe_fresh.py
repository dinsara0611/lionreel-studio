import os
from source_utils import probe_video_fast
from clip_ledger import ClipLedger
from watermark_detector import WatermarkDetector
from qa_check import check_cartoon_classifier

l = ClipLedger()
wm = WatermarkDetector()

sources = [
    r"C:\LionReel\cache\cache_-dTa8gchZfc.mp4",
    r"C:\LionReel\cache\cache_hY7m5jjJ9mM.mp4",
    r"C:\LionReel\cache\cache_zCBhhLo6lIM.mp4",
    r"C:\LionReel\cache\cache_SB-qEYVdvXA.mp4",
    r"C:\LionReel\cache\cache_rHIm-jdjqoU.mp4",
    r"C:\LionReel\cache\cache_cMlweIcxyZQ.mp4"
]

for s in sources:
    b = os.path.basename(s)
    if not os.path.exists(s):
        print(f"{b}: NOT FOUND")
        continue
    pr = probe_video_fast(s)
    pass_gate = pr.get("pass_gate")
    is_blocked = l.is_blocked_source(s)
    has_wm, _, _, wm_reason = wm.check_video_corners(s, n_samples=8)
    cart = check_cartoon_classifier(s, n_samples=6)
    print(f"{b}: pass_gate={pass_gate} (res={pr.get('width')}x{pr.get('height')}), blocked={is_blocked}, wm={has_wm} ({wm_reason}), cgi={not cart['passed']}")
