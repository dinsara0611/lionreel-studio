import cv2
import numpy as np

src_path = r"G:\My Drive\Cat make\raw\cache_ByH9LuSILxU.mp4"
cap = cv2.VideoCapture(src_path)
print("Opened:", cap.isOpened(), "Total frames:", cap.get(cv2.CAP_PROP_FRAME_COUNT), "W:", cap.get(cv2.CAP_PROP_FRAME_WIDTH), "H:", cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

for t_s in [96.0, 98.0, 100.0, 185.0, 188.0, 300.0]:
    cap.set(cv2.CAP_PROP_POS_MSEC, t_s * 1000.0)
    ret, frame = cap.read()
    if ret:
        h, w = frame.shape[:2]
        lap_raw = cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        # center 9:16 crop
        cw = int(h * 9 / 16)
        cx = (w - cw) // 2
        crop = frame[:, cx:cx+cw]
        crop_540 = cv2.resize(crop, (540, 960))
        gray_540 = cv2.cvtColor(crop_540, cv2.COLOR_BGR2GRAY)
        lap_crop = cv2.Laplacian(gray_540, cv2.CV_64F).var()

        # let's also check qa_check score formula:
        h_g, w_g = gray_540.shape
        w_sub = int(w_g * 0.70)
        x_sub = int((w_g - w_sub) / 2)
        score_full = float(cv2.Laplacian(gray_540, cv2.CV_64F).var())
        score_fg = float(cv2.Laplacian(gray_540[:, x_sub:x_sub+w_sub], cv2.CV_64F).var())
        score_center = float(cv2.Laplacian(gray_540[int(h_g*0.32):int(h_g*0.68), int(w_g*0.15):int(w_g*0.85)], cv2.CV_64F).var())
        sh_score = max(score_full, score_fg, score_center)

        print(f"t={t_s:5.1f}s: raw_lap={lap_raw:6.1f}, crop_540_lap={lap_crop:5.1f}, max_sub={sh_score:5.1f}")
cap.release()
