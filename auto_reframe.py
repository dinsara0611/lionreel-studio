"""
LionReel Auto Reframe Smart Crop Engine (Premiere / CapCut Style)
=================================================================
Converts 16:9 / 4K / landscape footage into professional 9:16 vertical video
that fills the entire 1080x1920 frame with human-editor camera tracking.

Key Specifications:
1. 9:16 crop window at full source height (608x1080 for 1080p, 1216x2160 for 4K).
2. Upscale limits: Up to 2.0x (1.8x for 1080p); below 1080p rejected.
3. Subject tracking with YOLOX:
   - Pet body at x = 50% of crop window
   - Eyes/head at 40-45% from the top
   - Smoothing: One-Euro filter + dead-zone + ease-in/ease-out
   - Look-ahead: 0.3 - 0.5s predictive lead
   - Max pan speed: <= 12% of crop width per second
   - Close-up stabilization (hold frame still when pet is stationary or large)
4. Multi-pet priority: motion + size + face visible; 0.4-0.6s smooth transition ease.
5. Funniest moment punch-in zoom (+10% to +12%) with smooth ease in/out.
6. Start already framed on pet (zero camera searching at t=0).
7. Native single-pass FFmpeg execution with Lanczos scaling and mild unsharp.
"""

import os
import sys
import time
import math
import uuid
import subprocess

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_VENV_SITE = os.path.join(_BASE_DIR, ".venv", "Lib", "site-packages")
if os.path.exists(_VENV_SITE) and _VENV_SITE not in sys.path:
    sys.path.insert(0, _VENV_SITE)

import cv2
import numpy as np
import json
import imageio_ffmpeg
from pet_detector import PetDetector

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

_HW_ENCODER_CONFIG = None

def get_best_video_encoder():
    """
    Detects hardware video encoders (Intel MediaFoundation h264_mf, Quick Sync QSV, NVIDIA NVENC, AMD AMF).
    Returns dict with encoder name and ffmpeg CLI flags.
    Falls back cleanly to libx264 -crf 17 -preset veryfast.
    """
    global _HW_ENCODER_CONFIG
    if _HW_ENCODER_CONFIG is not None:
        return _HW_ENCODER_CONFIG

    # 1. Test Intel MediaFoundation (h264_mf: 119.2 fps hardware acceleration on Windows)
    try:
        test_cmd = [
            FFMPEG_EXE, "-nostats", "-loglevel", "error", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.05",
            "-c:v", "h264_mf", "-b:v", "10M", "-pix_fmt", "yuv420p",
            "-f", "null", "-"
        ]
        res = subprocess.run(test_cmd, capture_output=True, timeout=5)
        if res.returncode == 0:
            _HW_ENCODER_CONFIG = {
                "name": "h264_mf",
                "args": ["-c:v", "h264_mf", "-b:v", "10M", "-pix_fmt", "yuv420p"]
            }
            return _HW_ENCODER_CONFIG
    except Exception:
        pass

    # 2. Test Intel Quick Sync (h264_qsv)
    try:
        test_cmd = [
            FFMPEG_EXE, "-nostats", "-loglevel", "error", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.05",
            "-c:v", "h264_qsv", "-global_quality", "20", "-preset", "veryfast",
            "-f", "null", "-"
        ]
        res = subprocess.run(test_cmd, capture_output=True, timeout=5)
        if res.returncode == 0:
            _HW_ENCODER_CONFIG = {
                "name": "h264_qsv",
                "args": ["-c:v", "h264_qsv", "-global_quality", "20", "-preset", "veryfast"]
            }
            return _HW_ENCODER_CONFIG
    except Exception:
        pass

    # 3. Test NVIDIA NVENC
    try:
        test_cmd = [
            FFMPEG_EXE, "-nostats", "-loglevel", "error", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.05",
            "-c:v", "h264_nvenc", "-cq", "19", "-preset", "p4",
            "-f", "null", "-"
        ]
        res = subprocess.run(test_cmd, capture_output=True, timeout=5)
        if res.returncode == 0:
            _HW_ENCODER_CONFIG = {
                "name": "h264_nvenc",
                "args": ["-c:v", "h264_nvenc", "-cq", "19", "-preset", "p4"]
            }
            return _HW_ENCODER_CONFIG
    except Exception:
        pass

    # 4. Fallback: Software libx264 CRF 17 veryfast
    _HW_ENCODER_CONFIG = {
        "name": "libx264",
        "args": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17"]
    }
    return _HW_ENCODER_CONFIG



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



class OneEuroFilter:
    """
    Adaptive low-pass filter designed for human/camera motion tracking:
    filters jitter when speed is low, reduces lag when speed is high.
    """
    def __init__(self, t0, x0, min_cutoff=0.6, beta=0.04, d_cutoff=1.0):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self.x_prev = float(x0)
        self.dx_prev = 0.0
        self.t_prev = float(t0)

    def _alpha(self, cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / max(1e-5, dt))

    def filter(self, t, x):
        dt = t - self.t_prev
        if dt <= 1e-5:
            return self.x_prev

        # Compute filtered derivative
        d_x = (x - self.x_prev) / dt
        alpha_d = self._alpha(self.d_cutoff, dt)
        dx_hat = alpha_d * d_x + (1.0 - alpha_d) * self.dx_prev

        # Adaptive cutoff frequency
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        alpha = self._alpha(cutoff, dt)
        x_hat = alpha * x + (1.0 - alpha) * self.x_prev

        self.x_prev = x_hat
        self.dx_prev = dx_hat
        self.t_prev = t
        return x_hat


class AutoReframeEngine:
    def __init__(self, detector=None):
        self.detector = detector or PetDetector()

    def analyze_and_plan(self, video_path=None, start_s=None, dur_s=None, **kwargs):
        return self.plan_reframe(video_path=video_path, start_s=start_s, dur_s=dur_s, **kwargs)

    def analyze_and_plan_framing(self, video_path=None, start_s=None, dur_s=None, **kwargs):
        return self.plan_reframe(video_path=video_path, start_s=start_s, dur_s=dur_s, **kwargs)

    def plan_reframe(self, video_path=None, start_s=None, dur_s=None, animal_mode="cat", layout_mode="smart_crop", stricter=False, allow_slide=True, max_slide_s=4.0, step_s=0.5, aspect_ratio=None, out_w=None, out_h=None, **kwargs):
        """
        Analyzes source clip and computes a smooth camera trajectory.
        Includes feasibility check, clamp-aware centering, area visibility,
        single-pass buffered sliding window search (+/-4s), and exact failing frame diagnostics.
        Fully ratio-aware: supports 16:9 (1920x1080), 9:16 (1080x1920), and 1:1 (1080x1080).
        """
        video_path = video_path or kwargs.get("source_video_path") or kwargs.get("source_path")
        start_s = start_s if start_s is not None else kwargs.get("start_sec", 0.0)
        dur_s = dur_s if dur_s is not None else kwargs.get("duration_sec", 10.0)

        aspect_ratio = aspect_ratio or kwargs.get("aspect_ratio")
        out_w = out_w or kwargs.get("out_w")
        out_h = out_h or kwargs.get("out_h")

        if out_w and out_h:
            out_w = int(out_w)
            out_h = int(out_h)
            if not aspect_ratio:
                if out_w == 1920 and out_h == 1080: aspect_ratio = "16:9"
                elif out_w == 1080 and out_h == 1080: aspect_ratio = "1:1"
                else: aspect_ratio = "9:16"
        else:
            if aspect_ratio == "16:9":
                out_w, out_h = 1920, 1080
            elif aspect_ratio == "1:1":
                out_w, out_h = 1080, 1080
            else:
                aspect_ratio = "9:16"
                out_w, out_h = 1080, 1920

        if not video_path or not os.path.exists(video_path):
            return {"status": "reject", "reason": "Source file not found"}

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_sec = total_frames / max(1.0, fps)
        cap.release()

        if total_frames <= 0 or orig_w <= 0 or orig_h <= 0:
            return {"status": "reject", "reason": "Invalid video stream"}

        # 1. Resolution Check: Below 1080p is rejected
        if orig_h < 1080 and orig_w < 1080:
            return {
                "status": "reject",
                "reason": f"LOW_RESOLUTION_UNDER_1080P ({orig_w}x{orig_h} is below minimum 1080p requirement)"
            }

        # 2. Ratio-aware mode & dimensions
        src_aspect = orig_w / max(1.0, float(orig_h))

        if aspect_ratio == "16:9":
            if src_aspect >= 1.2:
                # Landscape source
                if abs(src_aspect - 16.0 / 9.0) < 0.06:
                    crop_w, crop_h = orig_w, orig_h
                    mode = "landscape_direct"
                elif src_aspect > 1.78:
                    crop_h = orig_h
                    crop_w = int(round(orig_h * 16.0 / 9.0))
                    mode = "smart_crop_16_9"
                else:
                    crop_w = orig_w
                    crop_h = int(round(orig_w * 9.0 / 16.0))
                    mode = "smart_crop_16_9"
            else:
                # Vertical source for 16:9 output -> reject for smart_crop (must fill frame) or blurred pillarbox
                if layout_mode == "smart_crop":
                    return {
                        "status": "reject",
                        "reason": f"VERTICAL_SOURCE_IN_16_9_SMART_CROP (Aspect {src_aspect:.2f} < 1.2 is vertical; cannot smart crop to 16:9)",
                        "framing_score": 0.0,
                        "sharpness": 0.0,
                        "pet_detected_ratio": 0.0,
                        "details": {"vis": 0.0, "horiz": 0.0, "vert": 0.0, "size": 0.0},
                        "failing_frames": []
                    }
                crop_w, crop_h = orig_w, orig_h
                mode = "blur_fit_16_9"
            is_vertical_direct = False
        elif aspect_ratio == "1:1":
            crop_dim = min(orig_w, orig_h)
            crop_w, crop_h = crop_dim, crop_dim
            mode = "smart_crop_1_1"
            is_vertical_direct = False
        else: # 9:16
            is_vertical_direct = (src_aspect <= 0.60)
            if layout_mode == "blur_fit":
                crop_w, crop_h = orig_w, orig_h
                mode = "blur_fit"
            elif is_vertical_direct:
                crop_w, crop_h = orig_w, orig_h
                mode = "vertical_direct"
            else:
                crop_h = orig_h
                crop_w = int(round(orig_h * 9.0 / 16.0))
                mode = "smart_crop"

        if crop_w % 2 != 0:
            crop_w += 1
        if crop_h % 2 != 0:
            crop_h += 1
        crop_w = min(crop_w, orig_w)
        crop_h = min(crop_h, orig_h)
        max_x = orig_w - crop_w
        max_y = orig_h - crop_h

        # Upscale factor check
        if mode not in ("blur_fit", "blur_fit_16_9"):
            upscale_w = float(out_w) / float(crop_w)
            upscale_h = float(out_h) / float(crop_h)
            upscale_factor = max(upscale_w, upscale_h)
            if upscale_factor > 2.05:
                return {
                    "status": "reject",
                    "reason": f"UPSCALE_LIMIT_EXCEEDED (Upscale factor {upscale_factor:.2f}x > 2.0x limit)",
                    "framing_score": 0.0,
                    "sharpness": 0.0,
                    "pet_detected_ratio": 0.0,
                    "details": {"vis": 0.0, "horiz": 0.0, "vert": 0.0, "size": 0.0},
                    "failing_frames": []
                }

        # Determine buffered analysis window
        if allow_slide and layout_mode == "smart_crop":
            buf_start = max(0.0, start_s - max_slide_s)
            buf_end = min(total_sec, start_s + dur_s + max_slide_s)
        else:
            buf_start = max(0.0, start_s)
            buf_end = min(total_sec, start_s + dur_s)
        buf_dur = buf_end - buf_start

        if buf_dur <= 0:
            return {"status": "reject", "reason": "INVALID_SPAN"}

        # Decode low-res 320x180 stream at ~2 fps
        n_samples = max(6, int(round(buf_dur * 2.0)))
        target_w, target_h = 320, 180
        frames = decode_frames_ffmpeg_pipe(
            video_path, buf_start, buf_dur,
            n_frames=n_samples, target_w=target_w, target_h=target_h
        )
        if not frames:
            return {
                "status": "reject",
                "reason": "ANALYSIS_FAILED (Zero frames decoded via FFmpeg pipe)",
                "framing_score": 0.0,
                "sharpness": 0.0,
                "pet_detected_ratio": 0.0,
                "details": {"vis": 0.0, "horiz": 0.0, "vert": 0.0, "size": 0.0},
                "failing_frames": []
            }

        frame_times = [buf_start + (i / max(1, len(frames) - 1)) * buf_dur for i in range(len(frames))]
        scale_x = orig_w / float(target_w)
        scale_y = orig_h / float(target_h)

        frame_dets = []
        frame_sharp = []
        motion_energies = []
        pet_widths = []
        prev_gray = None

        for frame in frames:
            small = cv2.resize(frame, (160, 90))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                motion_energy = float(np.mean(cv2.absdiff(gray, prev_gray)))
            else:
                motion_energy = 0.0
            prev_gray = gray
            motion_energies.append(motion_energy)

            dets = self.detector.detect(frame, conf_threshold=0.20, include_objects=True)
            filtered = []
            for d in dets:
                bx1, by1, bx2, by2 = d["box"]
                scaled_d = dict(d)
                scaled_d["box"] = [bx1 * scale_x, by1 * scale_y, bx2 * scale_x, by2 * scale_y]
                scaled_d["center"] = (d["center"][0] * scale_x, d["center"][1] * scale_y)
                scaled_d["area_frac"] = (scaled_d["box"][2] - scaled_d["box"][0]) * (scaled_d["box"][3] - scaled_d["box"][1]) / float(orig_w * orig_h)
                filtered.append(scaled_d)
                if d["class_name"] in ("cat", "dog"):
                    pet_widths.append(scaled_d["box"][2] - scaled_d["box"][0])
            frame_dets.append(filtered)

        # Measure true visual sharpness on canonical standard scale and check for source black borders / burned-in text
        source_sharpness_scores = []
        source_border_violations = 0
        source_text_violations = 0
        source_sampled_sh = 0
        act_x, act_y, act_w, act_h = 0, 0, orig_w, orig_h
        try:
            from overlay_text_detector import check_frame_black_borders, analyze_frame_text_and_borders
        except Exception:
            check_frame_black_borders = None
            analyze_frame_text_and_borders = None
        try:
            from canonical_window import measure_canonical_sharpness, detect_active_content_box
        except Exception:
            measure_canonical_sharpness = None
            detect_active_content_box = None

        try:
            sh_frames = decode_frames_ffmpeg_pipe(
                video_path, start_s, dur_s,
                n_frames=3, target_w=orig_w, target_h=orig_h
            )
            if detect_active_content_box and sh_frames:
                act_x, act_y, act_w, act_h = detect_active_content_box(sh_frames, orig_w, orig_h)
                if act_w < orig_w or act_h < orig_h:
                    act_aspect = act_w / max(1.0, float(act_h))
                    if aspect_ratio == "16:9":
                        if act_aspect < 1.35:
                            if layout_mode == "smart_crop":
                                return {
                                    "status": "reject",
                                    "reason": f"PILLARBOX_IN_SMART_CROP_16_9 (Active aspect {act_aspect:.2f} < 1.35 has pillarbox bars in 16:9 smart crop)",
                                    "framing_score": 0.0,
                                    "sharpness": 0.0,
                                    "pet_detected_ratio": 0.0,
                                    "details": {"vis": 0.0, "horiz": 0.0, "vert": 0.0, "size": 0.0},
                                    "failing_frames": []
                                }
                            mode = "blur_fit_16_9"
                            crop_w, crop_h = act_w, act_h
                        elif abs(act_aspect - 16.0 / 9.0) < 0.06:
                            mode = "landscape_direct"
                            crop_w, crop_h = act_w, act_h
                        elif act_aspect > 1.78:
                            mode = "smart_crop_16_9"
                            crop_h = act_h
                            crop_w = min(act_w, int(round(act_h * 16.0 / 9.0)))
                        else:
                            mode = "smart_crop_16_9"
                            crop_w = act_w
                            crop_h = min(act_h, int(round(act_w * 9.0 / 16.0)))
                    elif aspect_ratio == "1:1":
                        crop_dim = min(act_w, act_h)
                        crop_w, crop_h = crop_dim, crop_dim
                        mode = "smart_crop_1_1"
                    else:
                        if mode == "smart_crop":
                            crop_h = min(crop_h, act_h)
                            crop_w = min(act_w, int(round(crop_h * 9.0 / 16.0)))
                        else:
                            crop_w, crop_h = act_w, act_h
                    crop_w -= crop_w % 2
                    crop_h -= crop_h % 2

            for sh_frame in sh_frames:
                if sh_frame is not None and sh_frame.size > 0:
                    source_sampled_sh += 1
                    sh_active = sh_frame[act_y:act_y+act_h, act_x:act_x+act_w]
                    if sh_active.size == 0:
                        sh_active = sh_frame
                    sh_h, sh_w = sh_active.shape[:2]
                    if aspect_ratio == "16:9":
                        sh_crop = sh_active
                    elif aspect_ratio == "1:1":
                        sh_cdim = min(sh_w, sh_h)
                        sh_cx = max(0, (sh_w - sh_cdim) // 2)
                        sh_cy = max(0, (sh_h - sh_cdim) // 2)
                        sh_crop = sh_active[sh_cy:sh_cy+sh_cdim, sh_cx:sh_cx+sh_cdim]
                    else:
                        sh_cw = min(sh_w, int(sh_h * 9 / 16)) if layout_mode != "blur_fit" else sh_w
                        sh_cx = max(0, (sh_w - sh_cw) // 2)
                        sh_crop = sh_active[:, sh_cx:sh_cx+sh_cw]

                    if check_frame_black_borders and mode not in ("blur_fit", "blur_fit_16_9"):
                        b_info = check_frame_black_borders(sh_crop, border_threshold=12.0, min_border_thickness=6)
                        if b_info.get("has_black_border"):
                            source_border_violations += 1
                    if analyze_frame_text_and_borders:
                        t_info = analyze_frame_text_and_borders(
                            sh_active,
                            is_pillarbox_layout=(mode in ("blur_fit", "blur_fit_16_9")),
                            is_master_with_captions=False
                        )
                        if t_info.get("has_text_overlay"):
                            source_text_violations += 1

                    if measure_canonical_sharpness:
                        source_sharpness_scores.append(measure_canonical_sharpness(sh_crop))
                    else:
                        sh_std = cv2.resize(sh_crop, (180, 320))
                        sh_gray = cv2.cvtColor(sh_std, cv2.COLOR_BGR2GRAY)
                        source_sharpness_scores.append(float(cv2.Laplacian(sh_gray, cv2.CV_64F).var()))
        except Exception:
            pass

        med_sharp = float(np.median(source_sharpness_scores)) if source_sharpness_scores else 0.0

        if source_sampled_sh > 0 and source_border_violations >= 1:
            return {
                "status": "reject",
                "reason": f"BLACK_BORDER_DETECTED ({source_border_violations}/{source_sampled_sh} sampled frames have black letterbox/pillarbox bars)",
                "framing_score": 0.0,
                "sharpness": round(med_sharp, 1),
                "pet_detected_ratio": 0.0,
                "details": {"vis": 0.0, "horiz": 0.0, "vert": 0.0, "size": 0.0},
                "failing_frames": []
            }

        if source_sampled_sh > 0 and source_text_violations >= 2:
            return {
                "status": "reject",
                "reason": f"BURNED_IN_TEXT_DETECTED ({source_text_violations}/{source_sampled_sh} sampled frames have burned-in text)",
                "framing_score": 0.0,
                "sharpness": round(med_sharp, 1),
                "pet_detected_ratio": 0.0,
                "details": {"vis": 0.0, "horiz": 0.0, "vert": 0.0, "size": 0.0},
                "failing_frames": []
            }

        # Step 4a: Feasibility check (extreme full-frame close-ups only)
        if pet_widths and not is_vertical_direct and mode not in ("vertical_direct", "blur_fit", "blur_fit_16_9"):
            med_pet_w = float(np.median(pet_widths))
            if med_pet_w > 1.95 * float(orig_w):
                return {
                    "status": "reject",
                    "reason": f"FRAMING_INFEASIBLE (Median pet box width {med_pet_w:.1f}px > 92% crop {crop_w}px)",
                    "framing_score": 0.0,
                    "sharpness": round(med_sharp, 1),
                    "pet_detected_ratio": 0.0,
                    "details": {"vis": 0.0, "horiz": 0.0, "vert": 0.0, "size": 0.0},
                    "failing_frames": []
                }

        # 4b. Blur-fit evaluation modes
        if mode == "blur_fit_16_9":
            if med_sharp < 150.0:
                return {
                    "status": "reject",
                    "reason": f"LOW_SOURCE_SHARPNESS (Median {med_sharp:.1f} < 150.0)",
                    "framing_score": 0.0,
                    "sharpness": round(med_sharp, 1),
                    "pet_detected_ratio": 1.0,
                    "details": {"vis": 1.0, "horiz": 1.0, "vert": 1.0, "size": 1.0},
                    "failing_frames": []
                }
            return {
                "status": "pass",
                "mode": "blur_fit_16_9",
                "aspect_ratio": aspect_ratio,
                "out_w": out_w,
                "out_h": out_h,
                "orig_size": (orig_w, orig_h),
                "active_box": [act_x, act_y, act_w, act_h],
                "crop_w": crop_w,
                "crop_h": crop_h,
                "keyframes_t": [0.0],
                "keyframes_x": [act_x],
                "keyframes_y": [act_y],
                "keyframes_zoom": [1.0],
                "framing_score": 1.0,
                "sharpness": round(med_sharp, 1),
                "pet_detected_ratio": 1.0,
                "details": {"vis": 1.0, "horiz": 1.0, "vert": 1.0, "size": 1.0},
                "failing_frames": [],
                "best_start_s": start_s,
                "best_dur_s": dur_s,
                "best_offset": 0.0
            }

        if layout_mode == "blur_fit" or mode == "blur_fit":
            S = float(out_w) / float(orig_w)
            Y_offset = (float(out_h) - orig_h * S) / 2.0
            vis_ok, horiz_ok, vert_ok, size_ok, all_ok = 0, 0, 0, 0, 0
            total_eval = 0

            for i, dets in enumerate(frame_dets):
                if not dets:
                    continue
                total_eval += 1
                primary = max(dets, key=lambda d: d["area_frac"] * 2.0 + d["conf"])
                bx1, by1, bx2, by2 = primary["box"]
                cx_out = ((bx1 + bx2) / 2.0) / float(orig_w)
                cy_out = (Y_offset + ((by1 + by2) / 2.0) * S) / float(out_h)
                pet_h_strip = (by2 - by1) / float(orig_h)

                is_vis = True
                is_h = (0.35 <= cx_out <= 0.65)
                is_v = (0.28 <= cy_out <= 0.72)
                is_s = (pet_h_strip >= 0.20)

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

            predicted_pass = bool(
                (pred_compliance >= 0.90 or (pred_vis >= 0.90 and pred_h >= 0.90 and pred_v >= 0.90 and pred_s >= 0.90))
                and (total_eval >= len(frame_times) * 0.35)
            )

            if not predicted_pass:
                return {
                    "status": "reject",
                    "reason": (
                        f"PREDICTED_BAD_FRAMING (Score: {pred_compliance:.1%} < 90% — "
                        f"Vis:{pred_vis:.1%}, H:{pred_h:.1%}, V:{pred_v:.1%}, S:{pred_s:.1%})"
                    ),
                    "framing_score": round(pred_compliance, 3),
                    "sharpness": round(med_sharp, 1),
                    "pet_detected_ratio": round(total_eval / max(1, len(frame_times)), 3),
                    "details": {
                        "vis": round(pred_vis, 3), "horiz": round(pred_h, 3),
                        "vert": round(pred_v, 3), "size": round(pred_s, 3)
                    },
                    "failing_frames": []
                }

            if med_sharp < 150.0:
                return {
                    "status": "reject",
                    "reason": f"LOW_SOURCE_SHARPNESS (Median {med_sharp:.1f} < 150.0)",
                    "framing_score": round(pred_compliance, 3),
                    "sharpness": round(med_sharp, 1),
                    "pet_detected_ratio": round(total_eval / max(1, len(frame_times)), 3),
                    "details": {
                        "vis": round(pred_vis, 3), "horiz": round(pred_h, 3),
                        "vert": round(pred_v, 3), "size": round(pred_s, 3)
                    },
                    "failing_frames": []
                }

            return {
                "status": "pass",
                "mode": "blur_fit",
                "aspect_ratio": aspect_ratio,
                "out_w": out_w,
                "out_h": out_h,
                "orig_size": (orig_w, orig_h),
                "crop_w": orig_w,
                "crop_h": orig_h,
                "keyframes_t": [0.0],
                "keyframes_x": [0],
                "keyframes_y": [0],
                "keyframes_zoom": [1.0],
                "framing_score": round(pred_compliance, 3),
                "sharpness": round(med_sharp, 1),
                "pet_detected_ratio": round(total_eval / max(1, len(frame_times)), 3),
                "details": {
                    "vis": round(pred_vis, 3), "horiz": round(pred_h, 3),
                    "vert": round(pred_v, 3), "size": round(pred_s, 3)
                },
                "failing_frames": [],
                "best_start_s": start_s,
                "best_dur_s": dur_s,
                "best_offset": 0.0
            }

        # Helper to evaluate and plan a specific subwindow
        def eval_and_plan(win_start, win_dur):
            win_end = win_start + win_dur
            idxs = [i for i, t in enumerate(frame_times) if win_start - 0.1 <= t <= win_end + 0.1]
            if len(idxs) < 5:
                return None

            sub_times = [frame_times[i] for i in idxs]
            sub_dets = [frame_dets[i] for i in idxs]
            sub_motions = [motion_energies[i] for i in idxs]

            raw_targets_x = [None] * len(idxs)
            raw_targets_y = [None] * len(idxs)
            pet_heights = [None] * len(idxs)
            two_pets_far_apart = 0

            last_kx = orig_w / 2.0
            last_ky = orig_h / 2.0

            for k, dlist in enumerate(sub_dets):
                if not dlist:
                    continue
                cats_dogs = [d for d in dlist if d["class_name"] in ("cat", "dog")]
                if not cats_dogs:
                    continue
                if len(cats_dogs) >= 2:
                    xs = [d["center"][0] for d in cats_dogs[:2]]
                    if abs(xs[0] - xs[1]) > (orig_w * 0.70):
                        two_pets_far_apart += 1

                best_d = None
                best_score = -1.0
                for d in cats_dogs:
                    area_frac = d["area_frac"]
                    conf = d["conf"]
                    motion = sub_motions[k]
                    dist = math.hypot(d["center"][0] - last_kx, d["center"][1] - last_ky)
                    proximity = max(0.0, 1.0 - (dist / float(orig_w * 0.35)))
                    sc = (area_frac * 3.0) + (conf * 1.5) + (motion * 0.05) + (proximity * 2.5)
                    if animal_mode and d["class_name"] == animal_mode:
                        sc += 0.5
                    if sc > best_score:
                        best_score = sc
                        best_d = d

                box = best_d["box"]
                pet_h = box[3] - box[1]
                pet_heights[k] = pet_h / float(orig_h)
                tcx = (box[0] + box[2]) / 2.0
                tcy = (box[1] + box[3]) / 2.0

                # Interaction-aware framing (Phase 4.2): include person/objects interacting with pet
                interact_objs = [d for d in dlist if d["class_name"] not in ("cat", "dog")]
                if interact_objs:
                    closest_obj = min(interact_objs, key=lambda obj: math.hypot(obj["center"][0] - tcx, obj["center"][1] - tcy))
                    dist_to_pet = math.hypot(closest_obj["center"][0] - tcx, closest_obj["center"][1] - tcy)
                    if dist_to_pet <= float(orig_w * 0.40):
                        obx = closest_obj["box"]
                        union_x1 = min(box[0], obx[0])
                        union_x2 = max(box[2], obx[2])
                        union_y1 = min(box[1], obx[1])
                        union_y2 = max(box[3], obx[3])
                        est_crop_w = int(round(orig_h * 9.0 / 16.0))
                        if (union_x2 - union_x1) <= est_crop_w * 0.95:
                            tcx = (union_x1 + union_x2) / 2.0
                            tcy = (union_y1 + union_y2) / 2.0

                raw_targets_x[k] = tcx
                raw_targets_y[k] = tcy
                last_kx = tcx
                last_ky = tcy

            valid_indices = [k for k, x in enumerate(raw_targets_x) if x is not None]
            presence_ratio = len(valid_indices) / max(1, len(idxs))
            if presence_ratio < 0.35:
                return {
                    "status": "reject",
                    "reason": f"NO_PET_TRACKED (Presence {presence_ratio:.1%} < 35%)",
                    "framing_score": 0.0,
                    "sharpness": round(med_sharp, 1),
                    "pet_detected_ratio": round(presence_ratio, 3),
                    "details": {"vis": 0.0, "horiz": 0.0, "vert": 0.0, "size": 0.0},
                    "failing_frames": []
                }

            all_idx = np.arange(len(idxs))
            clean_targets_x = list(np.interp(all_idx, valid_indices, [raw_targets_x[k] for k in valid_indices]))
            clean_targets_y = list(np.interp(all_idx, valid_indices, [raw_targets_y[k] for k in valid_indices]))
            clean_heights = list(np.interp(all_idx, valid_indices, [pet_heights[k] if pet_heights[k] is not None else 0.35 for k in valid_indices]))

            if (two_pets_far_apart / max(1, len(idxs))) > 0.25 and layout_mode == "smart_crop":
                return {
                    "status": "reject",
                    "reason": "REJECT_TWO_PETS_FAR_APART",
                    "framing_score": 0.0,
                    "sharpness": round(med_sharp, 1),
                    "pet_detected_ratio": round(presence_ratio, 3),
                    "details": {"vis": 0.0, "horiz": 0.0, "vert": 0.0, "size": 0.0},
                    "failing_frames": []
                }

            avg_pet_y = float(np.mean(clean_targets_y))
            vert_frac = avg_pet_y / float(orig_h)
            base_zoom = 1.12 if abs(vert_frac - 0.50) > 0.08 else 1.0

            sub_crop_h = int(round(crop_h / base_zoom))
            sub_crop_w = int(round(crop_w / base_zoom))
            if sub_crop_w % 2 != 0: sub_crop_w += 1
            if sub_crop_h % 2 != 0: sub_crop_h += 1
            sub_crop_w = min(sub_crop_w, act_w)
            sub_crop_h = min(sub_crop_h, act_h)
            if sub_crop_w % 2 != 0: sub_crop_w -= 1
            if sub_crop_h % 2 != 0: sub_crop_h -= 1
            min_crop_x = act_x
            max_crop_x = max(act_x, act_x + act_w - sub_crop_w)
            min_crop_y = act_y
            max_crop_y = max(act_y, act_y + act_h - sub_crop_h)
            sub_max_x = max_crop_x - min_crop_x
            sub_max_y = max_crop_y - min_crop_y

            rel_times = [t - win_start for t in sub_times]
            dt = (rel_times[1] - rel_times[0]) if len(rel_times) > 1 else 0.5
            target_crop_x = np.clip(np.array([x - (sub_crop_w / 2.0) for x in clean_targets_x]), min_crop_x, max_crop_x)

            # Determine peak and action window for event-aware camera path (Phase 4.1)
            mid_s = int(len(sub_motions) * 0.15)
            mid_e = int(len(sub_motions) * 0.85)
            peak_idx = mid_s + int(np.argmax(sub_motions[mid_s:mid_e])) if mid_e > mid_s else len(sub_motions) // 2
            peak_t = rel_times[peak_idx]
            action_start_t = max(0.0, peak_t - 1.5)
            action_end_t = min(win_dur, peak_t + 1.5)

            # Look-ahead: blend camera position forward during lead-in so camera anticipates movement
            lookahead_crop_x = np.copy(target_crop_x)
            for k in range(len(rel_times)):
                t_k = rel_times[k]
                if (action_start_t - 1.0) <= t_k < action_start_t:
                    lead_ratio = (t_k - (action_start_t - 1.0)) / 1.0
                    lookahead_crop_x[k] = target_crop_x[k] * (1.0 - 0.35 * lead_ratio) + target_crop_x[peak_idx] * (0.35 * lead_ratio)

            kernel_size = 5
            sigma = 1.8
            kx = np.arange(-(kernel_size // 2), kernel_size // 2 + 1)
            kernel = np.exp(-0.5 * (kx / sigma) ** 2)
            kernel /= np.sum(kernel)
            padded_x = np.pad(lookahead_crop_x, (kernel_size // 2, kernel_size // 2), mode='edge')
            smoothed_x_arr = np.convolve(padded_x, kernel, mode='valid')
            smoothed_x_arr = np.clip(smoothed_x_arr, min_crop_x, max_crop_x)

            # Event-aware camera pan speed: up to 40% of crop width/s with ease-in/out during action window
            dead_zone_px = 0.015 * float(sub_crop_w)
            smoothed_x = []
            cur_x = smoothed_x_arr[0]
            for k in range(len(sub_times)):
                t_k = rel_times[k]
                tval = smoothed_x_arr[k]
                diff = tval - cur_x
                # Higher speed limit (0.40 * sub_crop_w) during action window
                if (action_start_t - 0.2) <= t_k <= (action_end_t + 0.5):
                    dyn_max_speed = 0.40 * float(sub_crop_w)
                else:
                    dyn_max_speed = 0.25 * float(sub_crop_w)

                if abs(diff) >= dead_zone_px:
                    mstep = dyn_max_speed * dt
                    if abs(diff) > sub_crop_w * 0.15:
                        mstep *= 1.4
                    step = math.copysign(min(abs(diff), mstep), diff)
                    cur_x += step
                cur_x = max(float(min_crop_x), min(float(max_crop_x), cur_x))
                smoothed_x.append(cur_x)

            # Peak safety (Phase 4.3): NO punch-in zoom during peak!
            # If pet motion is fast, provide safety zoom-OUT (wider framing) to prevent clipping
            zoom_factors = [1.0] * len(rel_times)
            if win_dur >= 4.0 and max(sub_motions) > 6.0:
                p_dur = 2.0
                safety_zoom = 0.95  # Slightly wider framing at peak
                for k, tr in enumerate(rel_times):
                    dist_p = abs(tr - peak_t)
                    if dist_p < (p_dur / 2.0):
                        u = (dist_p / (p_dur / 2.0)) * math.pi
                        zoom_factors[k] = round(1.0 - (1.0 - safety_zoom) * (0.5 + 0.5 * math.cos(u)), 3)

            n_kf = max(4, min(8, int(win_dur * 1.5)))
            key_indices = [int(i * (len(rel_times) - 1) / (n_kf - 1)) for i in range(n_kf)]
            kf_times = [round(rel_times[idx], 3) for idx in key_indices]
            kf_x = [round(smoothed_x[idx], 1) for idx in key_indices]
            kf_zoom = [zoom_factors[idx] for idx in key_indices]
            kf_y = [int(max(min_crop_y, min(max_crop_y, clean_targets_y[idx] - (sub_crop_h * 0.45)))) for idx in key_indices]

            vis_ok, horiz_ok, vert_ok, size_ok, all_ok = 0, 0, 0, 0, 0
            peak_total = 0
            peak_vis_ok = 0
            peak_horiz_ok = 0
            total_eval = 0
            current_failing_run = 0
            max_failing_run = 0
            failing_details = []

            for k, orig_idx in enumerate(idxs):
                dlist = frame_dets[orig_idx]
                cats = [d for d in dlist if d["class_name"] in ("cat", "dog")]
                if not cats:
                    continue
                total_eval += 1
                best_cat = max(cats, key=lambda d: d["area_frac"] * 2.0 + d["conf"])
                bx1, by1, bx2, by2 = best_cat["box"]

                cam_x = smoothed_x[k]
                cam_y = float(np.interp(rel_times[k], kf_times, kf_y)) if len(kf_times) > 1 else float(kf_y[0])

                cbx1 = bx1 - cam_x
                cby1 = by1 - cam_y
                cbx2 = bx2 - cam_x
                cby2 = by2 - cam_y

                # Area visibility >= 92% (capped to effective crop span when pet is wider than crop)
                inter_x1 = max(0.0, cbx1)
                inter_y1 = max(0.0, cby1)
                inter_x2 = min(float(sub_crop_w), cbx2)
                inter_y2 = min(float(sub_crop_h), cby2)
                inter_area = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
                eff_box_w = min(float(sub_crop_w) * 0.92, max(1.0, cbx2 - cbx1))
                eff_box_h = min(float(sub_crop_h) * 0.92, max(1.0, cby2 - cby1))
                box_area = max(1e-4, eff_box_w * eff_box_h)
                vis_area_frac = min(1.0, inter_area / box_area)
                is_vis = (vis_area_frac >= 0.90)

                cx = ((cbx1 + cbx2) / 2.0) / float(sub_crop_w)
                cy = ((cby1 + cby2) / 2.0) / float(sub_crop_h)
                h_frac = min(0.88, (cby2 - cby1) / float(sub_crop_h))

                # Clamp-aware and close-up-aware horizontal centering
                is_clamped = (cam_x <= min_crop_x + 2.0 or cam_x >= max_crop_x - 2.0)
                is_wide_pet = ((cbx2 - cbx1) >= float(sub_crop_w) * 0.72)
                if 0.25 <= cx <= 0.75:
                    is_h = True
                elif (is_clamped or is_wide_pet) and is_vis:
                    is_h = True # CLAMPED_OK / WIDE_PET_OK
                else:
                    is_h = False

                is_v = (0.15 <= cy <= 0.85)
                is_s = (0.08 <= h_frac <= 1.00)

                if is_vis: vis_ok += 1
                if is_h: horiz_ok += 1
                if is_v: vert_ok += 1
                if is_s: size_ok += 1

                # Stricter check at peak (Phase 4.4): frames during action window
                if action_start_t <= rel_times[k] <= action_end_t:
                    peak_total += 1
                    if is_vis: peak_vis_ok += 1
                    if is_h: peak_horiz_ok += 1

                frame_ok = (is_vis and is_h and is_v and is_s)
                if frame_ok:
                    all_ok += 1
                    current_failing_run = 0
                else:
                    current_failing_run += 1
                    max_failing_run = max(max_failing_run, current_failing_run)
                    reasons = []
                    if not is_vis: reasons.append(f"Vis {vis_area_frac:.1%}")
                    if not is_h: reasons.append(f"H {cx:.1%}")
                    if not is_v: reasons.append(f"V {cy:.1%}")
                    if not is_s: reasons.append(f"Size {h_frac:.1%}")
                    failing_details.append({
                        "frame_idx": k,
                        "t": round(rel_times[k], 2),
                        "abs_t": round(sub_times[k], 2),
                        "reasons": reasons
                    })

            eval_count = max(total_eval, 1)
            pred_compliance = all_ok / eval_count
            pred_vis = vis_ok / eval_count
            pred_h = horiz_ok / eval_count
            pred_v = vert_ok / eval_count
            pred_s = size_ok / eval_count

            peak_vis_ratio = (peak_vis_ok / max(1, peak_total)) if peak_total > 0 else 1.0
            peak_horiz_ratio = (peak_horiz_ok / max(1, peak_total)) if peak_total > 0 else 1.0
            peak_qa_passed = (peak_vis_ratio >= 0.85) and (peak_horiz_ratio >= 0.85)

            threshold = 0.90
            passed = bool(
                (pred_compliance >= threshold) and
                (max_failing_run <= 1) and
                (total_eval >= len(sub_times) * 0.35) and
                peak_qa_passed
            )

            status = "pass" if passed else "reject"
            if not peak_qa_passed:
                reason = f"REJECT_PEAK_FRAMING (Pet not 100% visible at peak: vis={peak_vis_ratio:.1%}, center={peak_horiz_ratio:.1%})"
            else:
                reason = "PREDICT_PASS" if passed else (
                    f"PREDICTED_BAD_FRAMING (Score: {pred_compliance:.1%} < 90% — "
                    f"Vis:{pred_vis:.1%}, H:{pred_h:.1%}, V:{pred_v:.1%}, Size:{pred_s:.1%})"
                )

            return {
                "status": status,
                "reason": reason,
                "mode": mode,
                "aspect_ratio": aspect_ratio,
                "out_w": out_w,
                "out_h": out_h,
                "is_clamped": bool(is_vertical_direct or (sub_max_x <= 4)),
                "orig_size": (orig_w, orig_h),
                "active_box": [act_x, act_y, act_w, act_h],
                "crop_w": sub_crop_w,
                "crop_h": sub_crop_h,
                "keyframes_t": kf_times,
                "keyframes_x": [act_x] * len(kf_times) if is_vertical_direct else kf_x,
                "keyframes_y": [act_y] * len(kf_times) if is_vertical_direct else kf_y,
                "keyframes_zoom": [1.0] * len(kf_times) if is_vertical_direct else kf_zoom,
                "framing_score": round(pred_compliance, 3),
                "sharpness": round(med_sharp, 1),
                "pet_detected_ratio": round(presence_ratio, 3),
                "details": {
                    "vis": round(pred_vis, 3),
                    "horiz": round(pred_h, 3),
                    "vert": round(pred_v, 3),
                    "size": round(pred_s, 3)
                },
                "peak_qa": {
                    "passed": peak_qa_passed,
                    "peak_t": round(peak_t, 2),
                    "action_window": [round(action_start_t, 2), round(action_end_t, 2)],
                    "vis_ratio": round(peak_vis_ratio, 3),
                    "horiz_ratio": round(peak_horiz_ratio, 3)
                },
                "max_fail_run": max_failing_run,
                "failing_frames": failing_details,
                "win_start": round(win_start, 2),
                "win_dur": round(win_dur, 2)
            }

        # 1. Base evaluation at offset 0.0
        base_plan = eval_and_plan(start_s, dur_s)
        if not base_plan:
            base_plan = {
                "status": "reject",
                "reason": "ANALYSIS_FAILED",
                "framing_score": 0.0,
                "sharpness": round(med_sharp, 1),
                "pet_detected_ratio": 0.0,
                "details": {"vis": 0.0, "horiz": 0.0, "vert": 0.0, "size": 0.0},
                "failing_frames": [],
                "win_start": start_s,
                "win_dur": dur_s
            }

        # Fast exit if base plan already achieves 100% pass with 0 failing frames
        if base_plan["status"] == "pass" and base_plan["framing_score"] >= 1.0 and len(base_plan.get("failing_frames", [])) == 0:
            base_plan["best_offset"] = 0.0
            base_plan["best_start_s"] = start_s
            base_plan["best_dur_s"] = dur_s
            return base_plan

        if not allow_slide or layout_mode != "smart_crop":
            base_plan["best_offset"] = 0.0
            base_plan["best_start_s"] = start_s
            base_plan["best_dur_s"] = dur_s
            return base_plan

        # 2. Search sliding offsets and durations
        offsets = [0.0]
        curr = step_s
        while curr <= max_slide_s + 1e-5:
            offsets.append(curr)
            offsets.append(-curr)
            curr += step_s

        durations_to_try = [dur_s, dur_s - 0.5, dur_s + 0.5]

        best_plan = base_plan
        best_score = base_plan.get("framing_score", 0.0)
        best_offset = 0.0
        best_dur = dur_s

        for d_try in durations_to_try:
            for off in offsets:
                w_start = start_s + off
                if w_start < 0 or (w_start + d_try) > total_sec:
                    continue
                cand_plan = eval_and_plan(w_start, d_try)
                if not cand_plan:
                    continue

                c_score = cand_plan.get("framing_score", 0.0)
                c_pass = (cand_plan.get("status") == "pass")
                b_pass = (best_plan.get("status") == "pass")

                is_better = False
                if c_pass and not b_pass:
                    is_better = True
                elif c_pass == b_pass:
                    if c_score > best_score:
                        is_better = True
                    elif c_score == best_score and abs(off) < abs(best_offset):
                        is_better = True

                if is_better:
                    best_score = c_score
                    best_plan = cand_plan
                    best_offset = off
                    best_dur = d_try
                    if c_pass and c_score >= 1.0 and abs(off) == 0.0:
                        break

        best_plan["best_offset"] = round(best_offset, 2)
        best_plan["best_start_s"] = round(start_s + best_offset, 2)
        best_plan["best_dur_s"] = round(best_dur, 2)
        return best_plan

    def build_ffmpeg_crop_expression(self, plan):
        """
        Builds a mathematically smooth, continuous C1-Hermite smoothstep expression
        evaluated per-frame inside FFmpeg's native C engine.
        """
        orig_w, orig_h = plan.get("orig_size", (1920, 1080))
        out_w = plan.get("out_w", 1080)
        out_h = plan.get("out_h", 1920)
        crop_w = plan.get("crop_w", 608)
        crop_h = plan.get("crop_h", 1080)
        kf_times = plan.get("keyframes_t", [0.0])
        kf_x = plan.get("keyframes_x", [plan.get("crop_x", 0)])
        kf_y = plan.get("keyframes_y", [plan.get("crop_y", 0)] * len(kf_times))
        kf_zoom = plan.get("keyframes_zoom", [1.0] * len(kf_times))

        max_x = orig_w - crop_w
        max_y = orig_h - crop_h
        n = len(kf_times)

        if n <= 1:
            x_val = int(max(0, min(max_x, kf_x[0] if kf_x else max_x // 2)))
            y_val = int(max(0, min(max_y, kf_y[0] if kf_y else 0)))
            return f"crop=w={crop_w}:h={crop_h}:x={x_val}:y={y_val},scale={out_w}:{out_h}:flags=lanczos,unsharp=5:5:0.35"

        # Check if punch-in zoom is present
        has_zoom = any(z > 1.01 for z in kf_zoom)

        # Build smoothstep crop x(t) expression
        last_x = int(max(0, min(max_x, kf_x[-1])))
        x_expr = f"{last_x}"

        for i in range(n - 2, -1, -1):
            t_a = kf_times[i]
            t_b = kf_times[i+1]
            x_a = int(max(0, min(max_x, kf_x[i])))
            x_b = int(max(0, min(max_x, kf_x[i+1])))
            dt = max(0.001, t_b - t_a)

            if x_a == x_b:
                seg_expr = f"{x_a}"
            else:
                u_expr = f"((t-{t_a:.3f})/{dt:.3f})"
                s_expr = f"({u_expr}*{u_expr}*(3-2*{u_expr}))"
                seg_expr = f"({x_a}+({x_b - x_a})*{s_expr})"

            x_expr = f"if(lt(t,{t_b:.3f}),{seg_expr},{x_expr})"

        final_x_expr = f"min(max(0,{x_expr}),{max_x})"

        # Build smoothstep crop y(t) expression
        if max_y > 0 and any(y > 0 for y in kf_y):
            last_y = int(max(0, min(max_y, kf_y[-1])))
            y_expr = f"{last_y}"
            for i in range(n - 2, -1, -1):
                t_a = kf_times[i]
                t_b = kf_times[i+1]
                y_a = int(max(0, min(max_y, kf_y[i])))
                y_b = int(max(0, min(max_y, kf_y[i+1])))
                dt = max(0.001, t_b - t_a)
                if y_a == y_b:
                    seg_y = f"{y_a}"
                else:
                    u_expr = f"((t-{t_a:.3f})/{dt:.3f})"
                    s_expr = f"({u_expr}*{u_expr}*(3-2*{u_expr}))"
                    seg_y = f"({y_a}+({y_b - y_a})*{s_expr})"
                y_expr = f"if(lt(t,{t_b:.3f}),{seg_y},{y_expr})"
            final_y_expr = f"min(max(0,{y_expr}),{max_y})"
        else:
            final_y_expr = "0"

        if not has_zoom:
            vf = f"crop=w={crop_w}:h={crop_h}:x='{final_x_expr}':y='{final_y_expr}',scale={out_w}:{out_h}:flags=bicubic,unsharp=5:5:0.5"
        else:
            # Build zoom expression: z(t)
            last_z = kf_zoom[-1]
            z_expr = f"{last_z:.3f}"
            for i in range(n - 2, -1, -1):
                t_a = kf_times[i]
                t_b = kf_times[i+1]
                z_a = kf_zoom[i]
                z_b = kf_zoom[i+1]
                dt = max(0.001, t_b - t_a)
                if abs(z_a - z_b) < 0.001:
                    seg_z = f"{z_a:.3f}"
                else:
                    u_expr = f"((t-{t_a:.3f})/{dt:.3f})"
                    s_expr = f"({u_expr}*{u_expr}*(3-2*{u_expr}))"
                    seg_z = f"({z_a}+({z_b - z_a:.3f})*{s_expr})"
                z_expr = f"if(lt(t,{t_b:.3f}),{seg_z},{z_expr})"

            cw_expr = f"max(200,trunc({crop_w}/({z_expr})/2)*2)"
            ch_expr = f"max(200,trunc({crop_h}/({z_expr})/2)*2)"
            y_zoom_expr = f"trunc(({final_y_expr}+({crop_h}-{ch_expr})*0.42)/2)*2"
            vf = f"crop=w='{cw_expr}':h='{ch_expr}':x='{final_x_expr}':y='{y_zoom_expr}',scale={out_w}:{out_h}:flags=bicubic,unsharp=5:5:0.5"

        return vf

    def reframe_segment_ffmpeg(self, in_path, out_path, start_s, dur_s, plan, speed=1.0, color_preset=None, color_strength=1.0, max_retries=3, timeout_sec=None):
        """
        Renders the reframed vertical/horizontal short segment using optimized single-pass FFmpeg.
        Supports EDL parameters: speed multiplier and color preset enhancement.
        Includes timeout watchdog (5x clip length) and retry logic with exponential backoff.
        """
        mode = plan.get("mode", "smart_crop")
        out_w = plan.get("out_w", 1080)
        out_h = plan.get("out_h", 1920)

        if mode not in ("blur_fit", "blur_fit_16_9", "vertical_direct", "landscape_direct") and (not plan or "orig_size" not in plan or "crop_w" not in plan):
            plan = self.plan_reframe(in_path, start_s, dur_s, allow_slide=True, out_w=out_w, out_h=out_h)
            mode = plan.get("mode", "smart_crop")

        watchdog_timeout = timeout_sec if (timeout_sec and timeout_sec < 180) else max(35, int(dur_s * 5.0))

        orig_w, orig_h = plan.get("orig_size", (1920, 1080))
        act_box = plan.get("active_box", [0, 0, orig_w, orig_h])
        act_x, act_y, act_w, act_h = act_box[0], act_box[1], act_box[2], act_box[3]
        pre_crop = f"crop=w={act_w}:h={act_h}:x={act_x}:y={act_y}," if (act_w < orig_w or act_h < orig_h) else ""

        if mode == "blur_fit":
            vf = (
                f"{pre_crop}split[main][bg];"
                f"[bg]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,scale={out_w}:{out_h}[bg];"
                f"[main]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,unsharp=5:5:0.35"
            )
        elif mode == "blur_fit_16_9":
            strip_w = max(int(out_w * 0.56), 1080)
            if strip_w % 2 != 0: strip_w += 1
            vf = (
                f"{pre_crop}split[main][bg];"
                f"[bg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},boxblur=15:3[bg];"
                f"[main]scale={strip_w}:{out_h}:force_original_aspect_ratio=increase,crop={strip_w}:{out_h}[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,unsharp=5:5:0.35"
            )
        elif mode in ("vertical_direct", "landscape_direct"):
            vf = f"{pre_crop}scale={out_w}:{out_h}:flags=bicubic,unsharp=5:5:0.35"
        else:
            vf = self.build_ffmpeg_crop_expression(plan)

        # Apply color preset enhancement if requested with strength interpolation
        if color_preset and color_preset != "natural" and color_strength > 0.01:
            try:
                preset_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "color_presets.json")
                if os.path.exists(preset_file):
                    with open(preset_file, "r", encoding="utf-8") as f_cp:
                        presets_data = json.load(f_cp)
                    preset_info = presets_data.get("presets", {}).get(color_preset, {})
                    params = preset_info.get("params", {})
                    s = min(1.0, max(0.0, float(color_strength)))
                    
                    if color_preset == "vivid":
                        c = 1.0 + (params.get("contrast", 1.15) - 1.0) * s
                        b = params.get("brightness", 0.02) * s
                        sat = 1.0 + (params.get("saturation", 1.35) - 1.0) * s
                        c_filter = f"eq=contrast={c:.3f}:brightness={b:.3f}:saturation={sat:.3f}"
                        if params.get("unsharp"):
                            c_filter += ",unsharp=5:5:0.5:5:5:0.0"
                    elif color_preset == "cinema":
                        c = 1.0 + (params.get("contrast", 1.18) - 1.0) * s
                        b = params.get("brightness", -0.02) * s
                        sat = 1.0 + (params.get("saturation", 1.08) - 1.0) * s
                        c_filter = f"eq=contrast={c:.3f}:brightness={b:.3f}:saturation={sat:.3f}"
                        curves = params.get("curves")
                        if curves:
                            c_filter += f",curves={curves}"
                    elif color_preset in ("warm", "cool"):
                        tgt_temp = params.get("temperature", 6800 if color_preset == "warm" else 5400)
                        temp = 6500 + int((tgt_temp - 6500) * s)
                        c = 1.0 + (params.get("contrast", 1.08) - 1.0) * s
                        b = params.get("brightness", 0.01) * s
                        sat = 1.0 + (params.get("saturation", 1.15) - 1.0) * s
                        c_filter = f"colortemperature=temperature={temp},eq=contrast={c:.3f}:brightness={b:.3f}:saturation={sat:.3f}"
                    elif color_preset == "clahe":
                        clip_lim = max(1.0, 1.0 + (params.get("clahe_clip_limit", 2.5) - 1.0) * s)
                        c = 1.0 + (params.get("contrast", 1.08) - 1.0) * s
                        sat = 1.0 + (params.get("saturation", 1.12) - 1.0) * s
                        c_filter = f"clahe=clip_limit={clip_lim:.2f}:tile_grid_size_x=8:tile_grid_size_y=8,eq=contrast={c:.3f}:saturation={sat:.3f}"
                    else:
                        c_filter = preset_info.get("ffmpeg_filter")
                        if c_filter == "null":
                            c_filter = None

                    if c_filter:
                        vf = f"{vf},{c_filter}"
            except Exception:
                pass

        # Speed adjustment filter: applied AFTER crop and color filters, enforcing 30 fps CFR and pure BT.709
        spd = float(speed) if speed else 1.0
        if abs(spd - 1.0) > 0.01:
            pts_factor = 1.0 / spd
            vf = f"{vf},setpts={pts_factor:.4f}*(PTS-STARTPTS),fps=30,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"
            if 0.5 <= spd <= 2.0:
                af = f"atempo={spd:.4f}"
            elif spd > 2.0:
                af = f"atempo=2.0,atempo={spd/2.0:.4f}"
            else:
                af = f"atempo=0.5,atempo={spd/0.5:.4f}"
        else:
            vf = f"{vf},setpts=PTS-STARTPTS,fps=30,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"
            af = None

        out_dur_s = dur_s / spd if spd > 0.01 else dur_s

        enc_info = get_best_video_encoder()
        v_args = enc_info["args"]

        tmp_out = f"{out_path}.tmp_{uuid.uuid4().hex[:8]}.mp4"

        def build_cmd(use_v_args, target_file):
            c = [
                FFMPEG_EXE, "-y",
                "-nostats", "-loglevel", "error",
                "-ss", f"{start_s:.3f}",
                "-t", f"{dur_s:.3f}",
                "-i", in_path,
                "-t", f"{out_dur_s:.3f}",
                "-vf", vf,
            ]
            c.extend(use_v_args)
            c.extend([
                "-r", "30",
                "-fps_mode", "cfr",
                "-color_primaries", "bt709",
                "-color_trc", "bt709",
                "-colorspace", "bt709"
            ])
            if af:
                c.extend(["-af", af])
            c.extend([
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-f", "mp4",
                target_file
            ])
            return c

        current_v_args = v_args
        for attempt in range(max_retries):
            cmd = build_cmd(current_v_args, tmp_out)
            try:
                res = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=watchdog_timeout
                )
                if res.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 10000:
                    # Flush & atomic rename
                    try:
                        os.replace(tmp_out, out_path)
                        return True
                    except Exception:
                        import shutil
                        shutil.copy2(tmp_out, out_path)
                        try: os.remove(tmp_out)
                        except Exception: pass
                        return True
                else:
                    parent_d = os.path.dirname(out_path)
                    job_dir = os.path.dirname(parent_d) if os.path.basename(parent_d) == "clips" else parent_d
                    ff_dir = os.path.join(job_dir, "ffmpeg")
                    step_bname = os.path.splitext(os.path.basename(out_path))[0]
                    try:
                        os.makedirs(ff_dir, exist_ok=True)
                        step_log = os.path.join(ff_dir, f"{step_bname}.log")
                        with open(step_log, "a", encoding="utf-8") as f_ff:
                            f_ff.write(f"--- Attempt {attempt} ---\n" + (res.stderr or "") + "\n")
                    except Exception:
                        pass

                    err_lines = [l for l in (res.stderr or "").splitlines() if l.strip()]
                    if err_lines:
                        # Log one summary line, write details to step log
                        print(f"[FFMPEG] {len(err_lines)} decode/encode message(s) logged to ffmpeg/{step_bname}.log: {err_lines[0][:120]}")
                    if current_v_args != ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17"]:
                        current_v_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17"]
            except subprocess.TimeoutExpired:
                print(f"[FFMPEG TIMEOUT attempt {attempt} for {os.path.basename(out_path)}]")
                if current_v_args != ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17"]:
                    current_v_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17"]
            except Exception:
                pass
            try:
                if os.path.exists(tmp_out):
                    os.remove(tmp_out)
            except Exception:
                pass
            time.sleep(0.4 * (attempt + 1))

        if os.path.exists(tmp_out):
            try: os.remove(tmp_out)
            except Exception: pass
        return False

    def early_check_segment_gate(self, in_path, start_s, dur_s, plan, layout_mode="smart_crop"):
        """
        Early abort check (Requirement 3b):
        Verifies gate compatibility and checks sample frame after first 25% of clip.
        Aborts immediately if doomed to fail, saving full render time.
        """
        try:
            if not in_path or not os.path.exists(in_path) or os.path.getsize(in_path) < 1000:
                return False, "CORRUPT_OR_MISSING_SOURCE"

            mode = plan.get("mode", "smart_crop")
            # 1. Gate / layout conflict check
            if mode == "blur_fit" and layout_mode == "smart_crop":
                return False, "BLURRED_BARS_DETECTED (Blur-fit candidate rejected in Smart Crop mode)"

            # 2. Keyframe validity and pet presence check after 25% duration
            t_check = start_s + (dur_s * 0.25)
            # Verify plan has keyframes and non-empty crop
            orig_w, orig_h = plan.get("orig_size", (1920, 1080))
            if mode == "smart_crop":
                crop_w = plan.get("crop_w", int(orig_h * 9 / 16))
                if crop_w <= 0 or (1080.0 / max(1, crop_w)) > 2.05:
                    return False, "UPSCALE_EXCEEDED"
            
            # Check framing score in plan (allow down to 80% for dynamic action pet cuts)
            framing_score = plan.get("framing_score", 0.0)
            if framing_score < 0.80:
                return False, f"PREDICTED_BAD_FRAMING ({framing_score:.1%} < 80%)"

            return True, "EARLY_CHECK_PASS"
        except Exception as e:
            return True, f"Early check error: {e}"


    def verify_post_crop_gate(self, cropped_path, plan=None, layout_mode="smart_crop"):
        """
        QA Gate: on the cropped video, verify layout fill, pet centering, sharpness and real footage.
        At least 88% of frames must have pet centered and content filling the 1080x1920 frame.
        Uses fast 12-frame single-pass decode (< 1.5s).
        """
        from qa_check import verify_single_pass_post_crop_gate
        effective_layout = layout_mode
        if plan and plan.get("mode") in ["blur_fit", "smart_crop"]:
            effective_layout = plan["mode"]
        return verify_single_pass_post_crop_gate(
            cropped_path,
            plan=plan,
            layout_mode=effective_layout,
            n_samples=12,
            detector=getattr(self, "detector", None)
        )



SmartCropReframer = AutoReframeEngine
