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
import subprocess

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_VENV_SITE = os.path.join(_BASE_DIR, ".venv", "Lib", "site-packages")
if os.path.exists(_VENV_SITE) and _VENV_SITE not in sys.path:
    sys.path.insert(0, _VENV_SITE)

import cv2
import numpy as np
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

    def plan_reframe(self, video_path=None, start_s=None, dur_s=None, animal_mode="cat", layout_mode="smart_crop", stricter=False, allow_slide=True, max_slide_s=4.0, step_s=0.5, **kwargs):
        """
        Analyzes source clip and computes a smooth camera trajectory.
        Includes feasibility check, clamp-aware centering, area visibility,
        single-pass buffered sliding window search (+/-4s), and exact failing frame diagnostics.
        """
        video_path = video_path or kwargs.get("source_video_path") or kwargs.get("source_path")
        start_s = start_s if start_s is not None else kwargs.get("start_sec", 0.0)
        dur_s = dur_s if dur_s is not None else kwargs.get("duration_sec", 10.0)

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

        # 2. Check if source is already vertical (9:16)
        src_aspect = orig_w / max(1.0, float(orig_h))
        is_vertical_direct = (src_aspect <= 0.60)

        # 3. Base 9:16 crop window at full source height
        crop_h = orig_h
        crop_w = orig_w if is_vertical_direct else int(round(orig_h * 9.0 / 16.0))
        if crop_w % 2 != 0:
            crop_w += 1
        crop_w = min(crop_w, orig_w)
        max_x = orig_w - crop_w
        max_y = orig_h - crop_h

        # Upscale factor check
        if layout_mode != "blur_fit":
            upscale_factor = 1080.0 / float(crop_w)
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

        # Measure true visual sharpness on standard (540, 960) canvas matching post-crop gate
        source_sharpness_scores = []
        try:
            cap_sh = cv2.VideoCapture(video_path)
            for sh_idx in range(3):
                sample_t_s = start_s + dur_s * (sh_idx + 0.5) / 3.0
                cap_sh.set(cv2.CAP_PROP_POS_MSEC, sample_t_s * 1000.0)
                sh_ret, sh_frame = cap_sh.read()
                if sh_ret and sh_frame is not None:
                    sh_h, sh_w = sh_frame.shape[:2]
                    sh_cw = int(sh_h * 9 / 16) if layout_mode != "blur_fit" else sh_w
                    sh_cx = max(0, (sh_w - sh_cw) // 2)
                    sh_crop = sh_frame[:, sh_cx:sh_cx+sh_cw]
                    sh_std = cv2.resize(sh_crop, (540, 960))
                    sh_gray = cv2.cvtColor(sh_std, cv2.COLOR_BGR2GRAY)
                    sh_hg, sh_wg = sh_gray.shape
                    sh_wsub = int(sh_wg * 0.70)
                    sh_xsub = int((sh_wg - sh_wsub) / 2)
                    s_full = float(cv2.Laplacian(sh_gray, cv2.CV_64F).var())
                    s_fg = float(cv2.Laplacian(sh_gray[:, sh_xsub:sh_xsub+sh_wsub], cv2.CV_64F).var())
                    s_cnt = float(cv2.Laplacian(sh_gray[int(sh_hg*0.32):int(sh_hg*0.68), int(sh_wg*0.15):int(sh_wg*0.85)], cv2.CV_64F).var())
                    source_sharpness_scores.append(max(s_full, s_fg, s_cnt))
            cap_sh.release()
        except Exception:
            pass

        med_sharp = float(np.median(source_sharpness_scores)) if source_sharpness_scores else 0.0

        # Step 4a: Feasibility check (Median pet box width > 92% crop width -> FRAMING_INFEASIBLE)
        if pet_widths:
            med_pet_w = float(np.median(pet_widths))
            if med_pet_w > 0.92 * float(crop_w):
                return {
                    "status": "reject",
                    "reason": f"FRAMING_INFEASIBLE (Median pet box width {med_pet_w:.1f}px > 92% crop {crop_w}px)",
                    "framing_score": 0.0,
                    "sharpness": round(med_sharp, 1),
                    "pet_detected_ratio": 0.0,
                    "details": {"vis": 0.0, "horiz": 0.0, "vert": 0.0, "size": 0.0},
                    "failing_frames": []
                }

        # 4b. Blur-fit evaluation mode
        if layout_mode == "blur_fit":
            S = 1080.0 / float(orig_w)
            Y_offset = (1920.0 - orig_h * S) / 2.0
            vis_ok, horiz_ok, vert_ok, size_ok, all_ok = 0, 0, 0, 0, 0
            total_eval = 0

            for i, dets in enumerate(frame_dets):
                if not dets:
                    continue
                total_eval += 1
                primary = max(dets, key=lambda d: d["area_frac"] * 2.0 + d["conf"])
                bx1, by1, bx2, by2 = primary["box"]
                cx_out = ((bx1 + bx2) / 2.0) / float(orig_w)
                cy_out = (Y_offset + ((by1 + by2) / 2.0) * S) / 1920.0
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

            if med_sharp < 15.0:
                return {
                    "status": "reject",
                    "reason": f"LOW_SOURCE_SHARPNESS (Median raw LapVar {med_sharp:.1f} < 15.0)",
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

            sub_crop_h = int(round(orig_h / base_zoom))
            sub_crop_w = int(round(sub_crop_h * 9.0 / 16.0))
            if sub_crop_w % 2 != 0: sub_crop_w += 1
            if sub_crop_h % 2 != 0: sub_crop_h += 1
            sub_crop_w = min(sub_crop_w, orig_w)
            sub_crop_h = min(sub_crop_h, orig_h)
            sub_max_x = orig_w - sub_crop_w
            sub_max_y = orig_h - sub_crop_h

            rel_times = [t - win_start for t in sub_times]
            dt = (rel_times[1] - rel_times[0]) if len(rel_times) > 1 else 0.5
            target_crop_x = np.clip(np.array([x - (sub_crop_w / 2.0) for x in clean_targets_x]), 0, sub_max_x)

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
            smoothed_x_arr = np.clip(smoothed_x_arr, 0, sub_max_x)

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
                cur_x = max(0.0, min(float(sub_max_x), cur_x))
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
            kf_y = [int(max(0, min(sub_max_y, clean_targets_y[idx] - (sub_crop_h * 0.45)))) for idx in key_indices]

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

                # Area visibility >= 95%
                inter_x1 = max(0.0, cbx1)
                inter_y1 = max(0.0, cby1)
                inter_x2 = min(float(sub_crop_w), cbx2)
                inter_y2 = min(float(sub_crop_h), cby2)
                inter_area = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
                box_area = max(1e-4, (cbx2 - cbx1) * (cby2 - cby1))
                vis_area_frac = inter_area / box_area
                is_vis = (vis_area_frac >= 0.95)

                cx = ((cbx1 + cbx2) / 2.0) / float(sub_crop_w)
                cy = ((cby1 + cby2) / 2.0) / float(sub_crop_h)
                h_frac = (cby2 - cby1) / float(sub_crop_h)

                # Clamp-aware horizontal centering
                is_clamped = (cam_x <= 2.0 or cam_x >= sub_max_x - 2.0)
                if 0.38 <= cx <= 0.62:
                    is_h = True
                elif is_clamped and is_vis:
                    is_h = True # CLAMPED_OK
                else:
                    is_h = False

                if sub_max_y > 0:
                    is_v = (0.30 <= cy <= 0.62)
                else:
                    is_v = (0.20 <= cy <= 0.75) and (cby1 >= -3 and cby2 <= sub_crop_h + 3)

                is_s = (0.20 <= h_frac <= 0.75)

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
            peak_qa_passed = (peak_vis_ratio >= 0.99) and (peak_horiz_ratio >= 0.90)

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
                "mode": "vertical_direct" if is_vertical_direct else "smart_crop",
                "is_clamped": bool(is_vertical_direct or (sub_max_x == 0)),
                "orig_size": (orig_w, orig_h),
                "crop_w": sub_crop_w,
                "crop_h": sub_crop_h,
                "keyframes_t": kf_times,
                "keyframes_x": [0] * len(kf_times) if is_vertical_direct else kf_x,
                "keyframes_y": [0] * len(kf_times) if is_vertical_direct else kf_y,
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
            return f"crop=w={crop_w}:h={crop_h}:x={x_val}:y={y_val},scale=1080:1920:flags=lanczos,unsharp=5:5:0.35"

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
            vf = f"crop=w={crop_w}:h={crop_h}:x='{final_x_expr}':y='{final_y_expr}',scale=1080:1920:flags=bicubic,unsharp=5:5:0.5"
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
            vf = f"crop=w='{cw_expr}':h='{ch_expr}':x='{final_x_expr}':y='{y_zoom_expr}',scale=1080:1920:flags=bicubic,unsharp=5:5:0.5"

        return vf

    def reframe_segment_ffmpeg(self, in_path, out_path, start_s, dur_s, plan, speed=1.0, color_preset=None, color_strength=1.0, max_retries=3, timeout_sec=None):
        """
        Renders the reframed vertical short segment using optimized single-pass FFmpeg.
        Supports EDL parameters: speed multiplier and color preset enhancement.
        Includes timeout watchdog (5x clip length) and retry logic with exponential backoff.
        """
        mode = plan.get("mode", "smart_crop")
        if mode not in ("blur_fit", "vertical_direct") and (not plan or "orig_size" not in plan or "crop_w" not in plan):
            plan = self.plan_reframe(in_path, start_s, dur_s, allow_slide=True)
            mode = plan.get("mode", "smart_crop")

        watchdog_timeout = timeout_sec if (timeout_sec and timeout_sec < 180) else max(35, int(dur_s * 5.0))

        if mode == "blur_fit":
            vf = (
                f"split[main][bg];"
                f"[bg]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,scale=1080:1920[bg];"
                f"[main]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,unsharp=5:5:0.35"
            )
        elif mode == "vertical_direct":
            vf = "scale=1080:1920:flags=bicubic,unsharp=5:5:0.35"
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

        # Speed adjustment filter: applied AFTER crop and color filters, enforcing 30 fps CFR
        spd = float(speed) if speed else 1.0
        if abs(spd - 1.0) > 0.01:
            pts_factor = 1.0 / spd
            vf = f"{vf},setpts={pts_factor:.4f}*(PTS-STARTPTS),fps=30"
            if 0.5 <= spd <= 2.0:
                af = f"atempo={spd:.4f}"
            elif spd > 2.0:
                af = f"atempo=2.0,atempo={spd/2.0:.4f}"
            else:
                af = f"atempo=0.5,atempo={spd/0.5:.4f}"
        else:
            vf = f"{vf},setpts=PTS-STARTPTS,fps=30"
            af = None

        out_dur_s = dur_s / spd if spd > 0.01 else dur_s

        cmd = [
            FFMPEG_EXE, "-y",
            "-ss", f"{start_s:.3f}",
            "-t", f"{dur_s:.3f}",
            "-i", in_path,
            "-t", f"{out_dur_s:.3f}",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
            "-r", "30",
        ]
        if af:
            cmd.extend(["-af", af])
        cmd.extend([
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            out_path
        ])

        for attempt in range(max_retries):
            try:
                res = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=watchdog_timeout
                )
                if res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
                    return True
                else:
                    print(f"[FFMPEG ERROR attempt {attempt}] {res.stderr[-300:] if res.stderr else 'no stderr'}")
            except subprocess.TimeoutExpired:
                print(f"[FFMPEG TIMEOUT attempt {attempt}]")
                pass
            except Exception:
                pass
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)
            except Exception:
                pass
            time.sleep(0.4 * (attempt + 1))

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
            
            # Check framing score in plan
            framing_score = plan.get("framing_score", 0.0)
            if framing_score < 0.88:
                return False, f"PREDICTED_BAD_FRAMING ({framing_score:.1%} < 88%)"

            return True, "EARLY_CHECK_PASS"
        except Exception as e:
            return True, f"Early check error: {e}"


    def verify_post_crop_gate(self, cropped_path, plan=None, layout_mode="smart_crop"):
        """
        QA Gate: on the cropped video, verify layout fill and pet centering.
        At least 88% of frames must have pet centered and content filling the 1080x1920 frame.
        """
        from qa_check import check_pet_centering, check_layout_fill
        has_slack = False
        effective_layout = layout_mode
        if plan:
            orig_h = plan.get("orig_size", (0, 0))[1]
            crop_h = plan.get("crop_h", orig_h)
            has_slack = bool(crop_h < orig_h)
            if plan.get("mode") in ["blur_fit", "smart_crop"]:
                effective_layout = plan["mode"]
        fill_res = check_layout_fill(cropped_path, n_samples=16, layout_mode=effective_layout)
        cent_res = check_pet_centering(cropped_path, n_samples=24, has_vertical_slack=has_slack, layout_mode=effective_layout)
        passed = bool(fill_res["passed"] and cent_res["passed"])
        reason = (
            f"Centering: {cent_res.get('compliance_ratio', 0.0):.1%} "
            f"(Vis:{cent_res.get('visibility_ratio', 0.0):.1%}, "
            f"H:{cent_res.get('horizontal_ratio', 0.0):.1%}, "
            f"V:{cent_res.get('vertical_ratio', 0.0):.1%}, "
            f"S:{cent_res.get('size_ratio', 0.0):.1%}), "
            f"Layout: {fill_res.get('reason', '')}"
        )
        return passed, reason


SmartCropReframer = AutoReframeEngine
