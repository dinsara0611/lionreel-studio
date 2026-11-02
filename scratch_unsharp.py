import cv2
import numpy as np

s = r"G:\My Drive\Cat make\raw\cache_ByH9LuSILxU.mp4"
cap = cv2.VideoCapture(s)
cap.set(cv2.CAP_PROP_POS_MSEC, 190.0 * 1000.0)
ret, frame = cap.read()
if ret:
    h, w = frame.shape[:2]
    cw = int(h * 9 / 16)
    cx = (w - cw) // 2
    crop = frame[:, cx:cx+cw]
    
    # 1. raw 540x960
    s1 = cv2.resize(crop, (540, 960))
    g1 = cv2.cvtColor(s1, cv2.COLOR_BGR2GRAY)
    print("Raw crop 540x960:", cv2.Laplacian(g1, cv2.CV_64F).var())
    
    # 2. unsharp with GaussianBlur
    gaussian = cv2.GaussianBlur(g1, (0, 0), 2.0)
    unsharp = cv2.addWeighted(g1, 2.5, gaussian, -1.5, 0)
    print("Unsharp 2.5:", cv2.Laplacian(unsharp, cv2.CV_64F).var())
    
    gaussian2 = cv2.GaussianBlur(g1, (0, 0), 2.0)
    unsharp2 = cv2.addWeighted(g1, 3.5, gaussian2, -2.5, 0)
    print("Unsharp 3.5:", cv2.Laplacian(unsharp2, cv2.CV_64F).var())
cap.release()
