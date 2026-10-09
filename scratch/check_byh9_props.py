import cv2

cap = cv2.VideoCapture("raw/cache_ByH9LuSILxU.mp4")
fps = cap.get(cv2.CAP_PROP_FPS)
frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
dur = frames / fps if fps > 0 else 0
cap.release()
print(f"cache_ByH9LuSILxU.mp4: {w}x{h}, {fps:.2f} fps, {frames} frames, {dur:.1f}s ({dur/60:.1f} min)")
