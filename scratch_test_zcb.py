import cv2
import numpy as np

s = r"G:\My Drive\Cat make\raw\cache_zCBhhLo6lIM.mp4"
cap = cv2.VideoCapture(s)
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

for t_s in [250.0, 290.0, 375.0, 380.0]:
    cap.set(cv2.CAP_PROP_POS_MSEC, t_s * 1000.0)
    ret, frame = cap.read()
    if ret:
        resized_540 = cv2.resize(frame, (540, 960))
        gray_540 = cv2.cvtColor(resized_540, cv2.COLOR_BGR2GRAY)
        h_g, w_g = gray_540.shape
        w_sub = int(w_g * 0.70)
        x_sub = int((w_g - w_sub) / 2)
        score_full = float(cv2.Laplacian(gray_540, cv2.CV_64F).var())
        score_fg = float(cv2.Laplacian(gray_540[:, x_sub:x_sub+w_sub], cv2.CV_64F).var())
        score_center = float(cv2.Laplacian(gray_540[int(h_g*0.32):int(h_g*0.68), int(w_g*0.15):int(w_g*0.85)], cv2.CV_64F).var())
        sh_score = max(score_full, score_fg, score_center)
        print(f"t={t_s}s: full={score_full:.1f}, fg={score_fg:.1f}, center={score_center:.1f}, max={sh_score:.1f}")
cap.release()
