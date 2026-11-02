import cv2
import numpy as np
import os

sources = [
    r"G:\My Drive\Cat make\raw\cache_zCBhhLo6lIM.mp4",
    r"G:\My Drive\Cat make\raw\cache_cMlweIcxyZQ.mp4",
    r"G:\My Drive\Cat make\raw\cache_825Za_ZishQ.mp4",
    r"G:\My Drive\Cat make\raw\cache_OzAzzpR4JmY.mp4",
    r"G:\My Drive\Cat make\raw\cache_hY7m5jjJ9mM.mp4",
    r"G:\My Drive\Cat make\raw\cache_ByH9LuSILxU.mp4",
    r"G:\My Drive\Cat make\raw\cache_Rr9701_s-Qs.mp4",
]

for s in sources:
    if not os.path.exists(s):
        print("Missing:", s)
        continue
    cap = cv2.VideoCapture(s)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    dur = total_frames / max(1.0, fps)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # Sample 5 frames
    scores = []
    for i in range(5):
        t = dur * (i + 0.5) / 5.0
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ret, frame = cap.read()
        if ret and frame is not None:
            # 540x960 smart crop
            f_h, f_w = frame.shape[:2]
            cw = int(f_h * 9 / 16) if f_w >= f_h else f_w
            cx = max(0, (f_w - cw) // 2)
            crop = frame[:, cx:cx+cw]
            std = cv2.resize(crop, (540, 960))
            gray = cv2.cvtColor(std, cv2.COLOR_BGR2GRAY)
            scores.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
    cap.release()
    med = np.median(scores) if scores else 0.0
    print(f"{os.path.basename(s):25s} | {w}x{h} ({dur:5.1f}s) | 540x960 Median Sharpness: {med:6.1f} | >=150: {med >= 150.0}")
