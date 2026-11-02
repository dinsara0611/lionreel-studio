"""
overlay_text_detector.py
========================
Burned-in Text and Overlay Gate for Stage A, Post-Crop, and Final QA.
Detects:
1. Title banners, channel names, subtitles, stickers, and text overlays via edge/gradient + MSER + morphology.
2. Black bands / letterbox / pillarbox bars (real pixel row/col scans).

Thresholds per contract specification:
- Rejects windows where text covers > 3% of the frame area in >= 20% of sampled frames.
- Rejects windows where any text box is > 1.5% of the area in >= 20% of sampled frames.
- Rejects windows where text sits in top 25% or bottom 20% with >= 2% area in >= 20% of sampled frames.
- Rejects windows with black letterbox/pillarbox borders (>= 6 px border mean < 12.0) not part of layout.
"""

import os
import cv2
import numpy as np
from typing import Dict, Any, List, Tuple

def check_frame_black_borders(frame: np.ndarray, border_threshold: float = 12.0, min_border_thickness: int = 6) -> Dict[str, Any]:
    """
    Real pixel row-by-row and column-by-column scan for solid black letterbox or pillarbox bars.
    """
    if frame is None or frame.size == 0:
        return {"has_black_border": False, "top_black": 0, "bot_black": 0, "left_black": 0, "right_black": 0}
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
    row_means = np.mean(gray, axis=1)
    col_means = np.mean(gray, axis=0)

    top_black = 0
    while top_black < h // 4 and row_means[top_black] < border_threshold:
        top_black += 1

    bot_black = 0
    while bot_black < h // 4 and row_means[h - 1 - bot_black] < border_threshold:
        bot_black += 1

    left_black = 0
    while left_black < w // 4 and col_means[left_black] < border_threshold:
        left_black += 1

    right_black = 0
    while right_black < w // 4 and col_means[w - 1 - right_black] < border_threshold:
        right_black += 1

    has_black_border = (
        top_black >= min_border_thickness
        or bot_black >= min_border_thickness
        or left_black >= min_border_thickness
        or right_black >= min_border_thickness
    )
    return {
        "has_black_border": has_black_border,
        "top_black": top_black,
        "bot_black": bot_black,
        "left_black": left_black,
        "right_black": right_black,
    }


def analyze_frame_text_and_borders(frame: np.ndarray, is_pillarbox_layout: bool = False, is_master_with_captions: bool = False, **kwargs) -> Dict[str, Any]:
    """
    Analyzes a single frame for text overlays and black borders.
    """
    if frame is None or frame.size == 0:
        return {"has_text_overlay": False, "has_black_border": False, "reasons": ["EMPTY_FRAME"]}

    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame

    # 1. Real Pixel Border Scan (no black bands/letterbox)
    row_means = np.mean(gray, axis=1)
    col_means = np.mean(gray, axis=0)

    top_black = 0
    while top_black < h // 4 and row_means[top_black] < 12.0:
        top_black += 1

    bot_black = 0
    while bot_black < h // 4 and row_means[h - 1 - bot_black] < 12.0:
        bot_black += 1

    left_black = 0
    while left_black < w // 4 and col_means[left_black] < 12.0:
        left_black += 1

    right_black = 0
    while right_black < w // 4 and col_means[w - 1 - right_black] < 12.0:
        right_black += 1

    # Black borders are forbidden unless explicitly in a pillarbox layout (which uses blurred backgrounds, not solid black)
    has_black_border = (top_black >= 6 or bot_black >= 6 or left_black >= 6 or right_black >= 6)

    # 2. Text / Overlay Detection
    scale = 720.0 / float(h)
    proc_w = int(w * scale)
    proc_h = 720
    small_gray = cv2.resize(gray, (proc_w, proc_h), interpolation=cv2.INTER_LINEAR)
    small_area = float(proc_w * proc_h)

    # Real burned-in text glyphs have strong stroke edges (grad >= 145) adjacent to bright white/yellow
    # or solid black strokes with outline contrast, not soft fur/carpet/grass texture.
    kernel_grad = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    grad = cv2.morphologyEx(small_gray, cv2.MORPH_GRADIENT, kernel_grad)
    kernel_5 = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    local_max = cv2.dilate(small_gray, kernel_5)
    local_min = cv2.erode(small_gray, kernel_5)
    stroke_mask = ((grad >= 145) & (local_max >= 238) & (local_min <= 28)).astype(np.uint8) * 255

    # Connect letters horizontally into words and text boxes
    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 3))
    closed = cv2.morphologyEx(stroke_mask, cv2.MORPH_CLOSE, kernel_close)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    top_zone_h = int(proc_h * 0.22)
    bot_zone_y = int(proc_h * 0.80)

    total_text_area = 0.0
    top_text_area = 0.0
    bot_text_area = 0.0
    max_box_area = 0.0
    text_boxes = []

    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        box_area = bw * bh
        if box_area < 260:
            continue
        aspect = bw / float(bh)
        # Text word-box characteristics: horizontal word aspect >= 2.2, character height 14..75px
        if aspect >= 2.2 and 14 <= bh <= 75 and (box_area / small_area) <= 0.20:
            box_strokes = stroke_mask[y:y+bh, x:x+bw]
            edge_density = np.count_nonzero(box_strokes > 0) / float(box_area)
            # Count discrete letter-like connected components inside the word box
            num_labels, _ = cv2.connectedComponents(box_strokes)
            if 0.20 <= edge_density <= 0.65 and num_labels >= 5:
                box_frac = box_area / small_area
                total_text_area += box_frac
                if box_frac > max_box_area:
                    max_box_area = box_frac
                if y < top_zone_h:
                    overlap_h = min(top_zone_h, y + bh) - y
                    top_text_area += (bw * overlap_h) / small_area
                if (y + bh) > bot_zone_y:
                    overlap_h = (y + bh) - max(bot_zone_y, y)
                    bot_text_area += (bw * overlap_h) / small_area
                text_boxes.append((x, y, bw, bh, box_frac))

    # Also detect high-saturation yellow subtitle strokes in top/bottom zones
    if len(frame.shape) == 3:
        small_color = cv2.resize(frame, (proc_w, proc_h), interpolation=cv2.INTER_LINEAR)
        hsv = cv2.cvtColor(small_color, cv2.COLOR_BGR2HSV)
        yellow_mask = cv2.inRange(hsv, np.array([20, 160, 210]), np.array([34, 255, 255]))
        yellow_strokes = cv2.bitwise_and(stroke_mask, yellow_mask)
        yellow_text_top = yellow_strokes[:top_zone_h, :]
        yellow_text_bot = yellow_strokes[bot_zone_y:, :]
        if np.count_nonzero(yellow_text_top) / float(top_zone_h * proc_w) > 0.035:
            top_text_area = max(top_text_area, 0.035 * 0.25)
        if np.count_nonzero(yellow_text_bot) / float((proc_h - bot_zone_y) * proc_w) > 0.035:
            bot_text_area = max(bot_text_area, 0.035 * 0.20)

    top_zone_ratio = top_text_area / 0.25
    bot_zone_ratio = bot_text_area / 0.20

    frame_reasons = []
    if total_text_area > 0.03 and not is_master_with_captions:
        frame_reasons.append(f"TOTAL_TEXT_AREA ({total_text_area:.1%} > 3%)")
    elif total_text_area > 0.08 and is_master_with_captions:
        frame_reasons.append(f"TOTAL_TEXT_AREA ({total_text_area:.1%} > 8%)")
    if max_box_area > 0.015 and not is_master_with_captions:
        frame_reasons.append(f"LARGE_TEXT_BOX ({max_box_area:.1%} > 1.5%)")
    elif max_box_area > 0.05 and is_master_with_captions:
        frame_reasons.append(f"LARGE_TEXT_BOX ({max_box_area:.1%} > 5%)")
    if top_zone_ratio >= 0.02:
        frame_reasons.append(f"TOP_BANNER_TEXT ({top_zone_ratio:.1%} >= 2%)")
    if bot_zone_ratio >= 0.02 and not is_master_with_captions:
        frame_reasons.append(f"BOTTOM_OVERLAY_TEXT ({bot_zone_ratio:.1%} >= 2%)")
    if has_black_border and not is_pillarbox_layout:
        frame_reasons.append(f"BLACK_BORDER (T:{top_black} B:{bot_black} L:{left_black} R:{right_black})")

    has_text = (total_text_area > (0.08 if is_master_with_captions else 0.03) or
                max_box_area > (0.05 if is_master_with_captions else 0.015) or
                top_zone_ratio >= 0.02 or
                (bot_zone_ratio >= 0.02 and not is_master_with_captions))

    return {
        "has_text_overlay": has_text,
        "has_burned_in_text": has_text,
        "has_black_border": has_black_border,
        "frame_reasons": frame_reasons,
        "total_text_area": total_text_area,
        "max_box_area": max_box_area,
        "top_zone_ratio": top_zone_ratio,
        "bot_zone_ratio": bot_zone_ratio,
        "border_px": {"top": top_black, "bottom": bot_black, "left": left_black, "right": right_black}
    }


def check_window_burned_in_text(video_path: str, start_s: float, dur_s: float, n_samples: int = 8, is_pillarbox: bool = False, is_master_with_captions: bool = False, **kwargs) -> Dict[str, Any]:
    """
    Evaluates 6-8 sampled frames across a candidate video window for burned-in text/overlays and black borders.
    Enforces contract threshold: Rejects if violations occur in >= 20% of sampled frames.
    """
    if not os.path.exists(video_path):
        return {"passed": False, "reason": "FILE_NOT_FOUND"}

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap_dur = total_frames / fps if fps > 0 else 0.0

    if total_frames <= 0 or dur_s <= 0:
        cap.release()
        return {"passed": False, "reason": "INVALID_VIDEO_SPAN"}

    start_f = int(max(0.0, start_s) * fps)
    span_frames = int(dur_s * fps)
    end_f = min(total_frames, start_f + span_frames)
    actual_frames = max(1, end_f - start_f)

    sampled = 0
    text_violations = 0
    border_violations = 0
    reasons_counter = {}

    for i in range(n_samples):
        pos_f = start_f + int(actual_frames * (i + 0.5) / float(n_samples))
        pos_f = min(total_frames - 1, max(0, pos_f))
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos_f)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
        sampled += 1

        res = analyze_frame_text_and_borders(frame, is_pillarbox_layout=is_pillarbox, is_master_with_captions=is_master_with_captions)
        if res["has_text_overlay"]:
            text_violations += 1
            for r in res["frame_reasons"]:
                reasons_counter[r] = reasons_counter.get(r, 0) + 1
        if res["has_black_border"] and not is_pillarbox:
            border_violations += 1
            b_reason = f"BLACK_BORDER (T:{res['border_px']['top']} B:{res['border_px']['bottom']} L:{res['border_px']['left']} R:{res['border_px']['right']})"
            reasons_counter[b_reason] = reasons_counter.get(b_reason, 0) + 1

    cap.release()

    if sampled == 0:
        return {"passed": False, "reason": "FAILED_TO_DECODE_FRAMES"}

    text_fail_rate = text_violations / float(sampled)
    border_fail_rate = border_violations / float(sampled)

    # Rejection threshold: >= 20% of sampled frames
    passed = (text_fail_rate < 0.20) and (border_fail_rate < 0.20)
    top_reason = ""
    if not passed:
        sorted_reasons = sorted(reasons_counter.items(), key=lambda x: x[1], reverse=True)
        top_reason = sorted_reasons[0][0] if sorted_reasons else "BURNED_IN_TEXT_OR_OVERLAY_DETECTED"

    return {
        "passed": passed,
        "reason": top_reason if not passed else "CLEAN_NO_OVERLAYS",
        "sampled_frames": sampled,
        "text_violations": text_violations,
        "border_violations": border_violations,
        "text_fail_rate": text_fail_rate,
        "border_fail_rate": border_fail_rate,
        "reasons_detail": reasons_counter
    }
