import os
import glob
import cv2
import numpy as np

raw_dir = r"G:\My Drive\Cat make\raw"
files = glob.glob(os.path.join(raw_dir, "*.mp4"))

print(f"Found {len(files)} video files in raw/")
for f in files:
    cap = cv2.VideoCapture(f)
    if not cap.isOpened():
        continue
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    dur = total_frames / max(1.0, fps)
    
    scores_540 = []
    scores_orig = []
    for i in range(10):
        t_s = dur * (i + 0.5) / 10.0
        cap.set(cv2.CAP_PROP_POS_MSEC, t_s * 1000.0)
        ret, frame = cap.read()
        if ret and frame is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            scores_orig.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
            
            # 540x960
            r540 = cv2.resize(frame, (540, 960))
            gray540 = cv2.cvtColor(r540, cv2.COLOR_BGR2GRAY)
            scores_540.append(float(cv2.Laplacian(gray540, cv2.CV_64F).var()))
    cap.release()
    
    med_orig = np.median(scores_orig) if scores_orig else 0.0
    med_540 = np.median(scores_540) if scores_540 else 0.0
    print(f"{os.path.basename(f):35s} | {w}x{h:4d} ({dur:5.1f}s) | Orig Lap: {med_orig:6.1f} | 540x960 Lap: {med_540:6.1f}")
