import cv2
import numpy as np

s = r"G:\My Drive\Cat make\raw\cache_ByH9LuSILxU.mp4"
cap = cv2.VideoCapture(s)
cap.set(cv2.CAP_PROP_POS_MSEC, 190.0 * 1000.0)
ret, frame = cap.read()
if ret:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    print("Full frame 1920x1080 laplacian variance:", cv2.Laplacian(gray, cv2.CV_64F).var())
    
    # What about a region of interest around the pet?
    # What about unsharp mask?
    # What about without any resizing?
cap.release()
