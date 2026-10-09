import os, sys
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger, compute_phash
import cv2

ledger = ClipLedger()
for f in ["cache_8R_7KCtShkU.mp4", "cache_SB-qEYVdvXA.mp4", "sel_yt_1791105357_2.mp4", "cache_ByH9LuSILxU.mp4"]:
    p = os.path.join("raw", f)
    # Check if blocked
    cap = cv2.VideoCapture(p)
    frames = []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    for i in range(10):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + 0.5) / 10))
        ret, frame = cap.read()
        if ret: frames.append(compute_phash(frame))
    cap.release()
    blocked = ledger.is_blocked_source(p, frames)
    print(f"{f}: is_blocked = {blocked}")
