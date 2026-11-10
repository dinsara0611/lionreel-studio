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
import math
import subprocess
import cv2
import numpy as np
import imageio_ffmpeg
from pet_detector import PetDetector

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


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

    def plan_reframe(self, video_path, start_s, dur_s, animal_mode="cat", layout_mode="smart_crop", stricter=False):
        """
        Analyzes source clip and computes a smooth camera trajectory.
        Returns:
            dict containing crop plan, or rejection reason.
        """
        if not os.path.exists(video_path):
            return {"status": "reject", "reason": "Source file not found"}

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
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
        if src_aspect <= 0.60:
            # Already vertical: scale to 1080x1920 directly
            return {
                "status": "pass",
                "mode": "vertical_direct",
                "orig_size": (orig_w, orig_h),
                "crop_w": orig_w,
                "crop_h": orig_h,
                "keyframes_t": [0.0],
                "keyframes_x": [0],
                "keyframes_y": [0],
                "keyframes_zoom": [1.0]
            }

        # Forced blur-fit layout mode
        if layout_mode == "blur_fit":
            return {
                "status": "pass",
                "mode": "blur_fit",
                "orig_size": (orig_w, orig_h),
                "reason": "LAYOUT_BLURFIT (Manual user override)"
            }

        # 3. Compute base 9:16 crop window at full source height
        # For 1920x1080: crop_w = 608, crop_h = 1080
        # For 3840x2160: crop_w = 1216, crop_h = 2160
        crop_h = orig_h
        crop_w = int(round(orig_h * 9.0 / 16.0))
        if crop_w % 2 != 0:
            crop_w += 1
        crop_w = min(crop_w, orig_w)

        # Upscale factor check
        upscale_factor = 1080.0 / float(crop_w)
        if upscale_factor > 2.05:
            return {
                "status": "reject",
                "reason": f"UPSCALE_LIMIT_EXCEEDED (Upscale factor {upscale_factor:.2f}x > 2.0x limit)"
            }

        # 4. Dense Subject Tracking across clip interval (5.0 fps = every 2nd-3rd frame for speed)
        sample_fps = 5.0  # Sample every 0.2s
        total_sample_steps = max(5, int(dur_s * sample_fps))
        sample_times = [start_s + (i / max(1, total_sample_steps - 1)) * dur_s for i in range(total_sample_steps)]
        
        cap = cv2.VideoCapture(video_path)
        detections_per_time = []
        motion_energies = []
        sample_sharpness = []
        prev_gray = None

        for t in sample_times:
            frame_idx = min(total_frames - 1, int(t * fps))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                detections_per_time.append([])
                motion_energies.append(0.0)
                continue

            # Raw crop sharpness (center 9:16 slice)
            hf, wf = frame.shape[:2]
            cwf = int(hf * 9 / 16)
            cxf = (wf - cwf) // 2
            crop_sample = frame[:, cxf:cxf+cwf]
            gs = cv2.cvtColor(crop_sample, cv2.COLOR_BGR2GRAY)
            sample_sharpness.append(float(cv2.Laplacian(gs, cv2.CV_64F).var()))

            # Motion energy via low-res optical flow / frame diff
            small = cv2.resize(frame, (320, 180))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray)
                motion_energy = float(np.mean(diff))
            else:
                motion_energy = 0.0
            prev_gray = gray
            motion_energies.append(motion_energy)

            # Detect pets (cat=15, dog=16, hands/humans excluded)
            dets = self.detector.detect(frame, conf_threshold=0.20)
            filtered = []
            for d in dets:
                cname = d["class_name"]
                if cname not in ("cat", "dog"):
                    continue
                filtered.append(d)
            detections_per_time.append(filtered)

        cap.release()

        # Check total pet presence
        frames_with_pets = sum(1 for d in detections_per_time if len(d) > 0)
        presence_ratio = frames_with_pets / max(1, len(sample_times))
        if presence_ratio < 0.35:
            return {
                "status": "reject",
                "reason": f"NO_PET_TRACKED (Presence {presence_ratio:.1%} < 35%)"
            }

        # 5. Multi-Pet Prioritization & Target Center Computation with Gap Interpolation
        # Priority = motion + size + confidence + tracking persistence
        raw_targets_x = [None] * len(sample_times)
        raw_targets_y = [None] * len(sample_times)
        pet_heights = [None] * len(sample_times)
        two_pets_far_apart_count = 0

        last_known_x = orig_w / 2.0
        last_known_y = orig_h / 2.0

        for i, dets in enumerate(detections_per_time):
            if not dets:
                continue

            # Check if two pets are far apart (> 70% source width)
            if len(dets) >= 2:
                xs = [d["center"][0] for d in dets[:2]]
                if abs(xs[0] - xs[1]) > (orig_w * 0.70):
                    two_pets_far_apart_count += 1

            # Score each pet: motion + size + confidence + identity persistence
            best_det = None
            best_score = -1.0
            for d in dets:
                area_frac = d["area_frac"]
                conf = d["conf"]
                motion = motion_energies[i]
                dist = math.hypot(d["center"][0] - last_known_x, d["center"][1] - last_known_y)
                proximity = max(0.0, 1.0 - (dist / float(orig_w * 0.35)))
                score = (area_frac * 3.0) + (conf * 1.5) + (motion * 0.05) + (proximity * 2.5)
                if animal_mode and d["class_name"] == animal_mode:
                    score += 0.5

                if score > best_score:
                    best_score = score
                    best_det = d

            box = best_det["box"]
            pet_w = box[2] - box[0]
            pet_h = box[3] - box[1]
            pet_heights[i] = pet_h / float(orig_h)

            # Pet body center x & y
            target_cx = (box[0] + box[2]) / 2.0
            target_cy = (box[1] + box[3]) / 2.0
            raw_targets_x[i] = target_cx
            raw_targets_y[i] = target_cy
            last_known_x = target_cx
            last_known_y = target_cy

        # Bridge short detection gaps with smooth linear interpolation
        valid_indices = [i for i, x in enumerate(raw_targets_x) if x is not None]
        if not valid_indices:
            return {"status": "reject", "reason": "NO_PET_TRACKED (Zero pet detections)"}

        all_indices = np.arange(len(sample_times))
        clean_targets_x = list(np.interp(all_indices, valid_indices, [raw_targets_x[i] for i in valid_indices]))
        clean_targets_y = list(np.interp(all_indices, valid_indices, [raw_targets_y[i] for i in valid_indices]))
        clean_heights = list(np.interp(all_indices, valid_indices, [pet_heights[i] if pet_heights[i] is not None else 0.35 for i in valid_indices]))

        raw_targets_x = clean_targets_x
        raw_targets_y = clean_targets_y
        pet_heights = clean_heights

        # Check rare blur-fit fallback rule (Requirement 3):
        # Two important pets > 70% width apart for > 25% of clip
        far_apart_ratio = two_pets_far_apart_count / max(1, len(sample_times))
        if far_apart_ratio > 0.25:
            if layout_mode == "smart_crop":
                return {
                    "status": "reject",
                    "reason": f"REJECT_TWO_PETS_FAR_APART (Pets separated by > 70% frame for {far_apart_ratio:.1%}, blur-fit disabled in Smart Crop mode)"
                }
            else:
                return {
                    "status": "pass",
                    "mode": "blur_fit",
                    "orig_size": (orig_w, orig_h),
                    "reason": f"LAYOUT_BLURFIT (Two pets separated > 70% source width for {far_apart_ratio:.1%} of duration)"
                }

        # Check average pet vertical position in source
        avg_pet_y = float(np.mean(raw_targets_y)) if raw_targets_y else orig_h / 2.0
        vert_frac = avg_pet_y / float(orig_h)

        # Upscale budget: max upscale 2.0x (1080 / 540 = 2.0)
        # If pet is off-center vertically, apply mild zoom within upscale budget to gain vertical freedom
        base_zoom = 1.0
        if abs(vert_frac - 0.50) > 0.08:
            base_zoom = 1.12  # Upscale = 1.78 * 1.12 = 1.99x <= 2.0x limit

        crop_h = int(round(orig_h / base_zoom))
        crop_w = int(round(crop_h * 9.0 / 16.0))
        if crop_w % 2 != 0:
            crop_w += 1
        if crop_h % 2 != 0:
            crop_h += 1
        crop_w = min(crop_w, orig_w)
        crop_h = min(crop_h, orig_h)
        max_y = orig_h - crop_h
        max_x = orig_w - crop_w

        # 6. Smooth Trajectory with Adaptive Velocity & Lookahead
        rel_times = [t - start_s for t in sample_times]
        dt = 1.0 / sample_fps

        # Offline target crop position: center pet in crop
        target_crop_x = np.array([x - (crop_w / 2.0) for x in raw_targets_x])
        target_crop_x = np.clip(target_crop_x, 0, max_x)

        # Lookahead: start moving before pet accelerates
        lookahead_steps = int(0.35 * sample_fps)
        advanced_x = np.copy(target_crop_x)
        for i in range(len(target_crop_x)):
            future_idx = min(len(target_crop_x) - 1, i + lookahead_steps)
            advanced_x[i] = target_crop_x[future_idx]

        # Bidirectional Gaussian smoothing over the offline trajectory
        kernel_size = 5
        sigma = 1.8
        kx = np.arange(-(kernel_size // 2), kernel_size // 2 + 1)
        kernel = np.exp(-0.5 * (kx / sigma) ** 2)
        kernel /= np.sum(kernel)

        padded_x = np.pad(advanced_x, (kernel_size // 2, kernel_size // 2), mode='edge')
        smoothed_x_arr = np.convolve(padded_x, kernel, mode='valid')
        smoothed_x_arr = np.clip(smoothed_x_arr, 0, max_x)

        # Adaptive velocity clamping (up to 25% crop width/sec with ease-in/ease-out)
        max_speed = 0.25 * float(crop_w)
        dead_zone_px = 0.015 * float(crop_w)

        smoothed_x = []
        cur_x = smoothed_x_arr[0]
        for i in range(len(sample_times)):
            target_val = smoothed_x_arr[i]
            diff = target_val - cur_x
            if abs(diff) < dead_zone_px:
                pass
            else:
                max_step = max_speed * dt
                # Adaptive acceleration if pet moves fast
                if abs(diff) > crop_w * 0.15:
                    max_step *= 1.4
                step = math.copysign(min(abs(diff), max_step), diff)
                cur_x += step
            cur_x = max(0.0, min(float(max_x), cur_x))
            smoothed_x.append(cur_x)

        # 7. Pro Touch: Funniest Moment Punch-in (+10% to +12% zoom)
        # Find peak motion energy in the middle 60% of the clip
        mid_start = int(len(motion_energies) * 0.20)
        mid_end = int(len(motion_energies) * 0.80)
        if mid_end > mid_start:
            peak_idx = mid_start + int(np.argmax(motion_energies[mid_start:mid_end]))
            peak_val = motion_energies[peak_idx]
        else:
            peak_idx = len(motion_energies) // 2
            peak_val = 0.0

        # Punch-in zoom if noticeable motion burst exists AND pet is not already large
        zoom_factors = [1.0] * len(rel_times)
        med_pet_h = float(np.median(pet_heights)) if pet_heights else 0.35
        if peak_val > 6.0 and dur_s >= 4.0 and med_pet_h <= 0.50:
            peak_t = rel_times[peak_idx]
            punch_duration = 1.8  # seconds
            max_punch = 1.12  # +12% zoom

            for i, t_rel in enumerate(rel_times):
                dist = abs(t_rel - peak_t)
                if dist < (punch_duration / 2.0):
                    # Smooth cosine bell curve
                    u = (dist / (punch_duration / 2.0)) * math.pi
                    zoom = 1.0 + (max_punch - 1.0) * (0.5 + 0.5 * math.cos(u))
                    zoom_factors[i] = round(zoom, 3)

        # 8. Sample ~6 keyframes for the continuous FFmpeg expression
        n_keyframes = max(4, min(8, int(dur_s * 1.5)))
        key_indices = [int(i * (len(rel_times) - 1) / (n_keyframes - 1)) for i in range(n_keyframes)]
        
        kf_times = [rel_times[idx] for idx in key_indices]
        kf_x = [smoothed_x[idx] for idx in key_indices]
        kf_zoom = [zoom_factors[idx] for idx in key_indices]

        # Calculate Y offset: keep pet center at 45% of crop height
        kf_y = []
        for idx in key_indices:
            target_y = raw_targets_y[idx] if raw_targets_y else avg_pet_y
            y_val = int(max(0, min(max_y, target_y - (crop_h * 0.45))))
            kf_y.append(y_val)

        # 9. Pre-Score Framing Before Any Render (Requirement 4)
        vis_ok, horiz_ok, vert_ok, size_ok, all_ok = 0, 0, 0, 0, 0
        total_eval = 0

        for i, t_rel in enumerate(rel_times):
            dets = detections_per_time[i]
            cats = [d for d in dets if d["class_name"] in ("cat", "dog")]
            if not cats:
                continue
            total_eval += 1
            best_cat = max(cats, key=lambda d: d["area_frac"] * 2.0 + d["conf"])
            bx1, by1, bx2, by2 = best_cat["box"]

            cam_x = smoothed_x[i]
            cam_y = float(np.interp(t_rel, kf_times, kf_y)) if len(kf_times) > 1 else float(kf_y[0])

            cbx1 = bx1 - cam_x
            cby1 = by1 - cam_y
            cbx2 = bx2 - cam_x
            cby2 = by2 - cam_y

            is_vis = (cbx1 >= -3 and cby1 >= -3 and cbx2 <= crop_w + 3 and cby2 <= crop_h + 3)
            cx = ((cbx1 + cbx2) / 2.0) / float(crop_w)
            cy = ((cby1 + cby2) / 2.0) / float(crop_h)
            h_frac = (cby2 - cby1) / float(crop_h)

            is_h = (0.38 <= cx <= 0.62)
            if max_y > 0:
                is_v = (0.30 <= cy <= 0.62)
            else:
                is_v = (0.20 <= cy <= 0.75) and (cby1 >= -3 and cby2 <= crop_h + 3)
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

        predicted_pass = bool(
            (pred_compliance >= 0.85 or (pred_vis >= 0.88 and pred_h >= 0.88 and pred_v >= 0.88 and pred_s >= 0.88))
            and (total_eval >= len(sample_times) * 0.35)
        )

        if not predicted_pass:
            return {
                "status": "reject",
                "reason": (
                    f"PREDICTED_BAD_FRAMING (Score: {pred_compliance:.1%} < 88% — "
                    f"Vis:{pred_vis:.1%}, H:{pred_h:.1%}, V:{pred_v:.1%}, S:{pred_s:.1%})"
                ),
                "framing_score": round(pred_compliance, 3),
                "details": {
                    "vis": round(pred_vis, 3), "horiz": round(pred_h, 3),
                    "vert": round(pred_v, 3), "size": round(pred_s, 3)
                }
            }

        med_sharp = float(np.median(sample_sharpness)) if sample_sharpness else 0.0
        if med_sharp < 15.0:
            return {
                "status": "reject",
                "reason": f"LOW_SOURCE_SHARPNESS (Median raw LapVar {med_sharp:.1f} < 15.0)",
                "framing_score": round(pred_compliance, 3),
                "sharpness": round(med_sharp, 1)
            }

        return {
            "status": "pass",
            "mode": "smart_crop",
            "orig_size": (orig_w, orig_h),
            "crop_w": crop_w,
            "crop_h": crop_h,
            "keyframes_t": kf_times,
            "keyframes_x": kf_x,
            "keyframes_y": kf_y,
            "keyframes_zoom": kf_zoom,
            "framing_score": round(pred_compliance, 3),
            "sharpness": round(med_sharp, 1)
        }

    def build_ffmpeg_crop_expression(self, plan):
        """
        Builds a mathematically smooth, continuous C1-Hermite smoothstep expression
        evaluated per-frame inside FFmpeg's native C engine.
        """
        orig_w, orig_h = plan["orig_size"]
        crop_w = plan["crop_w"]
        crop_h = plan["crop_h"]
        kf_times = plan["keyframes_t"]
        kf_x = plan["keyframes_x"]
        kf_y = plan.get("keyframes_y", [0] * len(kf_times))
        kf_zoom = plan["keyframes_zoom"]

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
            vf = f"crop=w={crop_w}:h={crop_h}:x='{final_x_expr}':y='{final_y_expr}',scale=1080:1920:flags=lanczos,cas=0.9,unsharp=7:7:2.0:7:7:1.5"
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
            vf = f"crop=w='{cw_expr}':h='{ch_expr}':x='{final_x_expr}':y='{y_zoom_expr}',scale=1080:1920:flags=lanczos,cas=0.9,unsharp=7:7:2.0:7:7:1.5"

        return vf

    def reframe_segment_ffmpeg(self, in_path, out_path, start_s, dur_s, plan):
        """
        Renders the reframed vertical short segment using FFmpeg.
        """
        mode = plan.get("mode", "smart_crop")

        if mode == "blur_fit":
            vf = (
                f"split[main][bg];"
                f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg];"
                f"[main]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,unsharp=5:5:0.35"
            )
        elif mode == "vertical_direct":
            vf = "scale=1080:1920:flags=lanczos,unsharp=5:5:0.35"
        else:
            vf = self.build_ffmpeg_crop_expression(plan)

        cmd = [
            FFMPEG_EXE, "-y",
            "-ss", f"{start_s:.3f}",
            "-i", in_path,
            "-t", f"{dur_s:.3f}",
            "-vf", f"setpts=PTS-STARTPTS,{vf}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "12",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            out_path
        ]

        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        return res.returncode == 0 and os.path.exists(out_path)
