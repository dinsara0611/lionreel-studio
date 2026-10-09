import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import time
import math
import subprocess
import numpy as np
import cv2
import imageio_ffmpeg
from pet_detector import PetDetector

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

def decode_frames_ffmpeg_pipe(video_path, start_s, dur_s, n_frames=8, target_w=320, target_h=180):
    """
    Decodes n_frames evenly spaced across [start_s, start_s + dur_s]
    using an FFmpeg pipe stream into raw BGR24 frames at target resolution.
    Avoids cv2.VideoCapture random seeks and network I/O deadlocks.
    """
    sample_fps = max(0.5, float(n_frames) / max(0.1, float(dur_s)))
    cmd = [
        FFMPEG_EXE,
        "-threads", "2",
        "-ss", f"{max(0.0, start_s):.3f}",
        "-i", video_path,
        "-t", f"{dur_s:.3f}",
        "-vf", f"fps={sample_fps:.3f},scale={target_w}:{target_h}",
        "-an",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-v", "error",
        "-"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frames = []
    frame_bytes = target_w * target_h * 3
    while True:
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        arr = np.frombuffer(buf, dtype=np.uint8).reshape((target_h, target_w, 3))
        frames.append(arr)
    proc.stdout.close()
    proc.wait()
    return frames

def test_candidate(video_path, start_s, dur_s, layout_mode="smart_crop"):
    t0 = time.time()
    detector = PetDetector()
    
    # 1. Probe header
    cap = cv2.VideoCapture(video_path)
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()

    # 2. Decode frames via pipe at 320x180
    target_w, target_h = 320, 180
    n_samples = 8
    frames = decode_frames_ffmpeg_pipe(video_path, start_s, dur_s, n_frames=n_samples, target_w=target_w, target_h=target_h)
    t_decode = time.time()

    if not frames:
        return {"error": "NO_FRAMES_DECODED"}

    # 3. Detect pets and compute sharpness
    scale_x = orig_w / float(target_w)
    scale_y = orig_h / float(target_h)

    detections_per_frame = []
    sample_sharpness = []

    for frame in frames:
        # Sharpness: center slice
        hf, wf = frame.shape[:2]
        cwf = int(hf * 9 / 16) if layout_mode != "blur_fit" else int(wf * 0.60)
        cxf = (wf - cwf) // 2
        crop_sample = frame[:, cxf:cxf+cwf]
        gs = cv2.cvtColor(crop_sample, cv2.COLOR_BGR2GRAY)
        sample_sharpness.append(float(cv2.Laplacian(gs, cv2.CV_64F).var()))

        # Detect
        dets = detector.detect(frame, conf_threshold=0.20)
        filtered = []
        for d in dets:
            if d["class_name"] in ("cat", "dog"):
                # Scale boxes back to orig resolution
                bx1, by1, bx2, by2 = d["box"]
                scaled_d = dict(d)
                scaled_d["box"] = [bx1 * scale_x, by1 * scale_y, bx2 * scale_x, by2 * scale_y]
                scaled_d["center"] = (d["center"][0] * scale_x, d["center"][1] * scale_y)
                filtered.append(scaled_d)
        detections_per_frame.append(filtered)
    
    t_detect = time.time()
    med_sharp = float(np.median(sample_sharpness)) if sample_sharpness else 0.0

    # Presence
    frames_with_pets = sum(1 for d in detections_per_frame if len(d) > 0)
    presence_ratio = frames_with_pets / max(1, len(frames))

    # Evaluate Framing
    vis_ok, horiz_ok, vert_ok, size_ok, all_ok = 0, 0, 0, 0, 0
    total_eval = 0

    if layout_mode == "blur_fit":
        # Blur-fit framing logic
        S = 1080.0 / orig_w
        Y_offset = (1920.0 - orig_h * S) / 2.0
        for dets in detections_per_frame:
            if not dets:
                continue
            total_eval += 1
            primary = max(dets, key=lambda d: d["area_frac"] * 2.0 + d["conf"])
            bx1, by1, bx2, by2 = primary["box"]
            cx_out = ((bx1 + bx2) / 2.0) / float(orig_w)
            cy_out = (Y_offset + ((by1 + by2) / 2.0) * S) / 1920.0
            pet_h_out = ((by2 - by1) * S) / 1920.0

            is_vis = True
            is_h = (0.35 <= cx_out <= 0.65)
            is_v = (0.28 <= cy_out <= 0.72)
            is_s = (pet_h_out >= 0.20)
            if is_vis: vis_ok += 1
            if is_h: horiz_ok += 1
            if is_v: vert_ok += 1
            if is_s: size_ok += 1
            if is_vis and is_h and is_v and is_s:
                all_ok += 1
    else:
        # Smart crop framing logic
        crop_h = orig_h
        crop_w = int(round(orig_h * 9.0 / 16.0))
        if crop_w % 2 != 0: crop_w += 1
        crop_w = min(crop_w, orig_w)
        max_x = orig_w - crop_w
        max_y = orig_h - crop_h

        # Compute simple center tracking
        target_centers_x = []
        for dets in detections_per_frame:
            if dets:
                primary = max(dets, key=lambda d: d["area_frac"] * 2.0 + d["conf"])
                target_centers_x.append((primary["box"][0] + primary["box"][2]) / 2.0)
            else:
                target_centers_x.append(orig_w / 2.0)
        
        # Camera trajectory
        cam_xs = [max(0.0, min(float(max_x), cx - (crop_w / 2.0))) for cx in target_centers_x]
        
        for i, dets in enumerate(detections_per_frame):
            if not dets:
                continue
            total_eval += 1
            primary = max(dets, key=lambda d: d["area_frac"] * 2.0 + d["conf"])
            bx1, by1, bx2, by2 = primary["box"]
            cam_x = cam_xs[i]
            cbx1 = bx1 - cam_x
            cbx2 = bx2 - cam_x
            cby1 = by1
            cby2 = by2

            is_vis = (cbx1 >= -3 and cby1 >= -3 and cbx2 <= crop_w + 3 and cby2 <= crop_h + 3)
            cx = ((cbx1 + cbx2) / 2.0) / float(crop_w)
            cy = ((cby1 + cby2) / 2.0) / float(crop_h)
            h_frac = (cby2 - cby1) / float(crop_h)

            is_h = (0.38 <= cx <= 0.62)
            is_v = (0.30 <= cy <= 0.62) if max_y > 0 else ((0.20 <= cy <= 0.75) and (cby1 >= -3 and cby2 <= crop_h + 3))
            is_s = (0.28 <= h_frac <= 0.72)

            if is_vis: vis_ok += 1
            if is_h: horiz_ok += 1
            if is_v: vert_ok += 1
            if is_s: size_ok += 1
            if is_vis and is_h and is_v and is_s:
                all_ok += 1

    eval_count = max(total_eval, 1)
    pred_compliance = all_ok / eval_count
    pred_vis = vis_ok / eval_count
    pred_h = horiz_ok / eval_count
    pred_v = vert_ok / eval_count
    pred_s = size_ok / eval_count

    passed = bool(
        (pred_compliance >= 0.88 or (pred_vis >= 0.88 and pred_h >= 0.88 and pred_v >= 0.88 and pred_s >= 0.88))
        and (presence_ratio >= 0.35) and (med_sharp >= 15.0)
    )

    t_end = time.time()
    return {
        "passed": passed,
        "score": round(pred_compliance, 3),
        "sharpness": round(med_sharp, 1),
        "presence": round(presence_ratio, 3),
        "vis": round(pred_vis, 3),
        "horiz": round(pred_h, 3),
        "vert": round(pred_v, 3),
        "size": round(pred_s, 3),
        "frames_decoded": len(frames),
        "total_eval": total_eval,
        "t_decode": round(t_decode - t0, 2),
        "t_detect": round(t_detect - t_decode, 2),
        "t_total": round(t_end - t0, 2)
    }

if __name__ == "__main__":
    src = r"C:\LionReel\cache\cache_ByH9LuSILxU.mp4"
    print("Testing candidate at start 50.0s, dur 10.0s in SMART CROP:")
    res_sc = test_candidate(src, 50.0, 10.0, layout_mode="smart_crop")
    print(res_sc)

    print("\nTesting candidate at start 50.0s, dur 10.0s in BLUR FIT:")
    res_bf = test_candidate(src, 50.0, 10.0, layout_mode="blur_fit")
    print(res_bf)
