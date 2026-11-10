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


# ---------------------------------------------------------------------------
# Still text: captions, handles, comment bubbles and banners burned into the source.
# An overlay stays at the same pixels while the footage behind it moves, so the check
# looks for sharp edges that do not change across a short run of frames, then keeps
# only regions that binarise into a row of letter-sized shapes.
# ---------------------------------------------------------------------------

STILL_TEXT_PROC_H = 720
STILL_TEXT_RUN_FRAMES = 5
STILL_TEXT_RUN_STEP_S = 0.2
STILL_TEXT_MIN_EDGE = 70        # morphological gradient a glyph edge keeps in every frame of the run
STILL_TEXT_MAX_FLICKER = 10.0   # per-pixel standard deviation across the run
STILL_TEXT_MIN_LETTERS = 3
STILL_TEXT_MIN_LETTERS_AT_EDGE = 6
STILL_TEXT_MIN_CONTRAST = 70.0  # letters against their background, grey levels
STILL_TEXT_FEW_LETTERS = 5
STILL_TEXT_FEW_LETTERS_CONTRAST = 100.0
STILL_TEXT_MIN_BRIGHT = 150.0   # overlays are made to be read: white or bright text, or a bright box
STILL_TEXT_CLOSE = (15, 3)     # joins letters into words, keeps stacked lines apart


def _count_letters(crop: np.ndarray, touches_edge: bool = False) -> Tuple[int, float, float]:
    """Letter-sized shapes in a binarised text-line crop, the letter/background contrast,
    and the mean grey of the brighter of the two."""
    if crop.size == 0 or crop.shape[0] < 4:
        return 0, 0.0, 0.0
    _, binary = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    fg, bg = crop[binary > 0], crop[binary == 0]
    if not fg.size or not bg.size:
        return 0, 0.0, 0.0
    contrast = abs(float(fg.mean()) - float(bg.mean()))
    bright = max(float(fg.mean()), float(bg.mean()))
    h = crop.shape[0]
    best = 0
    for m in (binary, 255 - binary):
        share = np.count_nonzero(m) / float(m.size)
        if not 0.05 <= share <= 0.6:
            continue
        n, _, stats, _ = cv2.connectedComponentsWithStats(m)
        k = 0
        for i in range(1, n):
            y, ch, cw, area = stats[i, 1], stats[i, 3], stats[i, 2], stats[i, 4]
            inside = touches_edge or (y > 0 and y + ch < h)
            if 0.3 * h <= ch <= 0.95 * h and cw <= 1.5 * h and area >= 6 and inside:
                k += 1
        best = max(best, k)
    return best, contrast, bright


def find_still_text(gray_frames: List[np.ndarray]) -> List[Dict[str, Any]]:
    """Text boxes that stay fixed across a run of greyscale frames (same size, 720 px high)."""
    if len(gray_frames) < 3:
        return []
    stack = np.stack(gray_frames).astype(np.float32)
    grads = np.stack([cv2.morphologyEx(g, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) for g in gray_frames])
    mask = ((grads.min(axis=0) >= STILL_TEXT_MIN_EDGE) & (stack.std(axis=0) <= STILL_TEXT_MAX_FLICKER)).astype(np.uint8) * 255

    # Only the sharp picture reaches the output: blurred or black side bars are cropped away
    energy = cv2.blur(grads.max(axis=0).mean(axis=0).astype(np.float32).reshape(1, -1), (31, 1)).ravel()
    w = energy.size
    centre = float(np.median(energy[w // 3: 2 * w // 3]))
    live = np.where(energy >= 0.25 * centre)[0] if centre > 0 else np.arange(w)
    if live.size:
        mask[:, :int(live[0])] = 0
        mask[:, int(live[-1]) + 1:] = 0

    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, STILL_TEXT_CLOSE))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mean = stack.mean(axis=0).astype(np.uint8)
    h = mask.shape[0]
    boxes = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        if bh < 8 or bh > 90 or bw < 1.8 * bh or bw * bh < 250:
            continue
        pad = 3
        crop = mean[max(0, y - pad):y + bh + pad, max(0, x - pad):x + bw + pad]
        at_edge = y - pad < 0 or y + bh + pad > h
        letters, contrast, bright = _count_letters(crop, touches_edge=at_edge)
        # A line cut by the frame edge needs more letters: half shapes there are often scenery
        need = STILL_TEXT_MIN_LETTERS_AT_EDGE if at_edge else STILL_TEXT_MIN_LETTERS
        # A short run of shapes is weaker evidence than a word: it must stand out more
        min_contrast = STILL_TEXT_FEW_LETTERS_CONTRAST if letters < STILL_TEXT_FEW_LETTERS else STILL_TEXT_MIN_CONTRAST
        if letters >= need and contrast >= min_contrast and bright >= STILL_TEXT_MIN_BRIGHT:
            boxes.append({"x": x, "y": y, "w": bw, "h": bh, "letters": letters, "contrast": round(contrast, 1)})
    return boxes


def check_window_still_text(video_path: str, start_s: float, dur_s: float, n_runs: int = 8) -> Dict[str, Any]:
    """
    Burned-in source text in a source window. Reads the window once, front to back, and
    tests n_runs short runs of frames spread across it. Any run with still text fails it.
    passed is None when the window could not be read: that is not a pass.
    """
    if not video_path or not os.path.exists(video_path):
        return {"passed": None, "reason": "SOURCE_NOT_FOUND", "runs": 0, "text_runs": 0}
    cap = cv2.VideoCapture(video_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if fps <= 0 or total <= 0 or dur_s <= 0:
            return {"passed": None, "reason": "INVALID_VIDEO_SPAN", "runs": 0, "text_runs": 0}
        start_f = max(0, int(round(start_s * fps)))
        end_f = min(total, start_f + int(round(dur_s * fps)))
        step = max(1, int(round(STILL_TEXT_RUN_STEP_S * fps)))
        run_len = step * (STILL_TEXT_RUN_FRAMES - 1)
        span = end_f - 1 - start_f - run_len  # the last frame of the window is end_f - 1
        if span < 0:
            return {"passed": None, "reason": "WINDOW_TOO_SHORT", "runs": 0, "text_runs": 0}
        n_runs = max(1, min(n_runs, span // step + 1))
        wanted = {}
        for r in range(n_runs):
            f0 = start_f + (span * r) // max(1, n_runs - 1) if n_runs > 1 else start_f + span // 2
            for j in range(STILL_TEXT_RUN_FRAMES):
                wanted.setdefault(f0 + j * step, []).append(r)

        runs = [[] for _ in range(n_runs)]
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)
        pos = start_f
        last = max(wanted)
        while pos <= last:
            if pos in wanted:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                fh, fw = frame.shape[:2]
                small = cv2.resize(frame, (max(1, int(fw * STILL_TEXT_PROC_H / float(fh))), STILL_TEXT_PROC_H))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                for r in wanted[pos]:
                    runs[r].append(gray)
            elif not cap.grab():
                break
            pos += 1
    finally:
        cap.release()

    complete = [r for r in runs if len(r) == STILL_TEXT_RUN_FRAMES]
    if not complete:
        return {"passed": None, "reason": "FAILED_TO_DECODE_FRAMES", "runs": 0, "text_runs": 0}
    hits = []
    for i, run in enumerate(complete):
        boxes = find_still_text(run)
        if boxes:
            hits.append({"run": i, "boxes": boxes[:4]})
    passed = not hits
    reason = "CLEAN_NO_SOURCE_TEXT" if passed else f"BURNED_IN_SOURCE_TEXT ({len(hits)}/{len(complete)} frame runs)"
    return {"passed": passed, "reason": reason, "runs": len(complete), "text_runs": len(hits), "hits": hits}
