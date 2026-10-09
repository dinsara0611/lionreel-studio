import cv2, numpy as np

vid_path = "C:/LionReel/work/lionreel_cat_acceptance_fix7_1791471016/lionreel_cat_acceptance_fix7_1791471016.mp4"
cap = cv2.VideoCapture(vid_path)
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

start_f = int(30.0 * fps)
end_f = int(32.0 * fps)

cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)
print(f"Checking frames from {start_f} ({30.0}s) to {end_f} ({32.0}s) at {fps} fps:")

for f_idx in range(start_f, end_f + 1):
    ret, frame = cap.read()
    if not ret: break
    sec = f_idx / fps
    mean_val = np.mean(frame)
    if mean_val < 30.0 or (f_idx % 5 == 0):
        print(f"  Frame {f_idx} ({sec:.2f}s): mean_brightness={mean_val:.1f}")

cap.release()
