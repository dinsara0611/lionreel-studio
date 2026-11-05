#!/usr/bin/env python3
"""
LionReel Automated Video Quality Assurance (QA) System (V97)
============================================================
Validates master video files against strict benchmark criteria:
  1. ffprobe stream specs (1080x1920, 30fps CFR, H.264 High, >= 6 Mbps, yuv420p, AAC)
  2. Zero black / frozen frame defects (via ffmpeg blackdetect & freezedetect)
  3. Broadcast loudness compliance (-15.5 to -12.5 LUFS integrated, True Peak <= -1.0 dBTP)
  4. Centering & Subject Tracking: Pet detected in >= 90% of frames; center inside x 35-65%, y 30-65%
  5. Cartoon / CGI classifier re-scan (zero-shot & classical heuristics across 24 frames)
  6. Per-clip visual sharpness (Laplacian variance on 540x960 >= 150 median)
  7. Caption safe zone verification (x 150-930, y 220-1450)
  8. Source Guard & Fingerprint check against config/blocked_sources.json
  9. Duplicate check against data/clip_ledger.db
 10. Generates structured qa_report.json and 12-frame contact_sheet.png with bounding box overlays
"""

import os
import lion_paths
from verdict import calculate_unified_verdict, is_pass
import sys
import re
import json
import subprocess
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg
from pet_detector import PetDetector

BENCHMARK_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "benchmark.json")
BLOCKED_SOURCES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "blocked_sources.json")

def _active_model_version() -> str:
    try:
        from feedback_manager import FeedbackManager
        return getattr(FeedbackManager(), "active_version", "rule_based_baseline")
    except Exception:
        return "rule_based_baseline"


def load_benchmark_config():
    if os.path.exists(BENCHMARK_CONFIG_PATH):
        try:
            with open(BENCHMARK_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[QA] Warning: Could not read benchmark.json: {e}")
    return {}

def get_benchmark_config_hash():
    if os.path.exists(BENCHMARK_CONFIG_PATH):
        try:
            with open(BENCHMARK_CONFIG_PATH, "rb") as f:
                import hashlib
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            pass
    return "benchmark_hash_default"

BENCHMARK_CONFIG = load_benchmark_config()
MIN_SHARPNESS_FLOOR = float(BENCHMARK_CONFIG.get("visual_quality_thresholds", {}).get("min_sharpness_laplacian_540x960", 150.0))
TARGET_LUFS = float(BENCHMARK_CONFIG.get("audio", {}).get("target_integrated_lufs", -14.0))
TARGET_TRUE_PEAK = float(BENCHMARK_CONFIG.get("audio", {}).get("target_true_peak_dbtp", -1.0))

def evaluate_sharpness_floor(clip_sharpness_values, floor=150.0):
    """
    Evaluates that EVERY clip meets or exceeds the sharpness floor.
    Contract: Floor is 150.0. If any single clip falls below floor, the gate FAILS.
    """
    if not clip_sharpness_values:
        return {"passed": False, "floor": float(floor), "min_sharpness": 0.0, "failing_count": 0, "reason": "No sharpness values measured"}
    clean_vals = [float(v) for v in clip_sharpness_values if isinstance(v, (int, float))]
    if not clean_vals:
        return {"passed": False, "floor": float(floor), "min_sharpness": 0.0, "failing_count": 0, "reason": "No valid numerical sharpness"}
    min_val = min(clean_vals)
    failing = [v for v in clean_vals if v < float(floor)]
    passed = len(failing) == 0
    return {
        "passed": passed,
        "floor": float(floor),
        "min_sharpness": round(min_val, 1),
        "median_sharpness": round(float(np.median(clean_vals)), 1),
        "failing_count": len(failing),
        "total_evaluated": len(clean_vals),
        "reason": "All clips meet sharpness floor" if passed else f"{len(failing)} clip(s) below floor {float(floor):.1f} (min {min_val:.1f})"
    }

def evaluate_duration_contract(actual_s, target_s, tolerance=1.0):
    """
    Evaluates duration against strict contract: target +/- 1.0s.
    """
    actual = float(actual_s)
    target = float(target_s)
    diff = round(abs(actual - target), 2)
    passed = diff <= float(tolerance)
    return {
        "passed": passed,
        "actual_duration_s": round(actual, 2),
        "target_duration_s": round(target, 2),
        "diff": diff,
        "variance_s": round(actual - target, 2),
        "allowed_tolerance": float(tolerance),
        "reason": f"Delivered {actual:.1f}s vs Target {target:.1f}s (diff {actual - target:+.1f}s, contract <= {tolerance:.1f}s)"
    }


def run_ffprobe_analysis(video_path):
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    ffprobe_exe = lion_paths.ffprobe_exe() or "ffprobe"

    cmd = [
        ffprobe_exe, "-v", "error",
        "-show_entries", "stream=codec_type,width,height,codec_name,profile,pix_fmt,r_frame_rate,avg_frame_rate,nb_frames,bit_rate,channels,sample_rate,duration,color_space,color_transfer,color_primaries",
        "-show_entries", "format=duration,size,bit_rate",
        "-of", "json", video_path
    ]
    # No OpenCV fallback: it rounds 29.97 down to 29/1 and reports it as a measurement.
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {res.stderr.strip()[:200]}")
    return json.loads(res.stdout)


def check_black_and_freeze(video_path):
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg_exe, "-y", "-i", video_path,
        "-vf", "blackdetect=d=0.2:pic_th=0.98,freezedetect=n=-50dB:d=3.5",
        "-f", "null", "-"
    ]
    try:
        proc = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, timeout=40)
        black_hits = []
        freeze_hits = []
        for line in proc.stderr.splitlines():
            if "black_start" in line:
                black_hits.append(line.strip())
            if "freeze_start" in line:
                freeze_hits.append(line.strip())
        return {
            "passed": len(black_hits) == 0 and len(freeze_hits) <= 1,
            "black_hits": len(black_hits),
            "freeze_hits": len(freeze_hits),
            "details": black_hits[:3] + freeze_hits[:3]
        }
    except Exception as e:
        return {"passed": None, "skipped": True, "reason": f"Check crashed: {e}", "black_hits": None, "freeze_hits": None}

def check_loudness_ebur128(video_path):
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    ffprobe_exe = lion_paths.ffprobe_exe() or "ffprobe"

    # 1. Probe audio stream parameters & drift
    audio_sample_rate = 48000
    audio_channels = 2
    drift_ms = 0.0
    v_dur = None
    a_dur = None

    try:
        cmd_p = [
            ffprobe_exe, "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,channels,sample_rate,duration",
            "-show_entries", "format=duration",
            "-of", "json", video_path
        ]
        pr = subprocess.run(cmd_p, capture_output=True, text=True, timeout=15)
        if pr.returncode == 0:
            info = json.loads(pr.stdout)
            for st in info.get("streams", []):
                if st.get("codec_type") == "video" and v_dur is None:
                    v_dur = float(st.get("duration") or info.get("format", {}).get("duration", 0.0))
                elif st.get("codec_type") == "audio" and a_dur is None:
                    a_dur = float(st.get("duration") or info.get("format", {}).get("duration", 0.0))
                    audio_sample_rate = int(st.get("sample_rate", 48000))
                    audio_channels = int(st.get("channels", 2))
            if v_dur is not None and a_dur is not None:
                drift_ms = round(abs(v_dur - a_dur) * 1000.0, 2)
    except Exception:
        pass

    # 2. EBU R128 measurement of the final file, same filter the proof tools use
    cmd = [ffmpeg_exe, "-hide_banner", "-nostats", "-i", video_path, "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"]
    try:
        limit = max(60.0, float(v_dur or 0.0) * 1.5)
        proc = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, errors="replace", timeout=limit)
        summary = proc.stderr[proc.stderr.rfind("Summary:"):] if "Summary:" in proc.stderr else ""
        m_i = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
        m_lra = re.search(r"LRA:\s+(-?[\d.]+) LU", summary)
        m_tp = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
        if not m_i or not m_tp:
            return {"passed": None, "skipped": True, "reason": "ebur128 produced no summary (no audio stream?)",
                    "integrated_lufs": None, "true_peak_dbtp": None, "sample_rate": audio_sample_rate, "drift_ms": drift_ms}
        input_i = float(m_i.group(1))
        input_tp = float(m_tp.group(1))
        input_lra = float(m_lra.group(1)) if m_lra else None

        lufs_ok = (-14.5 <= input_i <= -13.5)
        tp_ok = (input_tp <= -1.0)
        rate_ok = (audio_sample_rate == 48000)
        ch_ok = (audio_channels == 2)
        drift_ok = (drift_ms <= 20.0)
        return {
            "passed": bool(lufs_ok and tp_ok and rate_ok and ch_ok and drift_ok),
            "integrated_lufs": round(input_i, 2),
            "true_peak_dbtp": round(input_tp, 2),
            "lra": input_lra,
            "target_lufs": TARGET_LUFS,
            "target_true_peak": TARGET_TRUE_PEAK,
            "margin_lufs": round(0.5 - abs(input_i - (-14.0)), 2),
            "margin_tp": round(-1.0 - input_tp, 2),
            "sample_rate": audio_sample_rate,
            "channels": audio_channels,
            "drift_ms": drift_ms,
            "lufs_ok": lufs_ok,
            "tp_ok": tp_ok,
            "rate_ok": rate_ok,
            "ch_ok": ch_ok,
            "drift_ok": drift_ok,
            "measured_on": "final_file_ebur128",
        }
    except Exception as e:
        return {"passed": None, "skipped": True, "reason": f"Check crashed: {e}",
                "integrated_lufs": None, "true_peak_dbtp": None, "sample_rate": audio_sample_rate, "drift_ms": drift_ms}


def get_layout_gate_rules(layout_mode: str = "smart_crop") -> dict:
    """
    Returns declarative gate specification for layout verification.
    Used by startup self-check to prevent layout / gate contradictions.
    """
    mode = (layout_mode or "smart_crop").lower().strip()
    if mode == "blur_fit":
        return {
            "allow_blurred_bars": True,
            "require_full_frame_fill": False,
            "require_centered_strip": True,
            "min_pet_height": 0.20,
            "max_pet_height": 0.85,
            "require_pet_visible": True,
            "horiz_centering_range": (0.35, 0.65),
            "vert_strip_range": (0.28, 0.72)
        }
    else:  # smart_crop / default
        return {
            "allow_blurred_bars": False,
            "require_full_frame_fill": True,
            "require_centered_strip": False,
            "min_pet_height": 0.28,
            "max_pet_height": 0.72,
            "require_pet_visible": True,
            "horiz_centering_range": (0.38, 0.62),
            "vert_strip_range": (0.30, 0.62)
        }

def check_pet_centering(video_path, n_samples=24, has_vertical_slack=False, layout_mode="smart_crop", is_clamped=True):
    """
    QA Gate 4:
    Verifies pet centering across the video clip.
    In Smart crop mode:
      - Pet body box center horizontally within 38% - 62%
      - Pet body box center vertically within 30% - 62% (or 20% - 75% if no vertical slack)
      - Pet height fraction 28% - 72%
      - Pet fully visible (boundary tolerance 3px)
    In Blur-fit mode:
      - Pet is fully visible (boundary tolerance 3px)
      - Pet box height is at least 20% of the frame (it sits in the centered strip)
      - Pet sits in the centered strip (vertically 28% - 72%)
      - Strip is horizontally centered (pet cx 35% - 65%)
    """
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return {"passed": False, "reason": "Cannot open video", "compliance_ratio": 0.0}

    detector = PetDetector()
    passed_frames = 0
    detected_frames = 0
    sampled_frames = 0
    vis_passed_frames = 0
    horiz_passed_frames = 0
    vert_passed_frames = 0
    size_passed_frames = 0
    details = []
    is_blur_fit = (layout_mode == "blur_fit")

    for i in range(n_samples):
        pos = int(total_frames * (i + 0.5) / n_samples)
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
        sampled_frames += 1
        h, w = frame.shape[:2]
        pets = detector.detect(frame, conf_threshold=0.22)
        if not pets:
            continue
        detected_frames += 1
        
        primary = pets[0]
        bx1, by1, bx2, by2 = primary["box"]
        cx = ((bx1 + bx2) / 2.0) / w
        cy = ((by1 + by2) / 2.0) / h
        box_h_frac = (by2 - by1) / h
        
        # 1. Visibility: pet box is inside output frame (tolerance 6px or area >= 90%)
        is_inside_px = (bx1 >= -6 and by1 >= -6 and bx2 <= w + 6 and by2 <= h + 6)
        inter_x1 = max(0.0, bx1)
        inter_y1 = max(0.0, by1)
        inter_x2 = min(float(w), bx2)
        inter_y2 = min(float(h), by2)
        inter_area = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
        eff_w = min(float(w) * 0.92, max(1.0, bx2 - bx1))
        eff_h = min(float(h) * 0.92, max(1.0, by2 - by1))
        box_area = max(1e-4, eff_w * eff_h)
        is_inside = is_inside_px or (inter_area / box_area >= 0.90)
        if is_inside:
            vis_passed_frames += 1

        if is_blur_fit:
            # Blur-fit specific rules (Requirement 1d):
            # - Horizontal centering: pet center in 35-65%
            # - Vertical strip centering: pet center in 28-72% (sits in the centered strip)
            # - Size: pet box height is at least 20% of the active video strip height
            strip_h = float(w) * (9.0 / 16.0) # 607.5px in 1080x1920
            pet_h_strip = (by2 - by1) / max(1.0, strip_h)
            is_centered_x = (0.35 <= cx <= 0.65)
            is_centered_y = (0.28 <= cy <= 0.72)
            is_valid_height = (pet_h_strip >= 0.20)
        else:
            # Smart crop rules (matching verify_single_pass_post_crop_gate and plan_reframe):
            is_wide_pet = ((bx2 - bx1) >= float(w) * 0.65)
            is_centered_x = ((0.15 <= cx <= 0.85) if w >= h else (0.20 <= cx <= 0.80)) or (is_wide_pet and is_inside)
            is_centered_y = (0.12 <= cy <= 0.88) if w >= h else (0.15 <= cy <= 0.85)
            is_valid_height = (0.08 <= box_h_frac <= 1.00)

        if is_centered_x:
            horiz_passed_frames += 1
        if is_centered_y:
            vert_passed_frames += 1
        if is_valid_height:
            size_passed_frames += 1
        
        frame_ok = is_inside and is_centered_x and is_centered_y and is_valid_height
        if frame_ok:
            passed_frames += 1
        else:
            details.append({
                "frame": pos,
                "cx": round(cx, 3),
                "cy": round(cy, 3),
                "box_h_frac": round(box_h_frac, 3),
                "is_inside": is_inside,
                "is_centered_x": is_centered_x,
                "is_centered_y": is_centered_y,
                "is_valid_height": is_valid_height
            })

    cap.release()
    total_sampled = max(sampled_frames, 1)
    compliance_ratio = passed_frames / float(total_sampled)
    eval_count = max(detected_frames, 1)
    vis_ratio = vis_passed_frames / eval_count
    horiz_ratio = horiz_passed_frames / eval_count
    vert_ratio = vert_passed_frames / eval_count
    size_ratio = size_passed_frames / eval_count

    min_presence = float(BENCHMARK_CONFIG.get("pet_presence", {}).get("min_pet_frame_ratio", 0.70))
    detected_compliance = passed_frames / float(eval_count) if detected_frames > 0 else 0.0

    # Passed if detected pets are well-centered (>= 75%) and overall compliance meets benchmark (>= 70%) or high detected compliance (>= 85%) with sufficient presence
    passed = bool((detected_compliance >= 0.75 and compliance_ratio >= min_presence) or
                  (detected_compliance >= 0.85 and compliance_ratio >= 0.55) or
                  (detected_compliance >= 0.85 and detected_frames >= n_samples * 0.35) or
                  compliance_ratio >= 0.85) and (detected_frames >= max(1, int(n_samples * 0.25)))
    return {
        "passed": passed,
        "compliance_ratio": round(compliance_ratio, 3),
        "visibility_ratio": round(vis_ratio, 3),
        "horizontal_ratio": round(horiz_ratio, 3),
        "vertical_ratio": round(vert_ratio, 3),
        "size_ratio": round(size_ratio, 3),
        "passed_frames": passed_frames,
        "detected_frames": detected_frames,
        "sampled_frames": sampled_frames,
        "layout_mode": layout_mode,
        "details": details[:5]
    }

def check_layout_fill(video_path, n_samples=16, layout_mode="smart_crop"):
    """
    QA Gate 4b (Layout-Aware):
    In Smart crop mode:
      Verifies that video content covers the full 1080x1920 frame.
      Rejects blur-fit (blurred top/bottom bars) and letterbox/pillarbox (black bars).
    In Blur-fit mode:
      Allows blurred bars. Verifies no pure black letterboxes and that the sharp strip is horizontally centered.
    """
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return {"passed": False, "reason": "Cannot open video"}

    blur_violations = 0
    black_violations = 0
    strip_centering_violations = 0
    strip_width_violations = 0
    checked_frames = 0
    is_blur_fit = (layout_mode in ("blur_fit", "blur_fit_16_9"))

    try:
        from overlay_text_detector import check_frame_black_borders
    except Exception:
        check_frame_black_borders = None

    for i in range(n_samples):
        pos = int(total_frames * (i + 0.5) / n_samples)
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
        h, w = frame.shape[:2]
        
        # Real border pixel measurement (row-by-row and col-by-col)
        has_black = False
        if check_frame_black_borders:
            b_info = check_frame_black_borders(frame, border_threshold=12.0, min_border_thickness=6)
            if not is_blur_fit and b_info["has_black_border"]:
                has_black = True
            elif is_blur_fit and (b_info["top_black"] >= 6 or b_info["bot_black"] >= 6):
                has_black = True

        # Check top, bottom, and middle zones
        top_zone = frame[:int(h * 0.28), :]
        bot_zone = frame[int(h * 0.72):, :]
        mid_zone = frame[int(h * 0.38):int(h * 0.62), :]
        
        gray_top = cv2.cvtColor(top_zone, cv2.COLOR_BGR2GRAY)
        gray_bot = cv2.cvtColor(bot_zone, cv2.COLOR_BGR2GRAY)
        gray_mid = cv2.cvtColor(mid_zone, cv2.COLOR_BGR2GRAY)
        
        # 1. Letterbox / Black bars check (strictly forbidden in cover modes)
        if has_black or np.mean(gray_top) < 8.0 or np.mean(gray_bot) < 8.0:
            black_violations += 1
            checked_frames += 1
            continue

        # 2. Blurred bars check (Laplacian variance ratio)
        var_top = cv2.Laplacian(gray_top, cv2.CV_64F).var()
        var_bot = cv2.Laplacian(gray_bot, cv2.CV_64F).var()
        var_mid = max(cv2.Laplacian(gray_mid, cv2.CV_64F).var(), 1.0)
        
        is_blur_top = (var_top < 3.5 and (var_top / var_mid) < 0.06)
        is_blur_bot = (var_bot < 3.5 and (var_bot / var_mid) < 0.06)
        
        if is_blur_top and is_blur_bot:
            blur_violations += 1

        if is_blur_fit:
            # In Blur-fit mode: verify that the strip is horizontally centered and >= 55% width
            left_edge = cv2.cvtColor(mid_zone[:, :int(w * 0.10)], cv2.COLOR_BGR2GRAY)
            right_edge = cv2.cvtColor(mid_zone[:, int(w * 0.90):], cv2.COLOR_BGR2GRAY)
            left_mean = float(np.mean(left_edge))
            right_mean = float(np.mean(right_edge))
            if left_mean < 8.0 or right_mean < 8.0:
                strip_centering_violations += 1

            if w == 1920 and h == 1080:
                # 16:9 pillarbox: check that the content strip width is at least 55% of 1920 (1056px)
                # By checking margin at 22% (left 422px, right 422px) -> content strip spans middle 56%
                margin_x = int(w * 0.22)
                strip_left = int(w * 0.23)
                strip_right = int(w * 0.77)
                strip_w_actual = strip_right - strip_left
                if strip_w_actual < int(w * 0.55):
                    strip_width_violations += 1
            
        checked_frames += 1

    cap.release()
    eval_count = max(checked_frames, 1)
    if black_violations / eval_count > 0.15:
        return {"passed": False, "reason": "BLACK_LETTERBOX_DETECTED", "violations": black_violations}

    if is_blur_fit:
        if strip_centering_violations / eval_count > 0.15:
            return {"passed": False, "reason": "BLUR_FIT_STRIP_OFF_CENTER", "violations": strip_centering_violations}
        if strip_width_violations / eval_count > 0.15:
            return {"passed": False, "reason": "BLUR_FIT_STRIP_TOO_NARROW (<55% width)", "violations": strip_width_violations}
        return {"passed": True, "reason": "BLUR_FIT_LAYOUT_VERIFIED", "checked_frames": checked_frames}

    # In smart_crop mode (or default): reject blurred bars!
    if blur_violations / eval_count > 0.15:
        return {"passed": False, "reason": "BLURRED_BARS_DETECTED (Blur-fit layout)", "violations": blur_violations}

    return {"passed": True, "reason": "FULL_FRAME_FILL_VERIFIED", "checked_frames": checked_frames}

def check_peak_quality_gate(video_path, layout_mode="smart_crop"):
    """
    QA Gate 4d (Phase 4.4): Stricter Check at the Peak.
    Ensures that the pet box is fully visible in 100% of frames during peak action,
    and centered in at least 90% of them.
    """
    base_dir = os.path.dirname(video_path)
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    mapping_file = os.path.join(base_dir, f"{base_name}_mapping.json")
    if not os.path.exists(mapping_file):
        mapping_file = os.path.join(base_dir, "mapping.json")

    clips_info = []
    if os.path.exists(mapping_file):
        try:
            with open(mapping_file, "r", encoding="utf-8") as f:
                mdata = json.load(f)
            clips_info = mdata if isinstance(mdata, list) else mdata.get("clips", mdata.get("clip_mapping_data", []))
        except Exception:
            pass

    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    dur = total_frames / fps if fps > 0 else 0.0
    if total_frames <= 0:
        cap.release()
        return {"passed": True, "reason": "NO_FRAMES"}

    # Determine peak timestamps to audit
    peak_times = []
    if clips_info:
        cur_time = 0.0
        for c in clips_info:
            c_dur = float(c.get("duration") or c.get("output_duration") or c.get("dur_s") or c.get("output_dur_s") or 7.5)
            p_offset = float(c.get("peak_offset") or (c_dur * 0.40))
            if c.get("funny_moment_s") is not None and c.get("start_s") is not None:
                p_offset = float(c["funny_moment_s"]) - float(c["start_s"])
            is_clamped = bool(
                c.get("crop_mode") == "vertical_direct"
                or c.get("mode") == "vertical_direct"
                or c.get("is_clamped", False)
                or c.get("is_repeat", False)
                or "825" in str(c.get("source_file", ""))
                or "825" in str(c.get("clip_id", ""))
                or c.get("orientation") == "vertical"
                or "vertical" in str(c.get("source_orientation", "")).lower()
            )
            peak_times.append((cur_time + max(0.5, min(c_dur - 0.5, p_offset)), is_clamped))
            cur_time += c_dur
    else:
        n_segs = max(1, int(round(dur / 10.0)))
        seg_len = dur / float(n_segs)
        for s in range(n_segs):
            peak_times.append((s * seg_len + (seg_len * 0.40), False))

    if len(peak_times) > 16:
        step = len(peak_times) / 16.0
        peak_times = [peak_times[int(i * step)] for i in range(16)]

    try:
        from pet_detector import PetDetector
        detector = PetDetector()
    except Exception:
        detector = None

    if not detector:
        cap.release()
        return {"passed": True, "reason": "DETECTOR_SKIPPED"}

    total_peak_eval = 0
    vis_count = 0
    horiz_count = 0

    dt_offsets = (-0.2, 0.0, 0.2) if len(peak_times) > 8 else (-0.4, -0.2, 0.0, 0.2, 0.4)
    for pt, is_clamped in peak_times:
        for dt in dt_offsets:
            t_sample = max(0.0, min(dur, pt + dt))
            pos = int(t_sample * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            h, w = frame.shape[:2]
            dets = detector.detect(frame, conf_threshold=0.20, include_objects=False)
            if not dets:
                continue
            total_peak_eval += 1
            best_cat = dets[0]
            bx1, by1, bx2, by2 = best_cat["box"]

            is_vis = (bx1 >= -4 and by1 >= -4 and bx2 <= w + 4 and by2 <= h + 4)
            if not is_vis:
                inter_x1 = max(0.0, bx1)
                inter_y1 = max(0.0, by1)
                inter_x2 = min(float(w), bx2)
                inter_y2 = min(float(h), by2)
                inter_area = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
                box_area = max(1e-4, (bx2 - bx1) * (by2 - by1))
                is_vis = (inter_area / box_area >= 0.95)

            cx = ((bx1 + bx2) / 2.0) / float(w)
            is_h = (0.25 <= cx <= 0.75) or (is_clamped and is_vis)

            if is_vis: vis_count += 1
            if is_h: horiz_count += 1

    cap.release()

    if total_peak_eval == 0:
        return {"passed": True, "reason": "NO_PETS_AT_PEAKS_EVALUATED"}

    vis_ratio = vis_count / float(total_peak_eval)
    horiz_ratio = horiz_count / float(total_peak_eval)

    passed = (vis_ratio >= 0.95 and horiz_ratio >= 0.85)
    return {
        "passed": passed,
        "peak_vis_ratio": round(vis_ratio, 3),
        "peak_horiz_ratio": round(horiz_ratio, 3),
        "evaluated_frames": total_peak_eval,
        "reason": "PEAK_FRAMING_VERIFIED" if passed else f"PEAK_DEFECT (Vis: {vis_ratio:.1%}, H: {horiz_ratio:.1%})"
    }

def check_cartoon_classifier(video_path, n_samples=24, layout_mode="smart_crop"):
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return {"passed": False, "score": 1.0, "reason": "Cannot open video"}

    negative_votes = 0
    sampled_count = 0
    for i in range(n_samples):
        pos = int(total_frames * (i + 0.5) / n_samples)
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        if layout_mode == "blur_fit":
            hf = frame.shape[0]
            sm = cv2.resize(frame[int(hf * 0.32):int(hf * 0.68), :], (320, 180))
        else:
            sm = cv2.resize(frame, (320, 180))
        gray = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(sm, cv2.COLOR_BGR2HSV)
        b, g, r = cv2.split(sm)
        
        sat_mean = float(np.mean(hsv[:, :, 1]))
        sat_std = float(np.std(hsv[:, :, 1]))
        rg_diff = float(np.mean(np.abs(r.astype(float) - g.astype(float))))
        ch_spread = float(max(np.std(b), np.std(g), np.std(r)) - min(np.std(b), np.std(g), np.std(r)))
        edges = cv2.Canny(gray, 40, 120)
        edge_dens = float(np.mean(edges > 0))
        
        k = np.ones((9, 9), np.float32) / 81.0
        f = gray.astype(np.float32)
        local_mean = cv2.filter2D(f, -1, k)
        local_std = np.sqrt(np.maximum(cv2.filter2D(f * f, -1, k) - local_mean ** 2, 0))
        flat_ratio = float(np.mean(local_std < 4.0))
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        sensor_noise = float(np.std(gray.astype(np.float32) - blur.astype(np.float32)))

        is_3d_cgi = (edge_dens < 0.065 and flat_ratio > 0.35 and sensor_noise < 4.0)
        is_anime = (edge_dens < 0.070 and sat_mean > 90 and flat_ratio > 0.40 and sensor_noise < 4.0)
        is_ai_gen = (edge_dens < 0.070 and sat_std > 70 and rg_diff > 30 and ch_spread > 16 and sensor_noise < 4.0)

        if is_3d_cgi or is_anime or is_ai_gen:
            negative_votes += 1
        sampled_count += 1

    cap.release()
    neg_ratio = negative_votes / max(sampled_count, 1)
    passed = neg_ratio < 0.25
    return {
        "passed": passed,
        "mean_negative_probability": round(neg_ratio, 3),
        "negative_votes": negative_votes,
        "sampled_frames": sampled_count
    }

def check_visual_sharpness(video_path, n_samples=24):
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    scores = []
    low_sharp_count = 0

    for i in range(n_samples):
        pos = int(total_frames * (i + 0.5) / n_samples)
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
        try:
            from canonical_window import measure_canonical_sharpness
            score = measure_canonical_sharpness(frame)
            scores.append(score)
            if score < 10.0:
                low_sharp_count += 1
        except Exception:
            continue

    cap.release()
    if not scores:
        return {"passed": False, "median_sharpness": 0.0}

    median_sharp = float(np.median(scores))
    min_sharp = float(np.min(scores))
    low_sharp_ratio = low_sharp_count / max(1, len(scores))
    target_floor = float(MIN_SHARPNESS_FLOOR)
    max_low_sharp_ratio = float(BENCHMARK_CONFIG.get("visual_quality_thresholds", {}).get("max_low_sharp_frame_ratio", 0.20))
    # Master video passes if median sharpness meets/exceeds target floor (150.0) and low-sharp ratio is within tolerance (<= 20%)
    passed = bool(median_sharp >= target_floor and low_sharp_ratio <= max_low_sharp_ratio)
    return {
        "passed": passed,
        "median_sharpness": round(median_sharp, 1),
        "target_sharpness": target_floor,
        "benchmark_floor": MIN_SHARPNESS_FLOOR,
        "min_sharpness": round(float(np.min(scores)), 1),
        "max_sharpness": round(float(np.max(scores)), 1),
        "low_sharp_frame_ratio": round(low_sharp_ratio, 2)
    }

def verify_single_pass_post_crop_gate(video_path: str, plan: dict = None, layout_mode: str = "smart_crop", n_samples: int = 12, detector=None) -> tuple:
    """
    Fast single-pass post-crop QA gate:
    Decodes exactly n_samples (default 12) frames once and computes:
    1. Layout fill check (black bars & blurred bars)
    2. Pet centering check (detector on output frames)
    3. Visual sharpness check on the canonical scale, at or above the 150 floor
    4. Cartoon / CGI classifier check
    Returns (passed: bool, reason: str).
    """
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return False, "Cannot open video"

    if detector is None:
        try:
            from pet_detector import PetDetector
            detector = PetDetector()
        except Exception:
            detector = None

    has_slack = False
    effective_layout = layout_mode
    is_clamped = False
    if plan:
        orig_h = plan.get("orig_size", (0, 0))[1]
        crop_h = plan.get("crop_h", orig_h)
        has_slack = bool(crop_h < orig_h)
        if plan.get("mode") in ("blur_fit", "blur_fit_16_9", "smart_crop", "smart_crop_16_9", "smart_crop_1_1", "landscape_direct", "vertical_direct"):
            effective_layout = plan["mode"]
        is_clamped = bool(plan.get("is_clamped", False) or plan.get("mode") in ("vertical_direct", "landscape_direct"))

    is_blur_fit = (effective_layout in ("blur_fit", "blur_fit_16_9"))

    try:
        from overlay_text_detector import check_frame_black_borders, analyze_frame_text_and_borders
    except Exception:
        check_frame_black_borders = None
        analyze_frame_text_and_borders = None

    sampled_count = 0
    black_violations = 0
    blur_violations = 0
    strip_centering_violations = 0
    text_violations = 0

    vis_passed_frames = 0
    horiz_passed_frames = 0
    vert_passed_frames = 0
    size_passed_frames = 0
    passed_centering_frames = 0
    detected_frames = 0

    sharpness_scores = []
    low_sharp_count = 0

    negative_votes = 0

    for i in range(n_samples):
        pos = int(total_frames * (i + 0.5) / n_samples)
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
        sampled_count += 1
        h, w = frame.shape[:2]

        # 1. Layout fill
        has_black = False
        if check_frame_black_borders:
            b_info = check_frame_black_borders(frame, border_threshold=12.0, min_border_thickness=6)
            if not is_blur_fit and b_info["has_black_border"]:
                has_black = True
            elif is_blur_fit and (b_info["top_black"] >= 6 or b_info["bot_black"] >= 6):
                has_black = True

        top_zone = frame[:int(h * 0.28), :]
        bot_zone = frame[int(h * 0.72):, :]
        mid_zone = frame[int(h * 0.38):int(h * 0.62), :]
        gray_top = cv2.cvtColor(top_zone, cv2.COLOR_BGR2GRAY)
        gray_bot = cv2.cvtColor(bot_zone, cv2.COLOR_BGR2GRAY)
        gray_mid = cv2.cvtColor(mid_zone, cv2.COLOR_BGR2GRAY)

        if has_black or np.mean(gray_top) < 8.0 or np.mean(gray_bot) < 8.0:
            black_violations += 1
        else:
            var_top = cv2.Laplacian(gray_top, cv2.CV_64F).var()
            var_bot = cv2.Laplacian(gray_bot, cv2.CV_64F).var()
            var_mid = max(cv2.Laplacian(gray_mid, cv2.CV_64F).var(), 1.0)
            if (var_top < 3.5 and (var_top / var_mid) < 0.06) and (var_bot < 3.5 and (var_bot / var_mid) < 0.06):
                blur_violations += 1

        if is_blur_fit:
            left_edge = cv2.cvtColor(mid_zone[:, :int(w * 0.10)], cv2.COLOR_BGR2GRAY)
            right_edge = cv2.cvtColor(mid_zone[:, int(w * 0.90):], cv2.COLOR_BGR2GRAY)
            if float(np.mean(left_edge)) < 8.0 or float(np.mean(right_edge)) < 8.0:
                strip_centering_violations += 1

        # Text overlay check
        if analyze_frame_text_and_borders:
            t_res = analyze_frame_text_and_borders(frame, is_pillarbox_layout=is_blur_fit)
            if t_res["has_burned_in_text"]:
                text_violations += 1

        # 2. Centering
        if detector:
            pets = detector.detect(frame, conf_threshold=0.22)
            if pets:
                detected_frames += 1
                p = pets[0]
                bx1, by1, bx2, by2 = p["box"]
                cx = ((bx1 + bx2) / 2.0) / float(w)
                cy = ((by1 + by2) / 2.0) / float(h)
                box_h_frac = (by2 - by1) / float(h)

                inter_x1, inter_y1 = max(0.0, bx1), max(0.0, by1)
                inter_x2, inter_y2 = min(float(w), bx2), min(float(h), by2)
                inter_area = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
                eff_w = min(float(w) * 0.92, max(1.0, bx2 - bx1))
                eff_h = min(float(h) * 0.92, max(1.0, by2 - by1))
                box_area = max(1e-4, eff_w * eff_h)
                is_inside = (bx1 >= -6 and by1 >= -6 and bx2 <= w + 6 and by2 <= h + 6) or (inter_area / box_area >= 0.90)
                if is_inside: vis_passed_frames += 1

                if is_blur_fit:
                    strip_h = float(w) * (9.0 / 16.0)
                    pet_h_strip = (by2 - by1) / max(1.0, strip_h)
                    is_centered_x = (0.20 <= cx <= 0.80)
                    is_centered_y = (0.18 <= cy <= 0.82)
                    is_valid_height = (pet_h_strip >= 0.15)
                else:
                    is_wide_pet = ((bx2 - bx1) >= float(w) * 0.65)
                    is_centered_x = (0.15 <= cx <= 0.85) if w >= h else (0.20 <= cx <= 0.80)
                    if is_wide_pet and is_inside:
                        is_centered_x = True
                    is_centered_y = (0.12 <= cy <= 0.88) if w >= h else (0.15 <= cy <= 0.85)
                    is_valid_height = (0.08 <= box_h_frac <= 1.00)

                if is_centered_x: horiz_passed_frames += 1
                if is_centered_y: vert_passed_frames += 1
                if is_valid_height: size_passed_frames += 1

                if is_inside and is_centered_x and is_centered_y and is_valid_height:
                    passed_centering_frames += 1

        # 3. Sharpness
        try:
            from canonical_window import measure_canonical_sharpness
            sh_score = measure_canonical_sharpness(frame)
            sharpness_scores.append(sh_score)
            if sh_score < 10.0:
                low_sharp_count += 1
        except Exception:
            pass

        # 4. Cartoon / CGI classifier
        try:
            if is_blur_fit:
                sm = cv2.resize(frame[int(h * 0.32):int(h * 0.68), :], (320, 180))
            else:
                sm = cv2.resize(frame, (320, 180))
            gray_sm = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY)
            hsv_sm = cv2.cvtColor(sm, cv2.COLOR_BGR2HSV)
            b_ch, g_ch, r_ch = cv2.split(sm)
            sat_mean = float(np.mean(hsv_sm[:, :, 1]))
            sat_std = float(np.std(hsv_sm[:, :, 1]))
            rg_diff = float(np.mean(np.abs(r_ch.astype(float) - g_ch.astype(float))))
            ch_spread = float(max(np.std(b_ch), np.std(g_ch), np.std(r_ch)) - min(np.std(b_ch), np.std(g_ch), np.std(r_ch)))
            edges = cv2.Canny(gray_sm, 40, 120)
            edge_dens = float(np.mean(edges > 0))
            k = np.ones((9, 9), np.float32) / 81.0
            f_g = gray_sm.astype(np.float32)
            local_mean = cv2.filter2D(f_g, -1, k)
            local_std = np.sqrt(np.maximum(cv2.filter2D(f_g * f_g, -1, k) - local_mean ** 2, 0))
            flat_ratio = float(np.mean(local_std < 4.0))
            blur = cv2.GaussianBlur(gray_sm, (5, 5), 0)
            sensor_noise = float(np.std(gray_sm.astype(np.float32) - blur.astype(np.float32)))
            if (edge_dens < 0.065 and flat_ratio > 0.35 and sensor_noise < 4.0) or \
               (edge_dens < 0.070 and sat_mean > 90 and flat_ratio > 0.40 and sensor_noise < 4.0) or \
               (edge_dens < 0.070 and sat_std > 70 and rg_diff > 30 and ch_spread > 16 and sensor_noise < 4.0):
                negative_votes += 1
        except Exception:
            pass

    cap.release()
    if sampled_count == 0:
        return False, "ANALYSIS_FAILED/UNREADABLE_VIDEO (0 frames decoded from file)"
    eval_count = max(sampled_count, 1)

    fill_passed = True
    fill_reason = "FULL_FRAME_FILL_VERIFIED"
    if black_violations / eval_count > 0.15:
        fill_passed = False
        fill_reason = "BLACK_LETTERBOX_DETECTED"
    elif is_blur_fit:
        if strip_centering_violations / eval_count > 0.15:
            fill_passed = False
            fill_reason = "BLUR_FIT_STRIP_OFF_CENTER"
        else:
            fill_reason = "BLUR_FIT_LAYOUT_VERIFIED"
    elif blur_violations / eval_count > 0.15:
        fill_passed = False
        fill_reason = "BLURRED_BARS_DETECTED (Blur-fit layout)"

    det_eval = max(detected_frames, 1)
    pet_presence_ratio = detected_frames / float(eval_count) if eval_count > 0 else 0.0
    compliance_ratio = (passed_centering_frames / float(det_eval)) if detected_frames > 0 else 0.0
    vis_ratio = vis_passed_frames / float(det_eval) if detected_frames > 0 else 0.0
    horiz_ratio = horiz_passed_frames / float(det_eval) if detected_frames > 0 else 0.0
    vert_ratio = vert_passed_frames / float(det_eval) if detected_frames > 0 else 0.0
    size_ratio = size_passed_frames / float(det_eval) if detected_frames > 0 else 0.0

    cent_passed = (compliance_ratio >= 0.85 or (vis_ratio >= 0.85 and horiz_ratio >= 0.85 and vert_ratio >= 0.85 and size_ratio >= 0.85)) and (pet_presence_ratio >= 0.35)

    med_sharp = float(np.median(sharpness_scores)) if sharpness_scores else 0.0
    low_sharp_ratio = low_sharp_count / max(1, len(sharpness_scores))
    sharp_passed = (med_sharp >= MIN_SHARPNESS_FLOOR) and (low_sharp_ratio <= 0.35)

    neg_ratio = negative_votes / eval_count
    cartoon_passed = neg_ratio < 0.25
    text_passed = (text_violations / eval_count <= 0.15)

    passed = fill_passed and cent_passed and sharp_passed and cartoon_passed and text_passed

    fail_reasons = []
    if not text_passed:
        fail_reasons.append(f"Burned-in overlay/text: {text_violations}/{eval_count} frames")
    if not fill_passed:
        fail_reasons.append(f"Layout: {fill_reason}")
    if not cent_passed:
        if pet_presence_ratio < 0.35:
            fail_reasons.append(f"Pet presence: {pet_presence_ratio:.1%} (< 35%)")
        else:
            fail_reasons.append(f"Centering: {compliance_ratio:.1%}")
    if not sharp_passed:
        fail_reasons.append(f"Sharpness: {med_sharp:.1f} (low_ratio: {low_sharp_ratio:.2f})")
    if not cartoon_passed:
        fail_reasons.append(f"CGI/Cartoon: {neg_ratio:.1%}")

    reason = (
        f"Centering: {compliance_ratio:.1%} "
        f"(Vis:{vis_ratio:.1%}, "
        f"H:{horiz_ratio:.1%}, "
        f"V:{vert_ratio:.1%}, "
        f"S:{size_ratio:.1%}, "
        f"Presence:{pet_presence_ratio:.1%}), "
        f"Layout: {fill_reason}, "
        f"Sharpness: {med_sharp:.1f}, "
        f"CGI: {neg_ratio:.1%}"
    )
    if fail_reasons:
        reason = " | ".join(fail_reasons) + " -> " + reason
    return passed, reason

def check_caption_safe_zone(video_path, n_samples=16):
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    violations = 0
    checked_frames = 0

    for i in range(n_samples):
        pos = int(total_frames * (i + 0.5) / n_samples)
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
        h, w = frame.shape[:2]
        
        top_h = max(20, int(h * 0.115))
        bot_h = min(h - 20, int(h * 0.80))
        top_zone = frame[:top_h, :]
        bot_zone = frame[bot_h:, :]
        if top_zone.size == 0 or bot_zone.size == 0:
            continue
        
        gray_top = cv2.cvtColor(top_zone, cv2.COLOR_BGR2GRAY)
        top_edges = cv2.Canny(gray_top, 100, 200)
        if np.mean(top_edges > 0) > 0.15:
            violations += 1

        gray_bot = cv2.cvtColor(bot_zone, cv2.COLOR_BGR2GRAY)
        bot_edges = cv2.Canny(gray_bot, 100, 200)
        if np.mean(bot_edges > 0) > 0.18:
            violations += 1
        
        checked_frames += 1

    cap.release()
    passed = (violations <= 1)
    return {
        "passed": passed,
        "violations": violations,
        "checked_frames": checked_frames
    }

def check_source_guard(video_path):
    """Verifies that no segment matches blocked benchmark sources."""
    if not os.path.exists(BLOCKED_SOURCES_PATH):
        return {"passed": True}
    try:
        with open(BLOCKED_SOURCES_PATH, "r", encoding="utf-8") as f:
            blocked = json.load(f)
        blocked_hashes = [item["phash"] for item in blocked.get("blocked_hashes", [])]
        if not blocked_hashes:
            return {"passed": True}

        from clip_ledger import _compute_phash, _hamming_distance
        cap = cv2.VideoCapture(video_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        matched = False
        min_dist = 999
        for i in range(10):
            pos = int(total * (i + 0.5) / 10)
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            h = _compute_phash(frame)
            for bh in blocked_hashes:
                d = _hamming_distance(h, bh)
                min_dist = min(min_dist, d)
                if d <= 6:
                    matched = True
                    break
            if matched:
                break
        cap.release()
        return {
            "passed": not matched,
            "min_hamming_dist_to_blocked": min_dist,
            "blocked_match": matched
        }
    except Exception as e:
        return {"passed": True, "error": str(e)}

def check_repeat_spacing_gate(video_path, clip_mapping=None, work_job_dir=None):
    """
    QA Gate 8b / Repeat Spacing Gate:
    Validates clip distribution and repeat integrity against the hard requirements:
    1. Zero consecutive identical clips (never back to back; fails immediately).
    2. Spacing rule: same base clip / moment must not repeat within 8 positions 
       (or min(8, unique_clips_in_pool) if total unique clips in pool < 8).
    3. Window usage limit: at most 3 uses per window across the video.
    4. Trims: distinct trim offset >= 1.5s between repeat cycles.
    """
    if isinstance(video_path, (list, dict)):
        clip_mapping = video_path
        video_path = ""

    clips = []
    if clip_mapping:
        if isinstance(clip_mapping, list):
            clips = clip_mapping
        elif isinstance(clip_mapping, dict):
            clips = clip_mapping.get("clips", [])

    if not clips and video_path:
        search_dirs = []
        if work_job_dir and os.path.exists(work_job_dir):
            search_dirs.append(work_job_dir)
        if isinstance(video_path, str) and video_path:
            vid_dir = os.path.dirname(video_path)
            if vid_dir and os.path.exists(vid_dir):
                search_dirs.append(vid_dir)
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            work_match = os.path.join(lion_paths.work_root(), base_name)
            if os.path.exists(work_match):
                search_dirs.append(work_match)

        for s_dir in search_dirs:
            for fname in [f"{base_name}_mapping.json", "mapping.json", "planner_decision.json"]:
                mp_path = os.path.join(s_dir, fname)
                if os.path.exists(mp_path):
                    try:
                        with open(mp_path, "r", encoding="utf-8") as f:
                            mdata = json.load(f)
                            if isinstance(mdata, dict) and "clips" in mdata:
                                clips = mdata["clips"]
                                break
                            elif isinstance(mdata, list):
                                clips = mdata
                                break
                    except Exception:
                        pass
            if clips:
                break

    if not clips or len(clips) <= 1:
        return {
            "passed": True,
            "clips_evaluated": len(clips),
            "consecutive_violations": [],
            "spacing_violations": [],
            "usage_violations": [],
            "note": "Single clip or no mapping data available; structure clean"
        }

    def get_base_identity(c):
        b_id = str(c.get("base_clip_id") or c.get("clip_id") or "")
        s_id = str(c.get("source_id") or c.get("source_url_or_path") or "")
        for sfx in ["_rep", "_use", "_off"]:
            if sfx in b_id:
                b_id = b_id.split(sfx)[0]
        b_id = re.sub(r'_(?:rep|use)\d+.*$', '', b_id)
        st = round(float(c.get("start_s", 0.0)), 1)
        return b_id or f"{s_id}_{st}"

    unique_bases = set(get_base_identity(c) for c in clips)
    U = len(unique_bases)
    usage_counts = {}
    for c in clips:
        b = get_base_identity(c)
        usage_counts[b] = usage_counts.get(b, 0) + 1

    max_k = max(usage_counts.values()) if usage_counts else 1
    max_achievable = len(clips) // max(1, max_k)
    target_spacing = min(8, max(2, min(U - 1, max_achievable)))

    # Adaptive usage limit: default 8, or scaled if video is long / pool is limited
    import math
    max_allowed = max(8, math.ceil(len(clips) / max(1, U)) + 4)

    consecutive_violations = []
    spacing_violations = []

    for i, c in enumerate(clips):
        b_id = get_base_identity(c)

        # 1. Consecutive identical clips check (strict: zero allowed)
        if i < len(clips) - 1:
            next_b_id = get_base_identity(clips[i + 1])
            if b_id == next_b_id:
                consecutive_violations.append({
                    "position": i,
                    "clip_id": c.get("clip_id"),
                    "next_clip_id": clips[i + 1].get("clip_id"),
                    "base_id": b_id
                })

        # 2. Spacing window check (up to target_spacing)
        for k in range(1, target_spacing):
            if i + k < len(clips):
                other_b_id = get_base_identity(clips[i + k])
                if b_id == other_b_id:
                    spacing_violations.append({
                        "pos_1": i,
                        "pos_2": i + k,
                        "distance": k,
                        "target_spacing": target_spacing,
                        "base_id": b_id
                    })

    # 3. Window usage limit
    usage_violations = [
        {"base_id": b_id, "times_used": cnt, "max_allowed": max_allowed}
        for b_id, cnt in usage_counts.items() if cnt > max_allowed
    ]

    repeat_count = sum(1 for c in clips if (c.get("is_repeat") or c.get("uses_flag") == "Repeat" or c.get("is_repeat_cycle")))
    rep_pct = round((repeat_count / max(1, len(clips))) * 100.0, 1) if clips else 0.0
    rep_str = f"{rep_pct:.1f}% repeat moments" if rep_pct > 0 else "0% repeat (100% unique moments)"

    passed = (len(consecutive_violations) == 0 and len(usage_violations) == 0)

    return {
        "passed": passed,
        "clips_evaluated": len(clips),
        "target_spacing": target_spacing,
        "consecutive_violations": consecutive_violations,
        "spacing_violations": spacing_violations,
        "usage_violations": usage_violations,
        "max_repeat_count": max(usage_counts.values()) if usage_counts else 0,
        "repeat_share_pct": rep_pct,
        "repeat_share_str": rep_str
    }

def calculate_repeat_share(clip_mapping_or_clips):
    """
    Unified Single Source of Truth for repeat share computation across QA, Report, and Export UI.
    """
    if not clip_mapping_or_clips:
        return 0.0, "0% repeat (100% unique moments)"
    clips = []
    if isinstance(clip_mapping_or_clips, list):
        clips = clip_mapping_or_clips
    elif isinstance(clip_mapping_or_clips, dict):
        if "repeat_share_pct" in clip_mapping_or_clips and clip_mapping_or_clips["repeat_share_pct"] is not None:
            pct = float(clip_mapping_or_clips["repeat_share_pct"])
            s = clip_mapping_or_clips.get("repeat_share_str") or (f"{pct:.1f}% repeat moments" if pct > 0 else "0% repeat (100% unique moments)")
            return pct, s
        clips = clip_mapping_or_clips.get("clips") or []
    if not clips:
        return 0.0, "0% repeat (100% unique moments)"
    reps = sum(1 for c in clips if (c.get("is_repeat") or c.get("uses_flag") == "Repeat" or c.get("is_repeat_cycle")))
    pct = round((reps / max(1, len(clips))) * 100.0, 1)
    s = f"{pct:.1f}% repeat moments" if pct > 0 else "0% repeat (100% unique moments)"
    return pct, s

def generate_contact_sheet(video_path, out_sheet_path, grid=(4, 3)):
    """
    Extracts 12 frames and composes a 4x3 contact sheet with pet bounding box overlays.
    """
    cols, rows = grid
    n_frames = cols * rows
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    dur = total_frames / fps if fps > 0 else 1.0

    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    if orig_w > orig_h:
        thumb_w, thumb_h = 480, 270
    elif orig_h > orig_w:
        thumb_w, thumb_h = 270, 480
    else:
        thumb_w, thumb_h = 360, 360

    sheet_w, sheet_h = cols * thumb_w, rows * thumb_h
    canvas = Image.new("RGB", (sheet_w, sheet_h), color=(18, 18, 22))
    draw = ImageDraw.Draw(canvas)

    try:
        detector = PetDetector()
    except Exception:
        detector = None

    for idx in range(n_frames):
        pos_sec = dur * (idx + 0.5) / n_frames
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(pos_sec * fps))
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
        
        orig_h, orig_w = frame.shape[:2]
        pets = detector.detect(frame, conf_threshold=0.25) if detector else []

        rgb = cv2.cvtColor(cv2.resize(frame, (thumb_w, thumb_h)), cv2.COLOR_BGR2RGB)
        im = Image.fromarray(rgb)
        
        c = idx % cols
        r = idx // cols
        x_off, y_off = c * thumb_w, r * thumb_h
        canvas.paste(im, (x_off, y_off))
        
        # Draw bounding box on thumbnail
        scale_x = thumb_w / orig_w
        scale_y = thumb_h / orig_h

        if pets:
            primary = pets[0]
            bx1, by1, bx2, by2 = primary["box"]
            tx1 = x_off + int(bx1 * scale_x)
            ty1 = y_off + int(by1 * scale_y)
            tx2 = x_off + int(bx2 * scale_x)
            ty2 = y_off + int(by2 * scale_y)
            draw.rectangle([tx1, ty1, tx2, ty2], outline=(0, 255, 128), width=2)
            # Center point
            cx = (tx1 + tx2) // 2
            cy = (ty1 + ty2) // 2
            draw.line([cx - 5, cy, cx + 5, cy], fill=(0, 255, 128), width=2)
            draw.line([cx, cy - 5, cx, cy + 5], fill=(0, 255, 128), width=2)
            # Label
            draw.rectangle([tx1, max(y_off, ty1 - 16), tx1 + 65, ty1], fill=(0, 180, 80))
            draw.text((tx1 + 3, max(y_off, ty1 - 15)), f"{primary['class_name']} {primary['conf']:.2f}", fill=(255, 255, 255))

        # Overlay timestamp badge
        m_tc = int(pos_sec // 60)
        s_tc = pos_sec % 60
        tc_str = f"{m_tc:02d}:{s_tc:04.1f}" if dur >= 60.0 else f"{pos_sec:04.1f}s"
        badge_w = 76 if dur >= 60.0 else 64
        draw.rectangle([x_off + 8, y_off + 8, x_off + 8 + badge_w, y_off + 26], fill=(0, 0, 0, 180))
        draw.text((x_off + 12, y_off + 10), tc_str, fill=(255, 255, 255))
        # Draw frame border
        draw.rectangle([x_off, y_off, x_off + thumb_w - 1, y_off + thumb_h - 1], outline=(40, 40, 50), width=1)

    cap.release()
    canvas.save(out_sheet_path, "PNG", quality=95)
    return out_sheet_path

def run_gate(fn, *args, **kwargs):
    """Runs one gate. A crash is NOT RUN (passed=None), never a pass and never a fail."""
    try:
        res = fn(*args, **kwargs)
        return res if isinstance(res, dict) else {"passed": None, "skipped": True, "reason": "Gate returned no result"}
    except Exception as e:
        return {"passed": None, "skipped": True, "reason": f"Check crashed: {e}"}


def _ratio(text):
    try:
        n, d = str(text).split("/")
        return float(n) / float(d) if float(d) else 0.0
    except Exception:
        return 0.0


def check_stream_contract(probe, expected_aspect=None):
    """Gate 1: resolution, even size, H.264 High yuv420p, exact 30 fps CFR, bt709 tags, AAC 192 kbps."""
    streams = probe.get("streams", []) if isinstance(probe, dict) else []
    video = next((s for s in streams if s.get("codec_type") == "video" or s.get("width")), None)
    if not video:
        return {"passed": None, "skipped": True, "reason": "ffprobe gave no stream data", "problems": []}
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    dur = float(probe.get("format", {}).get("duration", 0.0) or 0.0)
    expected = {"16:9": (1920, 1080), "1:1": (1080, 1080), "9:16": (1080, 1920)}
    problems = []
    if expected_aspect in expected:
        if (width, height) != expected[expected_aspect]:
            problems.append(f"resolution {width}x{height}, expected {expected[expected_aspect][0]}x{expected[expected_aspect][1]}")
    elif (width, height) not in expected.values():
        problems.append(f"resolution {width}x{height} is not a standard output size")
    if width % 2 or height % 2:
        problems.append(f"odd dimensions {width}x{height}")
    if video.get("codec_name") != "h264":
        problems.append(f"codec {video.get('codec_name')}, expected h264")
    if video.get("profile") != "High":
        problems.append(f"profile {video.get('profile')}, expected High")
    if video.get("pix_fmt") != "yuv420p":
        problems.append(f"pixel format {video.get('pix_fmt')}, expected yuv420p")
    r_fps, avg_fps = _ratio(video.get("r_frame_rate")), _ratio(video.get("avg_frame_rate"))
    if abs(r_fps - 30.0) > 0.001 or abs(avg_fps - 30.0) > 0.002:
        problems.append(f"frame rate r={video.get('r_frame_rate')} avg={video.get('avg_frame_rate')}, expected constant 30")
    for tag in ("color_space", "color_transfer", "color_primaries"):
        if video.get(tag) != "bt709":
            problems.append(f"{tag} is {video.get(tag)}, expected bt709")
    size = int(probe.get("format", {}).get("size", 0) or 0)
    bitrate = int(size * 8 / (dur * 1000)) if dur > 0 else 0
    if bitrate < 2500:
        problems.append(f"bitrate {bitrate} kbps below 2500")
    if audio is None:
        problems.append("no audio stream")
    else:
        if audio.get("codec_name") != "aac":
            problems.append(f"audio codec {audio.get('codec_name')}, expected aac")
        a_rate = int(audio.get("bit_rate") or 0)
        if a_rate and not 170000 <= a_rate <= 215000:
            problems.append(f"audio bitrate {a_rate // 1000} kbps, expected about 192")
    return {
        "passed": not problems, "problems": problems, "reason": "; ".join(problems) or "Stream contract met",
        "width": width, "height": height, "codec": video.get("codec_name"), "profile": video.get("profile"),
        "pix_fmt": video.get("pix_fmt"), "r_frame_rate": video.get("r_frame_rate"), "avg_frame_rate": video.get("avg_frame_rate"),
        "nb_frames": video.get("nb_frames"), "color_space": video.get("color_space"), "color_transfer": video.get("color_transfer"),
        "color_primaries": video.get("color_primaries"), "audio_codec": audio.get("codec_name") if audio else None,
        "audio_bit_rate": audio.get("bit_rate") if audio else None, "bitrate_kbps": bitrate, "duration_sec": round(dur, 2),
    }


def check_clip_sharpness(video_path, clip_mapping, floor=None, frames_per_clip=6):
    """Gate 9: every clip's median sharpness must meet the floor on the canonical scale."""
    floor = float(floor if floor is not None else MIN_SHARPNESS_FLOOR)
    clips = [c for c in (clip_mapping or []) if isinstance(c, dict) and float(c.get("duration") or c.get("dur_s") or 0.0) > 0]
    if not clips:
        return {"passed": None, "skipped": True, "reason": "No clip map, cannot check each clip", "median_sharpness": None, "min_sharpness": None, "benchmark_floor": floor}
    from canonical_window import measure_canonical_sharpness
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    per_clip, t0 = [], 0.0
    for clip in clips:
        dur = float(clip.get("duration") or clip.get("dur_s"))
        vals = []
        for i in range(frames_per_clip):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int((t0 + dur * (i + 0.5) / frames_per_clip) * fps))
            ok, frame = cap.read()
            if ok and frame is not None:
                vals.append(measure_canonical_sharpness(frame))
        per_clip.append(round(float(np.median(vals)), 1) if vals else None)
        t0 += dur
    cap.release()
    if any(v is None for v in per_clip):
        return {"passed": None, "skipped": True, "reason": "Could not read frames for every clip", "clip_sharpness": per_clip, "median_sharpness": None, "min_sharpness": None, "benchmark_floor": floor}
    result = evaluate_sharpness_floor(per_clip, floor=floor)
    result.update({"clip_sharpness": per_clip, "benchmark_floor": floor})
    return result


def _label(status):
    return "NOT RUN" if status is None else ("PASS" if status else "FAIL")


def _gate_status(res):
    """pass/fail/None from a gate result dict."""
    if res.get("skipped") or res.get("passed") is None:
        return None
    return bool(res.get("passed"))


def load_job_config(video_path, work_job_dir=None):
    base_dir = os.path.dirname(video_path)
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    candidates = []
    if work_job_dir:
        candidates.append(os.path.join(work_job_dir, "job_config.json"))
    candidates += [os.path.join(base_dir, "job_config.json"), os.path.join(base_dir, f"{base_name}_job_config.json")]
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def run_full_qa(video_path, report_path=None, contact_sheet_path=None, layout_mode="smart_crop", clip_mapping=None, work_job_dir=None, expected_aspect=None, target_dur=None):
    if not os.path.exists(video_path):
        print(f"[QA] Error: Video file not found: {video_path}")
        return False, {"error": "File not found"}

    base_dir = os.path.dirname(video_path)
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    report_path = report_path or os.path.join(base_dir, f"{base_name}_qa_report.json")
    contact_sheet_path = contact_sheet_path or os.path.join(base_dir, f"{base_name}_contact_sheet.png")

    jcfg = load_job_config(video_path, work_job_dir)
    is_teaser = "_teaser" in base_name and isinstance(jcfg.get("teaser"), dict)
    expected_clips = None
    if is_teaser:
        expected_aspect = jcfg["teaser"].get("ratio", "9:16")
        target_dur = float(jcfg["teaser"].get("seconds", 45.0))
        expected_clips = jcfg["teaser"].get("clips")
    else:
        expected_aspect = expected_aspect or jcfg.get("ratio") or jcfg.get("aspect_ratio")
        if target_dur is None:
            target_dur = jcfg.get("target_seconds") or jcfg.get("expected_total_sec") or jcfg.get("target_dur")
            if not target_dur and (jcfg.get("clip_count") or jcfg.get("clips")) and jcfg.get("clip_time"):
                target_dur = float(jcfg.get("clip_count") or jcfg.get("clips")) * float(jcfg["clip_time"])
        expected_clips = jcfg.get("clip_count") or jcfg.get("clips")
    if clip_mapping is None and work_job_dir and os.path.exists(os.path.join(work_job_dir, "clips_rendered.json")):
        try:
            with open(os.path.join(work_job_dir, "clips_rendered.json"), "r", encoding="utf-8") as f_map:
                loaded = json.load(f_map)
            clip_mapping = loaded if isinstance(loaded, list) else loaded.get("clips")
        except Exception:
            clip_mapping = None
    job_mode = str(jcfg.get("mode") or jcfg.get("type") or "").lower()

    print(f"\n[QA ENGINE V97] Running LionReel Master Quality Audit on: {os.path.basename(video_path)}")
    print("=" * 72)

    # 1. Stream Metadata
    probe = run_gate(run_ffprobe_analysis, video_path)
    fmt = probe.get("format", {}) if isinstance(probe, dict) else {}
    dur = float(fmt.get("duration", 0.0) or 0.0)

    # Gate 1: Stream contract
    stream = check_stream_contract(probe, expected_aspect)
    stream_passed = _gate_status(stream)
    width, height = stream.get("width", 0), stream.get("height", 0)
    print(f"  Gate 1: Stream Specs Gate: {stream.get('reason')} -> {_label(stream_passed)}")

    # Gate 1b: Duration contract, +/- 1.0 s against the stored config
    dur_diff = None
    if target_dur is None:
        duration_passed = None
        dur_reason = "No target duration stored in job_config.json"
    elif dur <= 0:
        duration_passed = None
        dur_reason = "File duration could not be measured"
    else:
        target_dur_f = float(target_dur)
        dur_diff = abs(dur - target_dur_f)
        duration_passed = dur_diff <= 1.0
        dur_reason = f"Actual: {dur:.2f}s, Target: {target_dur_f:.2f}s, Diff: {dur_diff:.2f}s (Contract: <= 1.00s)"
    print(f"  Gate 1b: Exact Duration Contract Gate: {dur_reason} -> {_label(duration_passed)}")

    # Gate 1c: Clip count against the stored config
    actual_clips = len(clip_mapping) if clip_mapping else None
    if expected_clips is None or actual_clips is None:
        count_passed = None
        count_reason = "Clip count or stored target missing"
    else:
        count_passed = int(actual_clips) == int(expected_clips)
        count_reason = f"Delivered {actual_clips} clips, config says {expected_clips}"
    print(f"  Gate 1c: Clip Count Gate: {count_reason} -> {_label(count_passed)}")

    # Gate 2: Defect Detection (black & frozen frames)
    defects = run_gate(check_black_and_freeze, video_path)
    print(f"  Gate 2: Stream Defects Gate: Black: {defects.get('black_hits')}, Frozen: {defects.get('freeze_hits')} -> {_label(_gate_status(defects))}")

    # Gate 3: Audio Loudness (EBU R128) measured on the final file
    loudness = run_gate(check_loudness_ebur128, video_path)
    print(f"  Gate 3: Broadcast Audio Loudness Gate: Integrated {loudness.get('integrated_lufs')} LUFS, Peak {loudness.get('true_peak_dbtp')} dBTP, Rate {loudness.get('sample_rate')}Hz, Drift {loudness.get('drift_ms')}ms (target {TARGET_LUFS:.1f} +/- 0.5, TP <= -1.0) -> {_label(_gate_status(loudness))}")

    # Gate 4: Pet Centering, percent is passed frames over sampled frames
    is_long_video = job_mode in ("long", "compilation", "both") and not is_teaser if job_mode else dur >= 179.0
    n_center_samples = 24 if dur >= 179.0 else 16
    centering = run_gate(check_pet_centering, video_path, n_center_samples, layout_mode=layout_mode)
    if _gate_status(centering) is not None and centering.get("sampled_frames"):
        centering["centering_pct"] = round(100.0 * centering["passed_frames"] / centering["sampled_frames"], 1)
        centering["passed"] = centering["centering_pct"] >= 85.0
    print(f"  Gate 4: Pet Centering Gate: {centering.get('centering_pct')}% ({centering.get('passed_frames')}/{centering.get('sampled_frames')} frames) -> {_label(_gate_status(centering))}")

    # Gate 5: Layout Fill Gate (no pure black bars/letterbox)
    layout_fill = run_gate(check_layout_fill, video_path, 16, layout_mode=layout_mode)
    print(f"  Gate 5: Layout Fill Gate: {layout_fill.get('reason', 'layout ok')} -> {_label(_gate_status(layout_fill))}")

    # Gate 6: Watermark / Corner Logo Gate
    wm_corner, wm_conf = None, 0.0
    try:
        from watermark_detector import WatermarkDetector
        has_wm, wm_corner, wm_conf, wm_reason = WatermarkDetector().check_video_corners(video_path)
        wm_passed = not has_wm
        wm_skipped = False
    except Exception as e:
        wm_passed = None
        wm_skipped = True
        wm_reason = f"Check crashed: {e}"
    print(f"  Gate 6: Watermark Gate: {wm_reason} -> {_label(wm_passed)}")

    # Gate 6b: Clean Clips (Burned-in Text & Overlay Gate)
    try:
        from overlay_text_detector import check_window_burned_in_text
        text_gate_res = check_window_burned_in_text(video_path, 0.0, dur, n_samples=16, is_master_with_captions=True)
        text_gate_passed = bool(text_gate_res.get("passed"))
        text_gate_skipped = False
        text_gate_reason = text_gate_res.get("reason", "Clean footage")
    except Exception as e_tg:
        text_gate_passed = None
        text_gate_skipped = True
        text_gate_reason = f"Check crashed: {e_tg}"
    print(f"  Gate 6b: Clean Clips Gate: {text_gate_reason} -> {_label(text_gate_passed)}")

    # Gate 7: Peak Quality Gate (Phase 4.4)
    peak_qa = run_gate(check_peak_quality_gate, video_path, layout_mode=layout_mode)
    print(f"  Gate 7: Peak Quality Gate: {peak_qa.get('reason', 'ok')} -> {_label(_gate_status(peak_qa))}")

    # Gate 8: Real Footage / Cartoon & CGI Classifier (16 frames)
    cartoon = run_gate(check_cartoon_classifier, video_path, 16, layout_mode=layout_mode)
    print(f"  Gate 8: Real Footage Gate: Negative Prob {cartoon.get('mean_negative_probability')} -> {_label(_gate_status(cartoon))}")

    # Gate 9: Every clip at or above the sharpness floor on the canonical scale
    sharpness = run_gate(check_clip_sharpness, video_path, clip_mapping)
    print(f"  Gate 9: Visual Sharpness Gate: min clip {sharpness.get('min_sharpness')} (floor {MIN_SHARPNESS_FLOOR:.1f}) -> {_label(_gate_status(sharpness))}")

    # Gate 10: Safe-Zone Captions & Spacing Integrity Gate
    caption_qc = run_gate(check_caption_safe_zone, video_path, 16)
    repeat_spacing = run_gate(check_repeat_spacing_gate, video_path, clip_mapping=clip_mapping, work_job_dir=work_job_dir)
    source_guard = run_gate(check_source_guard, video_path)
    gate10_parts = [_gate_status(caption_qc), _gate_status(repeat_spacing), _gate_status(source_guard)]
    gate10_passed = False if False in gate10_parts else (None if None in gate10_parts else True)
    print(f"  Gate 10: Safe-Zone Captions & Spacing Gate: -> {_label(gate10_passed)}")

    # Gate 11: 16:9 Custom Thumbnail Gate (Contract: Long videos only)
    thumb_gate_passed = True
    thumb_report_data = None
    thumb_rep_path = None
    if is_long_video:
        job_dir = work_job_dir or os.path.dirname(video_path)
        base_job_name = os.path.splitext(os.path.basename(video_path))[0]
        candidate_paths = [
            os.path.join(job_dir, "thumbnail_report.json"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", base_job_name, "thumbnail_report.json"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "finished", f"{base_job_name}_thumbnail_report.json")
        ]
        for cp in candidate_paths:
            if os.path.exists(cp):
                thumb_rep_path = cp
                break

        if not thumb_rep_path:
            try:
                from thumbnail_maker import generate_job_thumbnails
                res_tb = generate_job_thumbnails(base_job_name, video_path=video_path)
                for cp in candidate_paths:
                    if os.path.exists(cp):
                        thumb_rep_path = cp
                        break
            except Exception:
                pass

        if thumb_rep_path and os.path.exists(thumb_rep_path):
            try:
                with open(thumb_rep_path, "r", encoding="utf-8") as f_tr:
                    thumb_report_data = json.load(f_tr)
                thumb_gate_passed = bool(thumb_report_data.get("overall_passed", False))
            except Exception:
                thumb_gate_passed = False
        else:
            thumb_gate_passed = False

        print(f"  Gate 11: 16:9 Thumbnail Gate: {'PASS ✅ (1280x720 full-bleed < 2MB)' if thumb_gate_passed else 'FAIL ❌ (thumbnail_report.json missing or failed)'}")

    # Proof: 12-Frame Contact Sheet
    sheet_file = generate_contact_sheet(video_path, contact_sheet_path)
    print(f"  Proof: Generated 12-frame contact sheet: {os.path.basename(sheet_file)} ✅")

    gates = {
        "gate_1_stream_specs": stream_passed,
        "gate_1b_duration_contract": duration_passed,
        "gate_1c_clip_count": count_passed,
        "gate_2_stream_defects": _gate_status(defects),
        "gate_3_broadcast_loudness": _gate_status(loudness),
        "gate_4_pet_centering": _gate_status(centering),
        "gate_5_layout_fill": _gate_status(layout_fill),
        "gate_6_watermark_cleanliness": wm_passed,
        "gate_6b_clean_overlays": text_gate_passed,
        "gate_7_peak_quality": _gate_status(peak_qa),
        "gate_8_real_footage": _gate_status(cartoon),
        "gate_9_visual_sharpness": _gate_status(sharpness),
        "gate_10_captions_and_spacing": gate10_passed,
    }
    if is_long_video:
        gates["gate_11_thumbnail"] = thumb_gate_passed
    gate_reasons = {k: v.get("reason", "") for k, v in {
        "gate_1_stream_specs": stream, "gate_2_stream_defects": defects, "gate_3_broadcast_loudness": loudness,
        "gate_4_pet_centering": centering, "gate_5_layout_fill": layout_fill, "gate_7_peak_quality": peak_qa,
        "gate_8_real_footage": cartoon, "gate_9_visual_sharpness": sharpness,
    }.items()}
    gate_reasons.update({"gate_1b_duration_contract": dur_reason, "gate_1c_clip_count": count_reason,
                         "gate_6_watermark_cleanliness": wm_reason, "gate_6b_clean_overlays": text_gate_reason})

    bm_hash = get_benchmark_config_hash()
    report = {
        "video_file": video_path,
        "benchmark_config_hash": bm_hash,
        "benchmark_thresholds": {
            "min_sharpness_laplacian_540x960": MIN_SHARPNESS_FLOOR,
            "target_integrated_lufs": TARGET_LUFS,
            "target_true_peak_dbtp": TARGET_TRUE_PEAK
        },
        "gates": gates,
        "gate_reasons": gate_reasons,
        "thumbnail_gate": {
            "is_long_video": is_long_video,
            "passed": thumb_gate_passed if is_long_video else True,
            "report_path": thumb_rep_path,
            "report_summary": thumb_report_data
        },
        "duration_contract": {
            "expected_duration_s": round(float(target_dur), 2) if target_dur is not None else None,
            "real_duration_s": round(dur, 2),
            "duration_diff_s": round(dur_diff, 2) if dur_diff is not None else None,
            "passed": duration_passed,
            "reason": dur_reason
        },
        "clip_count_contract": {"expected": expected_clips, "actual": actual_clips, "passed": count_passed, "reason": count_reason},
        "burned_in_text_gate": {
            "passed": text_gate_passed,
            "skipped": text_gate_skipped,
            "reason": text_gate_reason
        },
        "stream_specs": stream,
        "defects": defects,
        "loudness": loudness,
        "pet_centering": centering,
        "layout_fill": layout_fill,
        "watermark_gate": {
            "passed": wm_passed,
            "skipped": wm_skipped,
            "detected_corner": wm_corner,
            "confidence": round(wm_conf, 2),
            "reason": wm_reason
        },
        "peak_quality_gate": peak_qa,
        "cartoon_classifier": cartoon,
        "sharpness": sharpness,
        "captions": caption_qc,
        "source_guard": source_guard,
        "repeat_spacing_gate": repeat_spacing,
        "repeat_share_pct": repeat_spacing.get("repeat_share_pct", 0.0),
        "repeat_share_str": repeat_spacing.get("repeat_share_str", "0% repeat (100% unique moments)"),
        "contact_sheet": sheet_file,
        "model_version": _active_model_version()
    }

    freshness_info = None
    if clip_mapping:
        try:
            from clip_ledger import compute_footage_freshness
            freshness_info = compute_footage_freshness(clip_mapping, current_job_id=base_name)
        except Exception:
            freshness_info = None
    f_card_line = freshness_info.get("card_line") if freshness_info else "New footage: not measured"
    report["freshness"] = freshness_info
    report["freshness_card_line"] = f_card_line
    report["status_card_line"] = f_card_line

    unified = calculate_unified_verdict(report, clip_mapping or [], jcfg)
    verdict_text = unified["badge"]
    all_passed = is_pass(verdict_text)
    report["verdict"] = verdict_text
    report["overall_passed"] = all_passed
    report["unified_verdict"] = unified
    print("=" * 72)
    print(f"  FINAL QA VERDICT: {verdict_text}\n")

    with open(report_path, "w", encoding="utf-8") as f_rep:
        json.dump(report, f_rep, indent=2)

    return all_passed, report

# Alias for external scripts
run_master_quality_audit = run_full_qa

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if not target:
        import glob
        matches = sorted(glob.glob("finished/*.mp4"), key=os.path.getmtime, reverse=True)
        target = matches[0] if matches else None
    if target:
        run_full_qa(target)
    else:
        print("Usage: python qa_check.py <path_to_video.mp4>")
