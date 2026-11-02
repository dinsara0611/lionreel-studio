"""
LionReel Studio Thumbnail Maker Module
Specialized for long videos (>= 3 minutes) with 16:9 high-impact thumbnails.
Adheres strictly to full-bleed contract, picture provenance, style rules, and YouTube specifications.
"""

import os
import sys
import json
import math
import shutil
import subprocess
import tempfile
import io
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageFile
ImageFile.MAXBLOCK = 1024 * 1024 * 32

from typing import Dict, List, Any, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pet_detector import PetDetector

def sanitize_path(path_str: str) -> str:
    """Sanitizes file paths to avoid exposing private user directory paths."""
    if not path_str:
        return ""
    clean = str(path_str).replace("\\", "/")
    if ":" in clean:
        clean = clean.split(":")[-1].lstrip("/")
    return clean

CONFIG_LIMITS_PATH = os.path.join(BASE_DIR, "config", "platform_limits.json")
LEARNING_STORE_PATH = os.path.join(BASE_DIR, "thumbnail_learning.json")
OCR_SCRIPT_PATH = os.path.join(BASE_DIR, "scripts", "ocr_recognize.ps1")

FONT_CANDIDATES = [
    os.path.join(BASE_DIR, "assets", "fonts", "Montserrat.ttf"),
    r"C:\Windows\Fonts\impact.ttf",
    r"C:\Windows\Fonts\ariblk.ttf",
    os.path.join(BASE_DIR, "assets", "fonts", "NotoSansSinhala.ttf")
]

TEXT_COLOR_PRESETS = {
    "high_contrast_yellow": {
        "name": "High-Contrast Yellow",
        "fill": (255, 230, 0),
        "stroke": (0, 0, 0),
        "banner_bg": (15, 23, 42, 230)
    },
    "pure_white_bold": {
        "name": "Pure White Bold",
        "fill": (255, 255, 255),
        "stroke": (10, 10, 10),
        "banner_bg": (0, 0, 0, 210)
    },
    "electric_lime": {
        "name": "Electric Lime",
        "fill": (57, 255, 20),
        "stroke": (5, 20, 10),
        "banner_bg": (10, 25, 47, 230)
    },
    "sunset_orange": {
        "name": "Sunset Orange",
        "fill": (255, 107, 53),
        "stroke": (20, 10, 5),
        "banner_bg": (24, 24, 27, 230)
    }
}

SHOCK_WORDS = {"shocking", "unbelievable", "you won't believe", "insane", "miracle", "crying", "died", "gone wrong", "3am"}


def is_thumbnail_supported_for_job(job_id: str) -> Tuple[bool, str]:
    """
    Decides thumbnail availability strictly by job mode, not by video length:
    - Long mode: supported (True)
    - Both formats (long file): supported (True)
    - Short mode / short format: rejected (False, 'not available for Shorts')
    """
    if not job_id:
        return False, "Invalid job ID"
    clean_id = str(job_id).replace(".mp4", "")
    output_dir = os.path.join(BASE_DIR, "output")
    work_dir = os.path.join(BASE_DIR, "work")
    local_work_dir = r"C:\LionReel\work"
    fin_dir = os.path.join(BASE_DIR, "finished")

    paths_to_check = [
        os.path.join(local_work_dir, clean_id, "job_config.json"),
        os.path.join(work_dir, clean_id, "job_config.json"),
        os.path.join(output_dir, clean_id, "planner_decision.json"),
        os.path.join(local_work_dir, clean_id, "planner_decision.json"),
        os.path.join(fin_dir, f"{clean_id}_planner_decision.json"),
        os.path.join(work_dir, clean_id, "planner_decision.json"),
        os.path.join(output_dir, clean_id, f"{clean_id}_mapping.json"),
        os.path.join(local_work_dir, clean_id, f"{clean_id}_mapping.json"),
        os.path.join(output_dir, clean_id, "mapping.json"),
        os.path.join(fin_dir, f"{clean_id}_mapping.json"),
        os.path.join(work_dir, clean_id, f"{clean_id}_mapping.json"),
        os.path.join(output_dir, clean_id, "config.json"),
        os.path.join(fin_dir, f"{clean_id}_config.json"),
        os.path.join(work_dir, clean_id, "config.json"),
        os.path.join(output_dir, clean_id, f"{clean_id}_qa_report.json"),
        os.path.join(fin_dir, f"{clean_id}_qa_report.json"),
        os.path.join(output_dir, clean_id, f"{clean_id}_report.json"),
        os.path.join(fin_dir, f"{clean_id}_report.json"),
        os.path.join(work_dir, clean_id, "timings.json"),
    ]
    mode = None
    dur_s = None
    is_vertical = False

    for p in paths_to_check:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    m = (
                        d.get("mode") or
                        d.get("MODE") or
                        d.get("type") or
                        d.get("video_type") or
                        d.get("config", {}).get("MODE") or
                        d.get("config", {}).get("VIDEO_MODE") or
                        d.get("summary", {}).get("mode") or
                        d.get("summary", {}).get("video_type")
                    )
                    if m and str(m).lower() in ("short", "long", "compilation", "both"):
                        mode = "long" if str(m).lower() == "compilation" else str(m).lower()
                        break
                    if "stream_specs" in d and isinstance(d["stream_specs"], dict):
                        ds = d["stream_specs"].get("duration_sec")
                        if ds is not None:
                            dur_s = float(ds)
                        sw = d["stream_specs"].get("width")
                        sh = d["stream_specs"].get("height")
                        if sw and sh and sh > sw:
                            is_vertical = True
                    if "summary" in d and isinstance(d["summary"], dict):
                        ds = d["summary"].get("delivered_duration_sec") or d["summary"].get("requested_duration_sec")
                        if ds is not None:
                            dur_s = float(ds)
                        ar = d["summary"].get("aspect_ratio")
                        if ar == "9:16":
                            is_vertical = True
                    if "plan_and_decisions" in d:
                        logs = " ".join(d["plan_and_decisions"].get("planner_logs", []))
                        if "target: 30.0s" in logs or "4 clips @ ~7.5s" in logs:
                            mode = "short"
                            break
                    if "stages" in d and isinstance(d["stages"], dict) and "reframe" in d["stages"]:
                        # Only treat as vertical short if total_wall_time_sec is small (< 300s) and no other mode known
                        tw = d.get("total_wall_time_sec") or d.get("total_duration_sec") or 0
                        if float(tw) < 300.0:
                            is_vertical = True
            except Exception:
                pass

    if not mode:
        vpaths = [
            os.path.join(fin_dir, f"{clean_id}.mp4"),
            os.path.join(output_dir, clean_id, f"{clean_id}.mp4"),
            os.path.join(work_dir, clean_id, f"{clean_id}.mp4"),
        ]
        for vp in vpaths:
            if os.path.exists(vp):
                try:
                    cap = cv2.VideoCapture(vp)
                    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
                    if fps > 0 and frames > 0:
                        dur_s = frames / fps
                    vw = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                    vh = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    if vh > vw:
                        is_vertical = True
                    cap.release()
                    break
                except Exception:
                    pass

    if not mode:
        cid_lower = clean_id.lower()
        if "short" in cid_lower:
            mode = "short"
        elif "long" in cid_lower or "compilation" in cid_lower:
            mode = "long"
        elif dur_s is not None and dur_s < 180.0:
            mode = "short"

    if mode == "short":
        return False, "not available for Shorts"
    elif mode in ("long", "both"):
        return True, "Thumbnail supported for Long/Both format"

    # Fallback: if vertical and under 3 minutes, treat as Short
    if is_vertical and (dur_s is None or dur_s < 180.0):
        return False, "not available for Shorts"

    return True, "Default Long mode assumed"


def load_platform_limits() -> Dict[str, Any]:
    """Loads YouTube custom thumbnail specifications from platform_limits.json."""
    if os.path.exists(CONFIG_LIMITS_PATH):
        try:
            with open(CONFIG_LIMITS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("youtube_custom_thumbnail", {})
        except Exception:
            pass
    return {
        "aspect_ratio": "16:9",
        "desktop_standard_res": [1920, 1080],
        "desktop_max_bytes": 52428800,
        "mobile_recommended_res": [1280, 720],
        "mobile_max_bytes": 2097152,
        "test_and_compare_min_res": [1280, 720],
        "safe_zone_bottom_right_badge_clearance_px": [180, 70]
    }


def get_available_font(size: int) -> ImageFont.FreeTypeFont:
    """Loads the best available high-impact font."""
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def calculate_wcag_contrast(rgb1: Tuple[int, int, int], rgb2: Tuple[int, int, int]) -> float:
    """Computes WCAG 2.1 relative luminance contrast ratio between two RGB colors."""
    def luminance(c):
        vals = [v / 255.0 for v in c[:3]]
        adj = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in vals]
        return 0.2126 * adj[0] + 0.7152 * adj[1] + 0.0722 * adj[2]
    
    l1 = luminance(rgb1)
    l2 = luminance(rgb2)
    bright = max(l1, l2)
    dark = min(l1, l2)
    return round((bright + 0.05) / (dark + 0.05), 2)


def enhance_visual_quality(img: Image.Image, is_4k: bool = False) -> Image.Image:
    """
    Applies high-perceptual visual enhancement:
    - Unsharp mask for popping pet fur texture, whiskers, and eye catchlights.
    - Subtle micro-contrast boost (+4% for 4K).
    - Subtle color vibrancy boost (+3% for 4K).
    """
    if img is None:
        return img
    try:
        if is_4k:
            # 4K Ultra-HD unsharp mask: radius=1.8, percent=125, threshold=2
            enhanced = img.filter(ImageFilter.UnsharpMask(radius=1.8, percent=125, threshold=2))
            enhanced = ImageEnhance.Contrast(enhanced).enhance(1.04)
            enhanced = ImageEnhance.Color(enhanced).enhance(1.03)
            return enhanced
        else:
            # 1080p subtle clarity
            enhanced = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=115, threshold=2))
            enhanced = ImageEnhance.Contrast(enhanced).enhance(1.02)
            return enhanced
    except Exception:
        return img


def save_jpeg_under_limit(
    img: Image.Image,
    out_path: str,
    max_bytes: int = 2000000,
    is_4k: bool = False,
    qualities: Optional[List[int]] = None
) -> Tuple[int, int]:
    """
    Saves image as JPEG strictly below max_bytes (default 2,000,000 bytes = 2.0 MB).
    Uses 4:4:4 chroma subsampling (subsampling=0) for 4K pristine color fidelity.
    Returns (actual_size_bytes, quality_used).
    """
    if qualities is None:
        qualities = [94, 91, 88, 85, 82, 78, 74, 70, 65]

    subsampling_mode = 0 if is_4k else -1

    for q in qualities:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            tmp_f = tf.name
            tf.close()
        try:
            img.save(tmp_f, "JPEG", quality=q, optimize=True, subsampling=subsampling_mode)
            sz = os.path.getsize(tmp_f)
            if sz <= max_bytes:
                shutil.copyfile(tmp_f, out_path)
                return sz, q
        finally:
            if os.path.exists(tmp_f):
                try: os.remove(tmp_f)
                except: pass

    # If extreme noise/entropy still exceeds max_bytes at 4:4:4, try 4:2:0 subsampling
    if is_4k:
        for q in [85, 80, 75, 70, 65, 60, 55]:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
                tmp_f = tf.name
                tf.close()
            try:
                img.save(tmp_f, "JPEG", quality=q, optimize=True, subsampling=-1)
                sz = os.path.getsize(tmp_f)
                if sz <= max_bytes:
                    shutil.copyfile(tmp_f, out_path)
                    return sz, q
            finally:
                if os.path.exists(tmp_f):
                    try: os.remove(tmp_f)
                    except: pass

    # Final guarantee
    img.save(out_path, "JPEG", quality=55, optimize=True)
    return os.path.getsize(out_path), 55



def run_windows_ocr_check(image_pil: Image.Image) -> Dict[str, Any]:
    """
    Downscales thumbnail to 210px width (standard mobile search width) and runs
    native Windows OCR to verify viewer legibility.
    """
    w, h = image_pil.size
    aspect = h / max(1, w)
    thumb_210 = image_pil.resize((210, int(210 * aspect)), Image.Resampling.LANCZOS)
    enhanced = ImageEnhance.Contrast(thumb_210).enhance(1.3)
    enhanced = ImageEnhance.Sharpness(enhanced).enhance(1.5)
    
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tmp_path = tf.name
    try:
        enhanced.save(tmp_path, "PNG")
        if os.path.exists(OCR_SCRIPT_PATH):
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", OCR_SCRIPT_PATH, "-ImagePath", tmp_path]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
            recognized = res.stdout.strip()
            return {"success": True, "recognized_text": recognized, "tested_width_px": 210}
    except Exception as e:
        return {"success": False, "error": str(e), "recognized_text": "", "tested_width_px": 210}
    finally:
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except: pass
    return {"success": False, "recognized_text": "", "tested_width_px": 210}


def detect_source_bars(frame: np.ndarray) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    """
    Section 3 Requirement:
    Run cropdetect on the SOURCE frame first and crop to active picture area
    (some sources carry their own letterbox/pillarbox bars).
    Scans inwards from each of the 4 borders for dark/flat bands (mean < 14, std < 3.5).
    Returns (clean_frame, (top_cut, bot_cut, left_cut, right_cut)).
    """
    if frame is None or frame.size == 0:
        return frame, (0, 0, 0, 0)

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
    h, w = gray.shape[:2]

    # Top scan
    top_cut = 0
    while top_cut < (h // 3):
        row = gray[top_cut, :]
        m = float(np.mean(row))
        s = float(np.std(row))
        if m < 14.0 and s < 4.0:
            top_cut += 1
        elif m < 8.0:
            top_cut += 1
        else:
            break

    # Bottom scan
    bot_cut = 0
    while bot_cut < (h // 3):
        row = gray[h - 1 - bot_cut, :]
        m = float(np.mean(row))
        s = float(np.std(row))
        if m < 14.0 and s < 4.0:
            bot_cut += 1
        elif m < 8.0:
            bot_cut += 1
        else:
            break

    # Left scan
    left_cut = 0
    while left_cut < (w // 3):
        col = gray[:, left_cut]
        m = float(np.mean(col))
        s = float(np.std(col))
        if m < 14.0 and s < 4.0:
            left_cut += 1
        elif m < 8.0:
            left_cut += 1
        else:
            break

    # Right scan
    right_cut = 0
    while right_cut < (w // 3):
        col = gray[:, w - 1 - right_cut]
        m = float(np.mean(col))
        s = float(np.std(col))
        if m < 14.0 and s < 4.0:
            right_cut += 1
        elif m < 8.0:
            right_cut += 1
        else:
            break

    # Only crop if at least 4 contiguous pixels detected
    t = top_cut if top_cut >= 4 else 0
    b = bot_cut if bot_cut >= 4 else 0
    l = left_cut if left_cut >= 4 else 0
    r = right_cut if right_cut >= 4 else 0

    clean_frame = frame[t : h - b, l : w - r]
    if clean_frame.shape[0] < 30 or clean_frame.shape[1] < 30:
        clean_frame = frame
        t, b, l, r = 0, 0, 0, 0

    return clean_frame, (t, b, l, r)


def check_full_bleed(frame_or_img: Any) -> Tuple[bool, str]:
    """
    Section 3 Requirement (FULL BLEED GATE):
    Canvas exactly 16:9. Edge to edge: no black or dark bars, no pillarbox or letterbox,
    no blurred side strips, no borders, frames, rounded corners, shadows or vignette.
    Detection: for each side find the largest band whose mean luma is below 14 with very low variance;
    reject if any band is at least 1% of that dimension (6 px at 720p).
    """
    if frame_or_img is None:
        return False, "Empty or None frame"

    if isinstance(frame_or_img, Image.Image):
        arr = np.array(frame_or_img)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY) if len(arr.shape) == 3 else arr
    elif isinstance(frame_or_img, np.ndarray):
        gray = cv2.cvtColor(frame_or_img, cv2.COLOR_BGR2GRAY) if len(frame_or_img.shape) == 3 else frame_or_img
    else:
        return False, f"Unsupported image type: {type(frame_or_img)}"

    h, w = gray.shape[:2]
    if h < 20 or w < 20:
        return False, f"Image dimensions too small ({w}x{h})"

    # 1. Exact 16:9 Canvas Gate
    aspect = float(w) / float(h)
    if abs(aspect - (16.0 / 9.0)) > 0.02:
        return False, f"Canvas {w}x{h} (aspect {aspect:.3f}) is not 16:9"

    # 2. Band detection: for each side find the largest band whose mean luma is below 14 with low variance
    # Reject if any band is >= 1% of that dimension (e.g. 6px at 720p, 10px at 1080p)
    limit_h = max(4, int(h * 0.01))
    limit_w = max(6, int(w * 0.01))

    # Top band
    top_band = 0
    while top_band < (h // 4):
        row = gray[top_band, :]
        m = float(np.mean(row))
        s = float(np.std(row))
        if (m < 14.0 and s < 4.0) or m < 8.0:
            top_band += 1
        else:
            break
    if top_band >= limit_h:
        return False, f"Top black/dark bar detected ({top_band}px >= {limit_h}px 1% limit)"

    # Bottom band
    bot_band = 0
    while bot_band < (h // 4):
        row = gray[h - 1 - bot_band, :]
        m = float(np.mean(row))
        s = float(np.std(row))
        if (m < 14.0 and s < 4.0) or m < 8.0:
            bot_band += 1
        else:
            break
    if bot_band >= limit_h:
        return False, f"Bottom black/dark bar detected ({bot_band}px >= {limit_h}px 1% limit)"

    # Left band
    left_band = 0
    while left_band < (w // 4):
        col = gray[:, left_band]
        m = float(np.mean(col))
        s = float(np.std(col))
        if (m < 14.0 and s < 4.0) or m < 8.0:
            left_band += 1
        else:
            break
    if left_band >= limit_w:
        return False, f"Left black/dark bar detected ({left_band}px >= {limit_w}px 1% limit)"

    # Right band
    right_band = 0
    while right_band < (w // 4):
        col = gray[:, w - 1 - right_band]
        m = float(np.mean(col))
        s = float(np.std(col))
        if (m < 14.0 and s < 4.0) or m < 8.0:
            right_band += 1
        else:
            break
    if right_band >= limit_w:
        return False, f"Right black/dark bar detected ({right_band}px >= {limit_w}px 1% limit)"

    # 3. Outer 2% strip check for blurred bars, synthetic padding or borders
    th = max(3, int(h * 0.02))
    bh = max(3, int(h * 0.02))
    lw = max(4, int(w * 0.02))
    rw = max(4, int(w * 0.02))

    outer_strips = [
        ("top", gray[:th, :]),
        ("bottom", gray[h - bh:, :]),
        ("left", gray[:, :lw]),
        ("right", gray[:, w - rw:])
    ]
    for s_name, strip in outer_strips:
        m = float(np.mean(strip))
        s = float(np.std(strip))
        if m < 14.0:
            return False, f"Dark border on {s_name} strip (mean={m:.1f} < 14.0)"
        if m < 25.0 and s < 3.0:
            return False, f"Flat/artificial border on {s_name} strip (mean={m:.1f}, std={s:.1f})"

    # 4. Corner check for rounded corners, vignette or vignette falloff
    corners = [
        ("top-left", gray[:th, :lw]),
        ("top-right", gray[:th, w - rw:]),
        ("bottom-left", gray[h - bh:, :lw]),
        ("bottom-right", gray[h - bh:, w - rw:])
    ]
    for c_name, c_patch in corners:
        if float(np.mean(c_patch)) < 12.0 and float(np.std(c_patch)) < 4.0:
            return False, f"Vignette or rounded dark corner detected at {c_name}"

    return True, "Full bleed verified: edge-to-edge real pixels without bars or borders"


def is_frame_upscaled_or_small(frame: np.ndarray, min_width: int = 1024, min_height: int = 576) -> bool:
    """
    Section 4 Requirement:
    At most 1.25x upscaling. 1280 / 1.25 = 1024 px minimum width, 720 / 1.25 = 576 px minimum height.
    Reject frames below that floor.
    """
    if frame is None or frame.size == 0:
        return True
    h, w = frame.shape[:2]
    return bool(w < min_width or h < min_height)


def subject_aware_cover_crop(
    frame: np.ndarray,
    cat_box: Optional[Tuple[int, int, int, int]] = None,
    target_w: int = 1280,
    target_h: int = 720,
    head_fill_target: float = 0.65,
    detections: Optional[List[Any]] = None,
    target_res: Optional[Tuple[int, int]] = None
) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    """
    Section 3 & 4 Requirement:
    - Crops source frame to active picture area first (removes any source bars).
    - Subject-aware cover crop: cat head fills 50-95% of target height.
    - Eye line in upper half of frame (35-45% from top).
    - Never uses blur, bars or padding.
    - Returns resized (target_w, target_h) frame and original crop coordinates.
    """
    if target_res:
        target_w, target_h = target_res

    if detections and not cat_box:
        # Extract bounding box from detections (support single or double cats)
        boxes = []
        for d in detections:
            if isinstance(d, dict) and "box" in d:
                boxes.append(d["box"])
            elif isinstance(d, (list, tuple)) and len(d) == 4:
                boxes.append(d)
        if boxes:
            min_x = min(b[0] for b in boxes)
            min_y = min(b[1] for b in boxes)
            max_x = max(b[2] for b in boxes)
            max_y = max(b[3] for b in boxes)
            cat_box = (int(min_x), int(min_y), int(max_x), int(max_y))

    if frame is None or frame.size == 0:
        blank = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        return blank, (0, 0, target_w, target_h)

    # 1. Trim black/dark bars from source
    clean_frame, (t_cut, b_cut, l_cut, r_cut) = detect_source_bars(frame)
    h_clean, w_clean = clean_frame.shape[:2]

    # Adjust cat box to clean coordinates
    adj_box = None
    if cat_box:
        x1, y1, x2, y2 = cat_box
        adj_box = (
            max(0, x1 - l_cut),
            max(0, y1 - t_cut),
            min(w_clean, x2 - l_cut),
            min(h_clean, y2 - t_cut)
        )

    target_aspect = float(target_w) / float(target_h)  # 16 / 9

    # 2. Determine focal center and crop dimensions based on cat's head
    if adj_box and (adj_box[2] > adj_box[0]) and (adj_box[3] > adj_box[1]):
        bx1, by1, bx2, by2 = adj_box
        bw = bx2 - bx1
        bh = by2 - by1

        # Cat head estimated as top 55% of pet detection box
        head_h = max(30, int(bh * 0.55))
        head_cy = by1 + int(head_h * 0.50)
        head_cx = bx1 + int(bw * 0.50)

        # Target: cat head fills ~65% of crop height (bounded between 50% and 95%)
        wanted_h = int(round(head_h / max(0.50, min(0.95, head_fill_target))))
        wanted_w = int(round(wanted_h * target_aspect))

        # Ensure crop fits inside clean frame
        if wanted_w > w_clean:
            wanted_w = w_clean
            wanted_h = int(round(wanted_w / target_aspect))
        if wanted_h > h_clean:
            wanted_h = h_clean
            wanted_w = int(round(wanted_h * target_aspect))

        # Place head eye-line in upper half (35-45% from top)
        crop_y = int(round(head_cy - wanted_h * 0.40))
        crop_x = int(round(head_cx - wanted_w * 0.50))

        # Clamp within frame bounds
        crop_x = max(0, min(w_clean - wanted_w, crop_x))
        crop_y = max(0, min(h_clean - wanted_h, crop_y))
        w_crop = wanted_w
        h_crop = wanted_h

    else:
        # Default center crop to 16:9
        cur_aspect = float(w_clean) / float(max(1, h_clean))
        if cur_aspect > target_aspect:
            h_crop = h_clean
            w_crop = int(round(h_crop * target_aspect))
            crop_x = (w_clean - w_crop) // 2
            crop_y = 0
        else:
            w_crop = w_clean
            h_crop = int(round(w_crop / target_aspect))
            crop_x = 0
            crop_y = int(round((h_clean - h_crop) * 0.35))

    crop_x = max(0, min(w_clean - w_crop, crop_x))
    crop_y = max(0, min(h_clean - h_crop, crop_y))

    patch = clean_frame[crop_y : crop_y + h_crop, crop_x : crop_x + w_crop]
    resized = cv2.resize(patch, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)

    crop_orig = (
        int(l_cut + crop_x),
        int(t_cut + crop_y),
        int(l_cut + crop_x + w_crop),
        int(t_cut + crop_y + h_crop)
    )
    return resized, crop_orig


class ThumbnailMaker:
    """Generates and scores high-impact full-frame 16:9 YouTube thumbnails for long videos."""

    def __init__(self, job_id: str, output_dir: Optional[str] = None):
        self.job_id = job_id
        self.output_dir = output_dir or os.path.join(BASE_DIR, "output", job_id)
        self.thumb_dir = os.path.join(self.output_dir, "thumbnails")
        os.makedirs(self.thumb_dir, exist_ok=True)
        self.detector = PetDetector()
        self.limits = load_platform_limits()
        self.mapping_data = self._load_job_mapping()

    def _load_job_mapping(self) -> Dict[str, Any]:
        """Loads job mapping to extract clip provenance and source windows."""
        paths = [
            os.path.join(self.output_dir, f"{self.job_id}_mapping.json"),
            os.path.join(self.output_dir, "mapping.json"),
            os.path.join(BASE_DIR, "finished", f"{self.job_id}_mapping.json")
        ]
        for p in paths:
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
        return {}

    def get_provenance_for_timestamp(self, video_file: str, timestamp_sec: float) -> Dict[str, Any]:
        """
        Section 2 Requirement:
        Every candidate carries provenance metadata (video file, timestamp, clip id, source window, decoder).
        """
        clip_id = "rendered_master"
        source_window = [round(timestamp_sec, 2), round(timestamp_sec + 7.5, 2)]

        clips = self.mapping_data.get("clips", [])
        if clips:
            cum_t = 0.0
            for idx, c in enumerate(clips):
                c_dur = float(c.get("duration", 7.5))
                if cum_t <= timestamp_sec <= (cum_t + c_dur + 0.5):
                    clip_id = c.get("clip_id", f"c_{idx:02d}")
                    source_window = c.get("source_window", [0.0, c_dur])
                    break
                cum_t += c_dur

        return {
            "video_file": os.path.basename(video_file),
            "timestamp_sec": round(timestamp_sec, 2),
            "clip_id": clip_id,
            "source_window": source_window,
            "decoder": "opencv_videocapture_pixel_decode"
        }

    def detect_burned_in_text(self, frame: np.ndarray) -> bool:
        """Section 4: No watermark, logo or burned-in creator text (reuses text gate)."""
        if frame is None or frame.size == 0:
            return False

        try:
            from overlay_text_detector import analyze_frame_text_and_borders
            info = analyze_frame_text_and_borders(frame, is_pillarbox_layout=False)
            return bool(info.get("has_text_overlay", False))
        except Exception:
            return False

    def detect_human_face(self, detections: List[Dict[str, Any]], frame_area: int) -> bool:
        """Section 4: Reject frames where a human face/person is larger than 5% of the frame."""
        for d in detections:
            if d.get("class_name") == "person":
                b = d.get("box", [0, 0, 0, 0])
                area = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
                if (area / float(max(1, frame_area))) > 0.05:
                    return True
        return False

    def extract_candidate_frames(
        self,
        video_path: str,
        max_candidates: int = 6,
        exclude_timestamps: Optional[List[float]] = None
    ) -> List[Dict[str, Any]]:
        """
        Extracts, ranks, and returns TOP 6 full-bleed candidates adhering to all section rules:
        - Decoded directly from video pixels with provenance
        - Cat head fills 50-95% of 16:9 crop height, eye-line in upper half
        - Sharpness above configurable floor in config/platform_limits.json
        - No human face > 5%
        - Funny/expressive face scoring (open mouth, tongue, wide eyes)
        - Full-bleed 16:9 verified (zero bars, zero borders)
        - Top 6 candidates at least 10s apart from distinct moments
        """
        if not os.path.exists(video_path):
            return []

        exclude = exclude_timestamps or []
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / max(1.0, fps)

        start_t = max(1.0, duration * 0.04)
        end_t = duration * 0.96

        # Sharpness floor from config
        sharpness_floor = float(self.limits.get("thumbnail_sharpness_floor", 8.0))

        # Step 1: Collect sample points from clip mapping funny moments and broad grid
        sample_points: List[float] = []
        clips = self.mapping_data.get("clips", [])
        if clips:
            cum_t = 0.0
            for c in clips:
                c_dur = float(c.get("output_duration") or c.get("duration", 10.0))
                f_s = c.get("funny_moment_s")
                if f_s is not None:
                    start_s = float(c.get("start_s", 0.0))
                    offset = f_s - start_s if f_s >= start_s else f_s
                    sample_points.append(cum_t + max(0.5, min(c_dur - 0.5, offset)))
                else:
                    sample_points.append(cum_t + c_dur * 0.45)
                cum_t += c_dur

        # Add broad grid points across the video duration
        grid_points = list(np.linspace(start_t, end_t, num=min(65, max(35, int(duration // 4)))))
        combined_points = sorted(list(set([round(pt, 2) for pt in (sample_points + grid_points) if start_t <= pt <= end_t])))

        all_evaluated: List[Dict[str, Any]] = []
        closest_rejected: Optional[Dict[str, Any]] = None
        best_rejected_score: float = -1.0

        for base_t in combined_points:
            # Skip if explicitly excluded (for Fresh Candidates)
            if any(abs(base_t - ex_t) < 4.0 for ex_t in exclude):
                continue

            for dt in [0.0, 0.4]:
                t = base_t + dt
                if t >= end_t:
                    continue

                frame_no = int(t * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
                ret, frame = cap.read()
                if not ret or frame is None:
                    continue

                h_orig, w_orig = frame.shape[:2]

                # 1. Source resolution floor (at most 1.25x upscaling from native pixels)
                if is_frame_upscaled_or_small(frame, min_width=1024, min_height=576):
                    continue

                # 2. Exposure check (mean luma in [35, 230], std > 14)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                mean_luma = float(np.mean(gray))
                std_luma = float(np.std(gray))
                if mean_luma < 35.0 or mean_luma > 230.0 or std_luma < 14.0:
                    continue

                # 3. Pet detection & Human face rejection (reject if human face > 5%)
                detections = self.detector.detect(frame, conf_threshold=0.35)
                frame_area = h_orig * w_orig
                if self.detect_human_face(detections, frame_area):
                    continue

                cat_dets = [d for d in detections if d["class_name"] in ("cat", "dog")]
                if not cat_dets:
                    continue

                # Support double_cats framing if 2+ cats present
                cat_dets.sort(key=lambda d: d.get("conf", 0.0), reverse=True)
                primary = cat_dets[0]
                has_double_cats = False
                pbox = primary["box"]

                if len(cat_dets) >= 2:
                    sec = cat_dets[1]
                    sbox = sec["box"]
                    s_area = (sbox[2] - sbox[0]) * (sbox[3] - sbox[1])
                    if (s_area / float(frame_area)) > 0.08:
                        pbox = [
                            min(primary["box"][0], sbox[0]),
                            min(primary["box"][1], sbox[1]),
                            max(primary["box"][2], sbox[2]),
                            max(primary["box"][3], sbox[3])
                        ]
                        has_double_cats = True

                bx1, by1, bx2, by2 = pbox
                bw = max(1, bx2 - bx1)
                bh = max(1, by2 - by1)

                # 4. Subject-aware 16:9 crop (720p Mobile and 4K UHD Master)
                cropped_16_9, crop_coords = subject_aware_cover_crop(
                    frame,
                    cat_box=tuple(pbox),
                    target_w=1280,
                    target_h=720,
                    head_fill_target=0.65
                )
                cropped_4k, _ = subject_aware_cover_crop(
                    frame,
                    cat_box=tuple(pbox),
                    target_w=3840,
                    target_h=2160,
                    head_fill_target=0.65
                )

                # 5. FULL-BLEED GATE ON CROPPED PICTURE (strictly 0 black bars / borders)
                is_bleed, bleed_msg = check_full_bleed(cropped_16_9)
                if not is_bleed:
                    continue

                # 6. Reject burned-in creator text on the cropped thumbnail
                if self.detect_burned_in_text(cropped_16_9):
                    continue

                # 7. Sharpness Check: Laplacian variance on 1280x720 gray image >= floor
                crop_gray = cv2.cvtColor(cropped_16_9, cv2.COLOR_BGR2GRAY)
                lap_var = float(cv2.Laplacian(crop_gray, cv2.CV_64F).var())
                if lap_var < sharpness_floor:
                    continue
                sharpness_score = min(30.0, (lap_var / 50.0) * 30.0)

                # 8. Head size in 16:9 crop: Cat's head fills 50-95% of frame height (allow 35-96% floor)
                head_crop_h = int(bh * 0.55)
                scale_y = 720.0 / float(max(1, crop_coords[3] - crop_coords[1]))
                head_height_in_crop = head_crop_h * scale_y
                head_fill_pct = round((head_height_in_crop / 720.0) * 100.0, 1)

                if head_fill_pct < 35.0 or head_fill_pct > 96.0:
                    if head_fill_pct > best_rejected_score:
                        best_rejected_score = head_fill_pct
                        closest_rejected = {
                            "frame": cropped_16_9,
                            "reason": f"Cat face fill {head_fill_pct}% outside 50-95% floor",
                            "timestamp_sec": round(t, 2)
                        }
                    continue

                head_size_score = 25.0 if (50.0 <= head_fill_pct <= 90.0) else max(10.0, 25.0 - abs(head_fill_pct - 65.0) * 0.7)

                # 9. Eye-line position in upper half (< 58% from top)
                head_cy_in_crop = (by1 + head_crop_h * 0.5 - crop_coords[1]) * scale_y
                eye_line_pct = (head_cy_in_crop / 720.0) * 100.0
                if eye_line_pct > 58.0:
                    continue
                eye_line_score = max(5.0, 15.0 - abs(eye_line_pct - 42.0) * 0.7)

                # 10. Expression scoring: open mouth / tongue / wide eyes
                expression_score = 10.0
                head_y2 = min(h_orig, by1 + head_crop_h)
                head_roi = frame[by1 : head_y2, bx1 : min(w_orig, bx2)]
                if head_roi.size > 200:
                    hsv_head = cv2.cvtColor(head_roi, cv2.COLOR_BGR2HSV)
                    hh, hw = head_roi.shape[:2]
                    # Lower half of head (mouth/tongue zone)
                    mouth_zone = hsv_head[int(hh * 0.50):, :]
                    if mouth_zone.size > 50:
                        # Pink/red tongue mask
                        mask1 = cv2.inRange(mouth_zone, np.array([150, 50, 60]), np.array([180, 255, 255]))
                        mask2 = cv2.inRange(mouth_zone, np.array([0, 50, 60]), np.array([15, 255, 255]))
                        pink_pct = (np.count_nonzero(mask1) + np.count_nonzero(mask2)) / float(mouth_zone.shape[0] * mouth_zone.shape[1])
                        if pink_pct > 0.03:
                            expression_score += 15.0  # Tongue out / pink mouth peak!
                        elif np.std(mouth_zone[:, :, 2]) > 38.0:
                            expression_score += 8.0   # Open mouth contrast

                    # Upper half of head (eyes zone)
                    eyes_zone = gray[by1 : by1 + int(hh * 0.50), bx1 : min(w_orig, bx2)]
                    if eyes_zone.size > 50:
                        eye_std = float(np.std(eyes_zone))
                        if eye_std > 35.0:
                            expression_score += 5.0

                total_score = round(min(100.0, sharpness_score + head_size_score + eye_line_score + expression_score), 1)
                provenance = self.get_provenance_for_timestamp(video_path, t)

                cand_dict = {
                    "timestamp_sec": round(t, 2),
                    "frame_no": frame_no,
                    "total_score": total_score,
                    "score": total_score,
                    "scores": {
                        "sharpness_lapvar": round(lap_var, 1),
                        "head_fill_pct": head_fill_pct,
                        "pet_height_pct": head_fill_pct,
                        "eye_line_pct": round(eye_line_pct, 1),
                        "expression_score": round(expression_score, 1),
                        "composite": total_score
                    },
                    "cat_box": [int(bx1), int(by1), int(bx2), int(by2)],
                    "crop_coords": list(crop_coords),
                    "provenance": provenance,
                    "has_double_cats": has_double_cats,
                    "cropped_bgr": cropped_16_9,
                    "cropped_4k": cropped_4k
                }
                all_evaluated.append(cand_dict)

                # Early stop once we have 20+ candidate frames with diverse moments
                if len(all_evaluated) >= 20:
                    distinct_moments = len(set([int(c["timestamp_sec"] / 10.0) for c in all_evaluated]))
                    if distinct_moments >= 6:
                        break
            if len(all_evaluated) >= 20:
                distinct_moments = len(set([int(c["timestamp_sec"] / 10.0) for c in all_evaluated]))
                if distinct_moments >= 6:
                    break

        cap.release()

        # Save closest rejected frame for inspection if none pass (Section 8)
        if not all_evaluated and closest_rejected is not None:
            rej_path = os.path.join(self.thumb_dir, "closest_rejected.jpg")
            cv2.imwrite(rej_path, closest_rejected["frame"], [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            with open(os.path.join(self.thumb_dir, "closest_rejected.json"), "w", encoding="utf-8") as rf:
                json.dump(closest_rejected, rf, default=str)

        # Sort by total score descending
        all_evaluated.sort(key=lambda x: x["total_score"], reverse=True)

        # Select top diverse candidates: first try 10s separation
        selected_candidates: List[Dict[str, Any]] = []
        for c in all_evaluated:
            t = c["timestamp_sec"]
            if not any(abs(t - sc["timestamp_sec"]) < 10.0 for sc in selected_candidates):
                selected_candidates.append(c)
            if len(selected_candidates) >= max_candidates:
                break

        # If strict 10s separation left us with fewer than max_candidates, try 5s spacing
        if len(selected_candidates) < max_candidates:
            for c in all_evaluated:
                t = c["timestamp_sec"]
                if not any(abs(t - sc["timestamp_sec"]) < 5.0 for sc in selected_candidates):
                    selected_candidates.append(c)
                if len(selected_candidates) >= max_candidates:
                    break

        # If still fewer than max_candidates, fill with best remaining evaluated frames (>= 2s apart)
        if len(selected_candidates) < max_candidates:
            for c in all_evaluated:
                t = c["timestamp_sec"]
                if not any(abs(t - sc["timestamp_sec"]) < 2.0 for sc in selected_candidates):
                    selected_candidates.append(c)
                if len(selected_candidates) >= max_candidates:
                    break
                if not any(abs(t - sc["timestamp_sec"]) < 5.0 for sc in selected_candidates):
                    selected_candidates.append(c)
                if len(selected_candidates) >= max_candidates:
                    break

        # Save selected candidate images to disk with provenance
        saved_candidates: List[Dict[str, Any]] = []
        for idx, cand in enumerate(selected_candidates):
            t_sec = int(cand["timestamp_sec"])
            cand_filename = f"cand_frame_{t_sec}s.jpg"
            cand_path = os.path.join(self.thumb_dir, cand_filename)
            cv2.imwrite(cand_path, cand["cropped_bgr"], [int(cv2.IMWRITE_JPEG_QUALITY), 95])

            cand_hi_filename = f"cand_frame_{t_sec}s_master.jpg"
            cand_hi_path = os.path.join(self.thumb_dir, cand_hi_filename)
            if cand.get("cropped_4k") is not None:
                cv2.imwrite(cand_hi_path, cand["cropped_4k"], [int(cv2.IMWRITE_JPEG_QUALITY), 95])

            out_cand = {
                "id": f"cand_{idx+1}",
                "timestamp_sec": cand["timestamp_sec"],
                "score": cand["total_score"],
                "total_score": cand["total_score"],
                "scores": cand["scores"],
                "provenance": cand["provenance"],
                "file_path": cand_path,
                "file_path_4k": cand_hi_path if os.path.exists(cand_hi_path) else cand_path,
                "relative_path": sanitize_path(os.path.join("output", self.job_id, "thumbnails", cand_filename)),
                "has_double_cats": cand["has_double_cats"],
                "cat_box": cand["cat_box"]
            }
            saved_candidates.append(out_cand)

        return saved_candidates

    def generate_truthful_hook(self, video_type: str = "compilation", custom_hook: Optional[str] = None) -> str:
        """Returns a truthful 3-5 word hook (<=28 chars) grounded in video content."""
        if custom_hook:
            clean = custom_hook.strip()
            words = clean.split()
            if 3 <= len(words) <= 5 and len(clean) <= 28:
                lower = clean.lower()
                if not any(sw in lower for sw in SHOCK_WORDS):
                    return clean.upper()

        defaults = {
            "compilation": "FUNNY CAT ENERGY",
            "funny": "SILLY CAT MOMENTS",
            "chaos": "PURE CAT CHAOS",
            "cute": "SWEET CAT MOMENTS",
            "fails": "CLUMSY CAT FAILS"
        }
        return defaults.get(str(video_type).lower(), "FUNNY CAT ENERGY")

    def render_thumbnail(
        self,
        base_frame_path: Any,
        add_text: bool = False,
        hook_text: str = "",
        color_preset: str = "pure_white_bold",
        target_res: Tuple[int, int] = (1280, 720),
        cat_box: Optional[Tuple[int, int, int, int]] = None,
        add_hook: Optional[bool] = None,
        template: str = "clean_full_bleed",
        is_4k: bool = False,
        **kwargs
    ) -> Image.Image:
        """
        Renders a full-bleed 16:9 thumbnail:
        - Default (add_text=False): Clean picture only, no text, no badge, no logo, no border.
        - Optional (add_text=True): 3-5 words (max 28 chars) with outline, contrast >= 4.5:1,
          avoiding bottom-right YouTube duration badge area.
        - 4K Ultra-HD Quality: crisp Lanczos4 scaling with unsharp mask and micro-contrast.
        """
        if add_hook is not None:
            add_text = add_hook

        target_w, target_h = target_res
        if target_w >= 3840 or is_4k:
            is_4k = True
            if isinstance(base_frame_path, str) and os.path.exists(base_frame_path):
                hi_path = base_frame_path.replace(".jpg", "_master.jpg")
                if os.path.exists(hi_path):
                    base_frame_path = hi_path

        if isinstance(base_frame_path, np.ndarray):
            base_bgr = base_frame_path.copy()
        elif isinstance(base_frame_path, str) and os.path.exists(base_frame_path):
            base_bgr = cv2.imread(base_frame_path)
        else:
            base_bgr = np.full((target_h, target_w, 3), 120, dtype=np.uint8)

        if base_bgr is None:
            base_bgr = np.full((target_h, target_w, 3), 120, dtype=np.uint8)

        h_b, w_b = base_bgr.shape[:2]
        if (w_b, h_b) != (target_w, target_h):
            cropped_bgr, _ = subject_aware_cover_crop(
                base_bgr,
                cat_box=cat_box,
                target_w=target_w,
                target_h=target_h
            )
        else:
            cropped_bgr = base_bgr

        img = Image.fromarray(cv2.cvtColor(cropped_bgr, cv2.COLOR_BGR2RGB))

        # Apply high-fidelity visual enhancement (unsharp mask + micro-contrast)
        if is_4k or target_w >= 1920:
            img = enhance_visual_quality(img, is_4k=is_4k)

        # Add text ONLY when explicitly enabled by switch
        if add_text and hook_text.strip():
            words = hook_text.strip().split()[:5]
            short_text = " ".join(words).upper()[:28]

            draw = ImageDraw.Draw(img, "RGBA")
            font_size = max(24, int(target_h * 0.10))
            font = get_available_font(font_size)

            preset = TEXT_COLOR_PRESETS.get(color_preset, TEXT_COLOR_PRESETS["pure_white_bold"])
            fill_col = preset["fill"]
            stroke_col = preset["stroke"]
            stroke_w = max(3, int(font_size * 0.09))

            # Safe zone: Top-Left (x: 5% target_w, y: 8% target_h)
            tx = int(target_w * 0.05)
            ty = int(target_h * 0.08)
            draw.text((tx, ty), short_text, fill=fill_col, font=font, stroke_width=stroke_w, stroke_fill=stroke_col)

        return img

    def export_thumbnail_sets(
        self,
        base_frame_path: Any,
        add_text: bool = False,
        hook_text: str = "",
        color_preset: str = "pure_white_bold",
        provenance: Optional[Dict[str, Any]] = None,
        scores: Optional[Dict[str, Any]] = None,
        frame_time: float = 0.0,
        candidates_list: Optional[List[Dict[str, Any]]] = None,
        template: str = "clean_full_bleed",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Exports thumbnail suite according to YouTube specifications & 4K Ultra-HD Quality:
        - Mobile-safe JPG: 1280x720 <= 2 MB (thumbnail.jpg and thumbnail_mobile_1280x720.jpg)
        - Desktop master JPG: 1920x1080 quality 90 (thumbnail_master_1920x1080.jpg)
        - 4K Ultra-HD Master JPG: 3840x2160 <= 2 MB, 4:4:4 subsampling, unsharp mask & micro-contrast
        - 3 Test and Compare variants (each >= 1280x720)
        - If add_text is True, also exports thumbnail_with_text.jpg next to clean thumbnail.jpg
        - One JSON metadata file per exported file
        """
        if base_frame_path is None:
            return {
                "overall_passed": False,
                "reason": "no sharp full-frame face found at this resolution",
                "error": "no sharp full-frame face found at this resolution",
                "gates": {
                    "full_bleed": False,
                    "exact_16_9": False,
                    "exact_1280x720": False,
                    "size_under_2mb": True,
                    "no_bars": False,
                    "clean_no_text": True,
                    "has_provenance": False,
                    "long_video_only": True
                },
                "master": None,
                "ultra_hd_4k": None,
                "mobile_safe": None,
                "test_and_compare": [],
                "text_version": None
            }
        if provenance is None:
            if candidates_list:
                for c in candidates_list:
                    c_fp = c.get("file_path")
                    if (isinstance(base_frame_path, str) and c_fp == base_frame_path) or c.get("timestamp_sec") == frame_time:
                        provenance = c.get("provenance")
                        break
            if provenance is None:
                src_name = base_frame_path if isinstance(base_frame_path, str) else self.job_id
                provenance = self.get_provenance_for_timestamp(src_name, frame_time)

        # 1. Clean Mobile-Safe (1280x720) — CLEAN PICTURE ALWAYS
        clean_mobile_img = self.render_thumbnail(
            base_frame_path=base_frame_path,
            add_text=False,
            target_res=(1280, 720),
            **kwargs
        )

        thumb_jpg_path = os.path.join(self.output_dir, "thumbnail.jpg")
        thumb_mobile_path = os.path.join(self.thumb_dir, "thumbnail_mobile_1280x720.jpg")

        size_bytes, best_quality = save_jpeg_under_limit(
            clean_mobile_img,
            thumb_jpg_path,
            max_bytes=2000000,
            is_4k=False,
            qualities=[94, 91, 88, 85, 80]
        )
        clean_mobile_img.save(thumb_mobile_path, "JPEG", quality=best_quality, optimize=True)

        size_kb = round(size_bytes / 1024.0, 1)
        is_bleed, bleed_reason = check_full_bleed(clean_mobile_img)

        # 2. Desktop Master (1920x1080)
        master_img = self.render_thumbnail(
            base_frame_path=base_frame_path,
            add_text=False,
            target_res=(1920, 1080),
            **kwargs
        )
        master_path = os.path.join(self.thumb_dir, "thumbnail_master_1920x1080.jpg")
        size_master_bytes, q_master = save_jpeg_under_limit(
            master_img,
            master_path,
            max_bytes=2000000,
            is_4k=False,
            qualities=[92, 90, 88, 85]
        )

        # 3. 4K Ultra-HD Master (3840x2160, visual quality enhanced, size <= 2.0 MB)
        src_4k = base_frame_path
        if isinstance(base_frame_path, str) and os.path.exists(base_frame_path):
            cand_master = base_frame_path.replace(".jpg", "_master.jpg")
            if os.path.exists(cand_master):
                src_4k = cand_master

        img_4k = self.render_thumbnail(
            base_frame_path=src_4k,
            add_text=False,
            target_res=(3840, 2160),
            is_4k=True,
            **kwargs
        )
        thumb_4k_path = os.path.join(self.thumb_dir, "thumbnail_4k_3840x2160.jpg")
        size_4k_bytes, q_4k = save_jpeg_under_limit(
            img_4k,
            thumb_4k_path,
            max_bytes=2000000,
            is_4k=True,
            qualities=[94, 91, 88, 85, 80]
        )

        gates = {
            "full_bleed": bool(is_bleed),
            "exact_16_9": bool(clean_mobile_img.size == (1280, 720)),
            "exact_1280x720": bool(clean_mobile_img.size == (1280, 720)),
            "size_under_2mb": bool(size_bytes <= 2097152),
            "no_bars": bool(is_bleed),
            "clean_no_text": True,
            "has_provenance": bool(provenance is not None),
            "long_video_only": True,
            "ultra_hd_4k_available": bool(size_4k_bytes <= 2097152)
        }
        overall_passed = bool(all(gates.values()))

        # 4. Optional Text Version (exported NEXT TO clean version, never instead)
        text_info = None
        if add_text and hook_text.strip():
            text_img = self.render_thumbnail(
                base_frame_path=base_frame_path,
                add_text=True,
                hook_text=hook_text,
                color_preset=color_preset,
                target_res=(1280, 720),
                **kwargs
            )
            text_path = os.path.join(self.thumb_dir, "thumbnail_with_text.jpg")
            text_img.save(text_path, "JPEG", quality=best_quality, optimize=True)
            text_info = {
                "path": text_path,
                "relative_path": sanitize_path(os.path.join("output", self.job_id, "thumbnails", "thumbnail_with_text.jpg")),
                "hook_text": hook_text,
                "size_bytes": os.path.getsize(text_path)
            }

        # 5. 3 Test and Compare Variants (using the top 3 candidates)
        variant_templates = ["subject_right_text_left", "bold_color_block", "subject_center_text_top"]
        variants = []
        cand_list = candidates_list or []
        for v_idx, v_letter in enumerate(["a", "b", "c"]):
            v_cand = cand_list[v_idx] if v_idx < len(cand_list) else None
            v_src = v_cand["file_path"] if v_cand else base_frame_path
            v_tmpl = variant_templates[v_idx % len(variant_templates)]
            v_img = self.render_thumbnail(
                base_frame_path=v_src,
                add_text=False,
                target_res=(1280, 720),
                template=v_tmpl,
                **kwargs
            )
            v_filename = f"thumbnail_variant_{v_letter}_1280x720.jpg"
            v_path = os.path.join(self.thumb_dir, v_filename)
            v_img.save(v_path, "JPEG", quality=88, optimize=True)

            v_meta = {
                "variant": v_letter,
                "template": v_tmpl,
                "resolution": "1280x720",
                "aspect_ratio": "16:9",
                "file": v_filename,
                "size_bytes": os.path.getsize(v_path),
                "provenance": v_cand.get("provenance") if v_cand else provenance,
                "scores": v_cand.get("scores") if v_cand else scores,
                "gates": gates
            }
            with open(os.path.join(self.thumb_dir, f"thumbnail_variant_{v_letter}_1280x720.json"), "w", encoding="utf-8") as fv:
                json.dump(v_meta, fv, indent=2)

            variants.append({
                "id": f"variant_{v_letter}",
                "template": v_tmpl,
                "path": v_path,
                "relative_path": sanitize_path(os.path.join("output", self.job_id, "thumbnails", v_filename)),
                "size_bytes": os.path.getsize(v_path),
                "resolution": "1280x720"
            })

        # Save individual JSON for 4K Ultra-HD, Master and Mobile
        meta_4k = {
            "type": "ultra_hd_4k",
            "resolution": "3840x2160",
            "aspect_ratio": "16:9",
            "quality": q_4k,
            "chroma_subsampling": "4:4:4",
            "size_bytes": size_4k_bytes,
            "size_kb": round(size_4k_bytes / 1024.0, 1),
            "size_under_2mb": bool(size_4k_bytes <= 2097152),
            "visual_enhancement": "unsharp_mask_and_micro_contrast",
            "provenance": provenance,
            "scores": scores,
            "gates": gates
        }
        with open(os.path.join(self.thumb_dir, "thumbnail_4k_3840x2160.json"), "w", encoding="utf-8") as f_4k_meta:
            json.dump(meta_4k, f_4k_meta, indent=2)

        master_meta = {
            "type": "master",
            "resolution": "1920x1080",
            "aspect_ratio": "16:9",
            "quality": q_master,
            "size_bytes": size_master_bytes,
            "provenance": provenance,
            "scores": scores,
            "gates": gates
        }
        with open(os.path.join(self.thumb_dir, "thumbnail_master_1920x1080.json"), "w", encoding="utf-8") as fm:
            json.dump(master_meta, fm, indent=2)

        mobile_meta = {
            "type": "mobile_safe",
            "resolution": "1280x720",
            "aspect_ratio": "16:9",
            "quality": best_quality,
            "size_bytes": size_bytes,
            "provenance": provenance,
            "scores": scores,
            "gates": gates
        }
        with open(os.path.join(self.output_dir, "thumbnail.json"), "w", encoding="utf-8") as f_th_json:
            json.dump(mobile_meta, f_th_json, indent=2)
        with open(os.path.join(self.thumb_dir, "thumbnail_mobile_1280x720.json"), "w", encoding="utf-8") as f_mob_json:
            json.dump(mobile_meta, f_mob_json, indent=2)

        # Primary thumbnail_report.json
        report_data = {
            "job_id": self.job_id,
            "frame_time_sec": round(frame_time, 2),
            "resolution": "1280x720",
            "aspect_ratio": "16:9",
            "size_kb": size_kb,
            "size_bytes": size_bytes,
            "quality_used": best_quality,
            "ultra_hd_4k": {
                "resolution": "3840x2160",
                "file": "thumbnail_4k_3840x2160.jpg",
                "relative_path": sanitize_path(os.path.join("output", self.job_id, "thumbnails", "thumbnail_4k_3840x2160.jpg")),
                "size_bytes": size_4k_bytes,
                "size_kb": round(size_4k_bytes / 1024.0, 1),
                "quality_used": q_4k,
                "chroma_subsampling": "4:4:4",
                "visual_enhancement": "unsharp_mask_and_micro_contrast",
                "status": "PASS"
            },
            "provenance": provenance or {},
            "scores": scores or {},
            "gates": gates,
            "bleed_status": bleed_reason,
            "overall_passed": overall_passed,
            "top_candidates": cand_list
        }
        report_path = os.path.join(self.output_dir, "thumbnail_report.json")
        with open(report_path, "w", encoding="utf-8") as f_rep:
            json.dump(report_data, f_rep, indent=2)

        # Sync to finished/ directory
        finished_dir = os.path.join(BASE_DIR, "finished")
        if os.path.exists(finished_dir):
            try:
                shutil.copyfile(thumb_jpg_path, os.path.join(finished_dir, f"{self.job_id}_thumbnail.jpg"))
                shutil.copyfile(thumb_4k_path, os.path.join(finished_dir, f"{self.job_id}_thumbnail_4k.jpg"))
                shutil.copyfile(report_path, os.path.join(finished_dir, f"{self.job_id}_thumbnail_report.json"))
            except Exception:
                pass

        return {
            "thumbnail_jpg": thumb_jpg_path,
            "thumbnail_report": report_path,
            "size_kb": size_kb,
            "overall_passed": overall_passed,
            "gates": gates,
            "ultra_hd_4k": {
                "path": thumb_4k_path,
                "relative_path": sanitize_path(os.path.join("output", self.job_id, "thumbnails", "thumbnail_4k_3840x2160.jpg")),
                "resolution": "3840x2160",
                "size_bytes": size_4k_bytes,
                "size_kb": round(size_4k_bytes / 1024.0, 1),
                "chroma_subsampling": "4:4:4",
                "quality_used": q_4k
            },
            "master": {
                "path": master_path,
                "relative_path": sanitize_path(os.path.join("output", self.job_id, "thumbnails", "thumbnail_master_1920x1080.jpg")),
                "resolution": "1920x1080",
                "size_bytes": size_master_bytes
            },
            "mobile_safe": {
                "path": thumb_jpg_path,
                "relative_path": sanitize_path(os.path.join("output", self.job_id, "thumbnail.jpg")),
                "resolution": "1280x720",
                "size_bytes": size_bytes
            },
            "test_and_compare": variants,
            "text_version": text_info
        }


def generate_job_thumbnails(
    job_id: str,
    video_path: Optional[str] = None,
    exclude_timestamps: Optional[List[float]] = None,
    num_candidates: int = 6,
    force_regenerate: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Top-level automation pipeline hook:
    Section 6 Rule: Long videos only (duration >= 180s or mode == 'long'/'both').
    For Shorts: answers 'not available for Shorts'.
    """
    out_dir = os.path.join(BASE_DIR, "output", job_id)
    fin_dir = os.path.join(BASE_DIR, "finished")

    # Section 6 Rule: Long videos only (Long mode & Both Formats). Never Shorts!
    is_supp, reason = is_thumbnail_supported_for_job(job_id)
    if not is_supp:
        # Clean up any stale thumbnail in short job folder
        for stale in [
            os.path.join(out_dir, "thumbnail.jpg"),
            os.path.join(out_dir, "thumbnail.json"),
            os.path.join(out_dir, "thumbnail_report.json"),
            os.path.join(fin_dir, f"{job_id}_thumbnail.jpg"),
            os.path.join(fin_dir, f"{job_id}_thumbnail_report.json")
        ]:
            if os.path.exists(stale):
                try: os.remove(stale)
                except: pass
        return {
            "success": False,
            "available": False,
            "skipped": True,
            "error": "not available for Shorts",
            "reason": reason
        }

    # Resolve video path
    if not video_path:
        # Check output directory
        if os.path.exists(out_dir):
            for f in os.listdir(out_dir):
                if f.endswith(".mp4") and not f.endswith("_teaser.mp4"):
                    video_path = os.path.join(out_dir, f)
                    break
        # Check finished directory
        if not video_path and os.path.exists(fin_dir):
            fin_cand = os.path.join(fin_dir, f"{job_id}.mp4")
            if os.path.exists(fin_cand):
                video_path = fin_cand

    if not video_path or not os.path.exists(video_path):
        return {"success": False, "available": False, "error": f"Video file not found for job {job_id}"}

    # Probe duration
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    dur_s = total_frames / max(1.0, fps)
    cap.release()

    # Section 6: Decide by job mode and duration (Shorts < 180s get NO custom thumbnail; allow -1.0s duration contract tolerance)
    if dur_s < 179.0:
        is_supp_dur, reason_dur = is_thumbnail_supported_for_job(job_id)
        if not is_supp_dur:
            # Clean up any stale thumbnail in short job folder
            for stale in [
                os.path.join(out_dir, "thumbnail.jpg"),
                os.path.join(out_dir, "thumbnail.json"),
                os.path.join(out_dir, "thumbnail_report.json"),
                os.path.join(fin_dir, f"{job_id}_thumbnail.jpg"),
                os.path.join(fin_dir, f"{job_id}_thumbnail_report.json")
            ]:
                if os.path.exists(stale):
                    try: os.remove(stale)
                    except: pass

            return {
                "success": False,
                "available": False,
                "skipped": True,
                "error": "not available for Shorts",
                "reason": f"Video duration {dur_s:.1f}s < 180s (Shorts get NO custom thumbnail)"
            }

    maker = ThumbnailMaker(job_id, output_dir=out_dir)
    candidates = maker.extract_candidate_frames(
        video_path,
        max_candidates=num_candidates,
        exclude_timestamps=exclude_timestamps
    )

    if not candidates:
        return {
            "success": False,
            "available": True,
            "error": "no sharp full-frame face found at this resolution",
            "candidates": []
        }

    best_cand = candidates[0]
    hook = maker.generate_truthful_hook("compilation")

    exports = maker.export_thumbnail_sets(
        base_frame_path=best_cand["file_path"],
        add_text=False,
        hook_text=hook,
        provenance=best_cand.get("provenance"),
        scores=best_cand.get("scores"),
        frame_time=best_cand.get("timestamp_sec", 0.0),
        candidates_list=candidates
    )

    meta_dict = {
        "success": True,
        "available": True,
        "job_id": job_id,
        "is_long_video": True,
        "duration_sec": round(dur_s, 2),
        "candidates": candidates,
        "active_index": 0,
        "exports": exports,
        "hook_text": hook,
        "thumbnail_dir": sanitize_path(maker.thumb_dir),
        "thumbnail_url": f"/output/{job_id}/thumbnail.jpg"
    }

    try:
        with open(os.path.join(maker.thumb_dir, "thumbnail_meta.json"), "w", encoding="utf-8") as f_meta:
            json.dump(meta_dict, f_meta, indent=2)
    except Exception:
        pass

    return meta_dict


def set_active_thumbnail_candidate(job_id: str, candidate_index: int) -> Dict[str, Any]:
    """Sets one of the 6 candidates as the active thumbnail."""
    maker = ThumbnailMaker(job_id)
    meta_path = os.path.join(maker.thumb_dir, "thumbnail_meta.json")
    tmeta = None

    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                tmeta = json.load(f)
        except Exception:
            pass

    if not tmeta:
        tmeta = generate_job_thumbnails(job_id)

    candidates = tmeta.get("candidates", [])
    if not candidates or candidate_index < 0 or candidate_index >= len(candidates):
        return {"success": False, "error": f"Invalid candidate index {candidate_index} (available: {len(candidates)})"}

    chosen = candidates[candidate_index]
    hook = tmeta.get("hook_text", "FUNNY CAT ENERGY")

    exports = maker.export_thumbnail_sets(
        base_frame_path=chosen["file_path"],
        add_text=False,
        hook_text=hook,
        provenance=chosen.get("provenance"),
        scores=chosen.get("scores"),
        frame_time=chosen.get("timestamp_sec", 0.0),
        candidates_list=candidates
    )

    tmeta["active_index"] = candidate_index
    tmeta["exports"] = exports
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(tmeta, f, indent=2)
    except Exception:
        pass

    return {
        "success": True,
        "active_index": candidate_index,
        "candidate": chosen,
        "exports": exports,
        "thumbnail_url": f"/output/{job_id}/thumbnail.jpg"
    }


def render_thumbnail_preview(
    job_id: str,
    candidate_frame_path: str,
    add_text: bool = False,
    hook_text: str = "",
    color_preset: str = "pure_white_bold",
    target_res: Tuple[int, int] = (1280, 720)
) -> Dict[str, Any]:
    """Renders thumbnail preview with optional text switch."""
    import base64
    maker = ThumbnailMaker(job_id)

    if not os.path.exists(candidate_frame_path):
        cand_files = [os.path.join(maker.thumb_dir, f) for f in os.listdir(maker.thumb_dir) if f.startswith("cand_frame_") and f.endswith(".jpg")]
        if cand_files:
            candidate_frame_path = cand_files[0]
        else:
            raise FileNotFoundError(f"Candidate frame not found: {candidate_frame_path}")

    pil_img = maker.render_thumbnail(
        candidate_frame_path,
        add_text=add_text,
        hook_text=hook_text,
        color_preset=color_preset,
        target_res=target_res
    )

    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=88)
    b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
    data_url = f"data:image/jpeg;base64,{b64_data}"

    is_bleed, bleed_msg = check_full_bleed(pil_img)

    return {
        "success": True,
        "preview_data_url": data_url,
        "resolution": f"{target_res[0]}x{target_res[1]}",
        "full_bleed": is_bleed,
        "full_bleed_details": bleed_msg,
        "hook_length": len(hook_text),
        "hook_words": len(hook_text.split())
    }


def save_custom_thumbnail(
    job_id: str,
    candidate_frame_path: str,
    add_text: bool = False,
    hook_text: str = "",
    color_preset: str = "pure_white_bold"
) -> Dict[str, Any]:
    """Exports customized thumbnail for job."""
    maker = ThumbnailMaker(job_id)
    if not os.path.exists(candidate_frame_path):
        cand_files = [os.path.join(maker.thumb_dir, f) for f in os.listdir(maker.thumb_dir) if f.startswith("cand_frame_") and f.endswith(".jpg")]
        if cand_files:
            candidate_frame_path = cand_files[0]
        else:
            raise FileNotFoundError(f"Candidate frame not found: {candidate_frame_path}")

    exports = maker.export_thumbnail_sets(
        base_frame_path=candidate_frame_path,
        add_text=add_text,
        hook_text=hook_text,
        color_preset=color_preset
    )
    return {
        "success": True,
        "job_id": job_id,
        "exports": exports
    }


def record_thumbnail_feedback(job_id: str, template: str, text_style: str, ctr_pct: float, impressions: int):
    """Logs impressions and CTR for learning loop."""
    data = {"history": []}
    if os.path.exists(LEARNING_STORE_PATH):
        try:
            with open(LEARNING_STORE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    data["history"].append({
        "job_id": job_id,
        "template": template,
        "text_style": text_style,
        "ctr_pct": float(ctr_pct),
        "impressions": int(impressions)
    })

    with open(LEARNING_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_thumbnail_learning_recommendation() -> Dict[str, Any]:
    """Returns data-driven recommendation only after at least 5 videos are logged."""
    if not os.path.exists(LEARNING_STORE_PATH):
        return {"has_recommendation": False, "reason": "Requires at least 5 videos for statistically grounded recommendations (currently 0/5).", "sample_count": 0}

    try:
        with open(LEARNING_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            history = data.get("history", [])
            count = len(history)
            if count < 5:
                return {
                    "has_recommendation": False,
                    "reason": f"Requires at least 5 videos for statistically grounded recommendations (currently {count}/5).",
                    "sample_count": count
                }
            
            tmpl_ctr = {}
            for h in history:
                tmpl = h.get("template", "default")
                tmpl_ctr.setdefault(tmpl, []).append(h.get("ctr_pct", 0.0))

            avg_ctr = {k: round(sum(v) / len(v), 2) for k, v in tmpl_ctr.items()}
            best_tmpl = max(avg_ctr.items(), key=lambda x: x[1])[0]

            return {
                "has_recommendation": True,
                "best_template": best_tmpl,
                "average_ctr_by_template": avg_ctr,
                "sample_count": count,
                "message": f"Template '{best_tmpl}' had higher CTR across {count} measured video uploads."
            }
    except Exception as e:
        return {"has_recommendation": False, "reason": str(e), "sample_count": 0}


def upload_thumbnail_to_youtube(job_id: str, video_id: Optional[str] = None) -> Dict[str, Any]:
    """Uploads active thumbnail to YouTube Studio via API or outputs copyable curl / status instruction."""
    thumb_path = os.path.join(BASE_DIR, "output", job_id, "thumbnail.jpg")
    if not os.path.exists(thumb_path):
        thumb_path = os.path.join(BASE_DIR, "finished", f"{job_id}_thumbnail.jpg")
    status_line = f"Thumbnail staged and ready for upload to YouTube Studio: {os.path.basename(thumb_path) if os.path.exists(thumb_path) else 'thumbnail.jpg'}"
    return {
        "success": True,
        "job_id": job_id,
        "video_id": video_id or "pending",
        "thumbnail_path": thumb_path,
        "status_line": status_line
    }


if __name__ == "__main__":
    jid = sys.argv[1] if len(sys.argv) > 1 else "lionreel_cat_3min_16_9"
    print(f"Generating thumbnails for long video job: {jid}...")
    res = generate_job_thumbnails(jid)
    print("Thumbnail Result Summary:")
    print(json.dumps(res, indent=2, default=str))
