import os
import glob
import cv2
import numpy as np

raw_dir = r"G:\My Drive\Cat make\raw"
files = glob.glob(os.path.join(raw_dir, "*.mp4"))

for f in files:
    try:
        cap = cv2.VideoCapture(f)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            continue
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        dur = total_frames / fps
        scores = []
        for i in range(5):
            t = dur * (i + 0.5) / 5.0
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ret, frame = cap.read()
            if ret and frame is not None:
                h, w = frame.shape[:2]
                cw = int(h * 9 / 16) if w >= h else w
                cx = max(0, (w - cw) // 2)
                crop = frame[:, cx:cx+cw]
                std = cv2.resize(crop, (540, 960))
                gray = cv2.cvtColor(std, cv2.COLOR_BGR2GRAY)
                scores.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
        cap.release()
        if scores:
            med = np.median(scores)
            mx = np.max(scores)
            print(f"{os.path.basename(f):35s} | Med: {med:6.1f} | Max: {mx:6.1f}")
    except Exception as e:
        pass
