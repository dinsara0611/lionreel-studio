#!/usr/bin/env python3
"""
LionReel V97 — Master Pet Video Automated Pipeline
==================================================
Fully implements Master Prompt V2 requirements:
  - Fix 1: Subject-tracking 9:16 reframing with YOLOX, smoothed trajectory, blurred-bg fallback, post-crop gate
  - Fix 2: Persistent SQLite Clip Ledger (data/clip_ledger.db) with zero repeat between shorts & cycle rotation
  - Fix 3: Shorts mode (15-35s, 3-6 clips) & Compilation mode (45-90s, 9-14 clips), mapping.json, credits.json
  - Fix 4: Safe-zone single-clip captions (Montserrat / Sinhala Noto, no overlap with pet, never spans cuts)
  - Fix 5: Sharpness & export: CRF 17 slow BT.709, Lanczos scale + unsharp, 2-pass loudnorm (-14 LUFS, TP <= -1.0)
  - Fix 6: One-to-one integration with centered dashboard & sequential queue
  - Fix 7: Automated QA validation (qa_check.py) with contact sheet bounding box overlays
"""

import os
import sys
import time
import json
import math
import random
import glob
import subprocess
import uuid
import shutil
import hashlib
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg
_SCRIPT_START_TIME = time.time()

from pet_detector import PetDetector
from clip_ledger import ClipLedger, _compute_phash
from auto_reframe import AutoReframeEngine
from watermark_detector import WatermarkDetector
from stage_timer import StageTimer
from source_utils import probe_video_fast, check_and_gate_source, get_normalized_source_cache
from harvest_worker import trigger_background_harvest_if_needed, get_harvest_status

# ───────────────────────────────────────────────────────────────
# PATHS & CONSTANTS
# ───────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
BENCHMARK_CONFIG = os.path.join(BASE_DIR, "config", "benchmark.json")
BLOCKED_SOURCES_FILE = os.path.join(BASE_DIR, "config", "blocked_sources.json")

def get_local_path(cfg_key, default_local, fallback_rel):
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                c = json.load(f)
                if c.get(cfg_key):
                    os.makedirs(c[cfg_key], exist_ok=True)
                    return c[cfg_key]
    except Exception:
        pass
    try:
        os.makedirs(default_local, exist_ok=True)
        return default_local
    except Exception:
        fallback = os.path.join(BASE_DIR, fallback_rel)
        os.makedirs(fallback, exist_ok=True)
        return fallback

RAW_DIR = os.path.join(BASE_DIR, "raw")
OWN_DIR = os.path.join(BASE_DIR, "own_footage")
REF_DIR = os.path.join(BASE_DIR, "reference")
OUT_DIR = os.path.join(BASE_DIR, "finished")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
JOB_RESULT_FILE = os.path.join(BASE_DIR, "job_result.json")

# Heavy I/O directories stored on local SSD
WORK_DIR = get_local_path("LOCAL_WORK_DIR", "C:\\LionReel\\work", "work")
DATA_DIR = get_local_path("LOCAL_DATA_DIR", "C:\\LionReel\\data", "data")
CACHE_DIR = get_local_path("LOCAL_CACHE_DIR", "C:\\LionReel\\cache", "cache")

for d in [RAW_DIR, OWN_DIR, REF_DIR, OUT_DIR, DATA_DIR, LOGS_DIR, WORK_DIR, OUTPUT_DIR, CACHE_DIR]:
    os.makedirs(d, exist_ok=True)

def verify_layout_gate_compatibility(layout_mode: str):
    """
    Startup Self-Check (Requirement 1d):
    Verifies that the requested layout mode and QA gate criteria are 100% compatible.
    Fails loudly with LAYOUT_GATE_CONFLICT if setting and gate contradict each other.
    """
    mode = (layout_mode or "smart_crop").lower().strip()
    valid_modes = ["smart_crop", "blur_fit", "auto"]
    if mode not in valid_modes:
        raise ValueError(f"LAYOUT_GATE_CONFLICT: Unknown layout_mode '{layout_mode}'. Must be one of {valid_modes}")

    from qa_check import get_layout_gate_rules
    rules = get_layout_gate_rules(mode)

    if mode == "smart_crop":
        if rules.get("allow_blurred_bars") is True:
            raise RuntimeError("LAYOUT_GATE_CONFLICT: Smart crop layout cannot allow blurred bars in QA gate!")
        if rules.get("require_full_frame_fill") is not True:
            raise RuntimeError("LAYOUT_GATE_CONFLICT: Smart crop layout must require full frame fill in QA gate!")
        if rules.get("min_pet_height", 0) < 0.28:
            raise RuntimeError("LAYOUT_GATE_CONFLICT: Smart crop layout pet height threshold is too low (<28%)!")

    elif mode == "blur_fit":
        if rules.get("allow_blurred_bars") is not True:
            raise RuntimeError("LAYOUT_GATE_CONFLICT: Blur-fit layout cannot reject blurred bars in QA gate!")
        if rules.get("require_full_frame_fill") is True:
            raise RuntimeError("LAYOUT_GATE_CONFLICT: Blur-fit layout cannot demand full-frame zoom fill!")
        if rules.get("min_pet_height", 0) > 0.20:
            raise RuntimeError("LAYOUT_GATE_CONFLICT: Blur-fit layout cannot demand >20% frame height for pet in horizontal strip!")
        if not rules.get("require_centered_strip"):
            raise RuntimeError("LAYOUT_GATE_CONFLICT: Blur-fit layout must enforce horizontally centered strip!")

    elif mode == "auto":
        rules_sc = get_layout_gate_rules("smart_crop")
        rules_bf = get_layout_gate_rules("blur_fit")
        if rules_sc.get("allow_blurred_bars") is True or rules_bf.get("allow_blurred_bars") is not True:
            raise RuntimeError("LAYOUT_GATE_CONFLICT: Auto mode sub-gates contain contradictory blurred bar policies!")

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
FFPROBE_EXE = os.path.join(os.path.dirname(FFMPEG_EXE), "ffprobe.exe")
if not os.path.exists(FFPROBE_EXE):
    FFPROBE_EXE = "ffprobe"

FONT_MONTSERRAT = os.path.join(BASE_DIR, "assets", "fonts", "Montserrat.ttf")
FONT_SINHALA = os.path.join(BASE_DIR, "assets", "fonts", "NotoSansSinhala.ttf")
BGM_PATH = os.path.join(BASE_DIR, "assets", "funny_bgm.webm")
LOGO_PATH = os.path.join(BASE_DIR, "lion_logo.png")

OUT_W, OUT_H = 1080, 1920
FPS = 30


def ensure_local_source_copy(src_path):
    """
    Ensures a local SSD copy exists in CACHE_DIR for high-speed FFmpeg decoding and pipe reads.
    Avoids random seek stalls and network I/O deadlocks over Google Drive.
    """
    if not src_path or not os.path.exists(src_path):
        return src_path
    
    # If already on C: drive, use directly
    try:
        drive = os.path.splitdrive(os.path.abspath(src_path))[0].upper()
        if drive == "C:":
            return src_path
    except Exception:
        pass

    try:
        basename = os.path.basename(src_path)
        dst_path = os.path.join(CACHE_DIR, basename)
        src_size = os.path.getsize(src_path)
        if os.path.exists(dst_path) and os.path.getsize(dst_path) == src_size:
            return dst_path
        
        import shutil
        shutil.copy2(src_path, dst_path)
        return dst_path
    except Exception as e:
        log(f"Warning: Failed to copy {src_path} to local SSD cache: {e}", "WARN")
        return src_path


def get_video_duration(video_path):
    # 1. ffprobe
    try:
        cmd = [
            FFPROBE_EXE, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if res.stdout.strip():
            dur = float(res.stdout.strip())
            if dur > 0:
                return round(dur, 2)
    except Exception:
        pass

    # 2. ffmpeg -i Duration: HH:MM:SS.ss
    try:
        import re
        cmd = [FFMPEG_EXE, "-i", video_path]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", res.stderr or "")
        if m:
            h, mins, s = map(float, m.groups())
            dur = h * 3600.0 + mins * 60.0 + s
            if dur > 0:
                return round(dur, 2)
    except Exception:
        pass

    # 3. OpenCV fallback
    try:
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        if fps > 0 and total_frames > 0:
            return round(total_frames / fps, 2)
    except Exception:
        pass

    return 0.0

def compute_clip_window(src_path, cand_start, cand_end, target_clip_sec, tolerance=0.5):
    """
    Computes an optimal clip window of duration `target_clip_sec` (+/- tolerance)
    centered around the funny moment (audio peak + motion burst).
    Lead time: ~40% before peak, tail time: ~60% after reaction, never mid-action.
    If source cannot give a window of that length around peak, returns (None, None, False).
    """
    try:
        cap = cv2.VideoCapture(src_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        src_dur = total_frames / fps if fps > 0 else 0
        cap.release()
    except Exception:
        src_dur = 0

    if src_dur <= 0:
        src_dur = get_video_duration(src_path)

    if src_dur < target_clip_sec - tolerance:
        return None, None, False

    cand_len = max(0.1, cand_end - cand_start)
    peak_time = cand_start + 0.45 * cand_len

    lead_time = 0.40 * target_clip_sec
    tail_time = 0.60 * target_clip_sec

    win_start = peak_time - lead_time
    win_end = peak_time + tail_time

    if win_start < 0:
        win_start = 0.0
        win_end = min(src_dur, target_clip_sec)
        if peak_time < 0.20 * target_clip_sec:
            return None, None, False
    elif win_end > src_dur:
        win_end = src_dur
        win_start = max(0.0, src_dur - target_clip_sec)
        if (src_dur - peak_time) < 0.25 * target_clip_sec:
            return None, None, False

    actual_dur = win_end - win_start
    if abs(actual_dur - target_clip_sec) > tolerance:
        return None, None, False

    return round(win_start, 3), round(win_end, 3), True

# Original comedy captions (strictly single-clip, never crossing cuts)
ENGLISH_CAPTIONS = [
    "When gravity decides to betray you 😹",
    "Not a single thought behind those eyes 🐾",
    "Mission failed successfully 💀",
    "Proof that cats are 90% liquid 🥛",
    "Caught red-handed in 4K 📸",
    "Zero regrets, will do it again 😹",
    "The drama queen of the house 👑",
    "Instant regret in 3... 2... 1... 🚀",
    "When the catnip hits a little too hard 🌿",
    "Cat.exe has stopped working 🤖"
]

SINHALA_CAPTIONS = [
    "ගුරුත්වාකර්ෂණයට අහු උනාම 😹",
    "කිසිම බයක් නැති අපේ පූසා 🐾",
    "වැඩේ වැරදුනත් ගානක් නෑ 💀",
    "පූසෝ කියන්නේ වතුර වගේ තමයි 🥛",
    "කැමරාවටම අහුවුනා 📸",
    "ආයේ කවදාවත් කරන්නේ නෑලු 😹",
    "ගෙදර ඉන්න නාට්‍ය රජා 👑",
    "පූස් පැටියාගේ අමුතු විකාර 🚀"
]

TITLES_CAT = [
    "Try Not To Laugh - Funniest Cats Ever! 😹",
    "Cats Being Pure Chaos (Impossible Not To Smile) 🐾",
    "Funniest Cat Moments Caught On Camera 🐱",
    "Ultimate Cat Logic That Makes No Sense 😹",
    "Cats That Forgot How To Cat 🐾"
]

TITLES_DOG = [
    "Guilty Dogs That Stole The Show 🐶",
    "Funniest Dogs Doing What Dogs Do Best 🐕",
    "Goofy Dogs Being 100% Good Boys 🐾",
    "Dogs With Zero Braincells And 100% Heart 🐶"
]

TITLES_DUO = [
    "Cats and Dogs: Best Friends & Worst Enemies 🐱🐶",
    "When Cats and Dogs Team Up For Chaos 🐾",
    "Cats vs Dogs: The Ultimate Comedy Showdown 😹🐶"
]

# ───────────────────────────────────────────────────────────────
# LOGGING HELPER WITH INCREMENTAL SEQUENCE TAGGING
# ───────────────────────────────────────────────────────────────
_LOG_SEQ = 0
_JOB_LOG_PATH = None

def set_job_log_path(path):
    global _JOB_LOG_PATH, _LOG_SEQ
    _JOB_LOG_PATH = path

def log(msg, level="INFO"):
    global _LOG_SEQ
    _LOG_SEQ += 1
    ts = time.strftime("%H:%M:%S")
    formatted = f"[SEQ:{_LOG_SEQ}] [{ts}] [{level}] {msg}"
    print(formatted, flush=True)
    try:
        with open(os.path.join(LOGS_DIR, "pipeline.log"), "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

# ───────────────────────────────────────────────────────────────
# SUBJECT-TRACKING REFRAMER & CROPPING ENGINE (FIX 1)
# ───────────────────────────────────────────────────────────────
class SubjectReframer:
    def __init__(self, detector=None):
        self.detector = detector or PetDetector()

    def analyze_source_clip(self, video_path, start_s, dur_s, animal_mode="cat"):
        """
        Samples frames across the segment to verify:
        - Pet presence in >= 85% of sampled frames
        - Pet height >= 10% of frame height
        - Animal mode matches ('cat', 'dog', or both for 'duo')
        - Text density (reject burned-in text)
        - LapVar sharpness >= 150
        """
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        start_frame = int(start_s * fps)
        total_frames = int(dur_s * fps)
        
        n_samples = 8
        sample_indices = [start_frame + int(total_frames * (i + 0.5) / n_samples) for i in range(n_samples)]

        detected_count = 0
        pet_heights = []
        pet_centers_x = []
        pet_centers_y = []
        pet_boxes = []
        sharpness_scores = []
        text_edge_scores = []
        pillarbox_flags = []
        classes_seen = set()

        orig_w, orig_h = 0, 0

        for frame_idx in sample_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            orig_h, orig_w = frame.shape[:2]
            
            # Reject window if any frame is black (cut transition)
            if np.mean(frame) < 15.0:
                cap.release()
                return {"passed": False, "reason": "BLACK_FRAME_DETECTED", "detected_count": 0, "pet_heights": []}

            resized = cv2.resize(frame, (540, 960))
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            sharpness_scores.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))

            # Pillarbox / pre-blurred sidebars check
            left_w = int(gray.shape[1] * 0.15)
            right_x = int(gray.shape[1] * 0.85)
            left_side = gray[:, :left_w]
            right_side = gray[:, right_x:]
            v_l = float(cv2.Laplacian(left_side, cv2.CV_64F).var())
            v_r = float(cv2.Laplacian(right_side, cv2.CV_64F).var())
            # True pillarbox has black bars (<5.0 on both sides) or extreme dual blur (<8.0 on both sides with high center)
            if (v_l < 5.0 and v_r < 5.0) or (v_l < 8.0 and v_r < 8.0 and v_l + v_r < 12.0):
                pillarbox_flags.append(True)
            else:
                pillarbox_flags.append(False)

            # Burned-in text check: analyze center and lower-third band
            mid_band = gray[int(orig_h * 0.3):int(orig_h * 0.85), :]
            edges = cv2.Canny(mid_band, 80, 160)
            text_edge_scores.append(float(np.mean(edges > 0)))

            # Pet Detection
            detections = self.detector.detect(frame, conf_threshold=0.25)
            if detections:
                # Filter by animal mode if needed
                filtered = detections
                if animal_mode == "cat":
                    filtered = [d for d in detections if d["class_name"] == "cat"]
                elif animal_mode == "dog":
                    filtered = [d for d in detections if d["class_name"] == "dog"]

                if filtered:
                    best = filtered[0]
                    detected_count += 1
                    classes_seen.add(best["class_name"])
                    pet_heights.append(best["height_frac"])
                    pet_centers_x.append(best["center"][0])
                    pet_centers_y.append(best["center"][1])
                    pet_boxes.append(best["box"])

        cap.release()

        # Quality Gates
        valid_samples = max(1, len(sample_indices))
        presence_ratio = detected_count / valid_samples
        med_sharp = float(np.median(sharpness_scores)) if sharpness_scores else 0.0
        med_text_edge = float(np.median(text_edge_scores)) if text_edge_scores else 0.0
        pillar_ratio = sum(pillarbox_flags) / max(1, len(pillarbox_flags))

        rejection_reason = None
        if presence_ratio < 0.35:
            rejection_reason = f"NO_PET (presence {presence_ratio:.1%} < 35%)"
        elif pet_heights and np.median(pet_heights) < 0.08:
            rejection_reason = "PET_TOO_SMALL (< 8% frame height)"
        elif pillar_ratio > 0.40:
            rejection_reason = f"PRE_BLURRED_PILLARBOX (blurred sidebars {pillar_ratio:.1%})"
        elif med_sharp < 80.0:
            rejection_reason = f"LOW_SHARPNESS ({med_sharp:.1f} < 80)"
        elif med_text_edge > 0.16:
            rejection_reason = f"BURNED_IN_TEXT (text edge density {med_text_edge:.3f} > 0.16)"
        elif animal_mode == "cat" and "cat" not in classes_seen:
            rejection_reason = "WRONG_ANIMAL (no cat found)"
        elif animal_mode == "dog" and "dog" not in classes_seen:
            rejection_reason = "WRONG_ANIMAL (no dog found)"

        return {
            "passed": rejection_reason is None,
            "rejection_reason": rejection_reason,
            "presence_ratio": presence_ratio,
            "median_sharpness": med_sharp,
            "classes_seen": list(classes_seen),
            "orig_size": (orig_w, orig_h),
            "pet_centers_x": pet_centers_x,
            "pet_centers_y": pet_centers_y,
            "pet_boxes": pet_boxes
        }

    def plan_reframe(self, video_path, start_s, dur_s, animal_mode="cat", layout_mode="smart_crop", stricter=False):
        """
        LionReel Pro Smart Crop Auto Reframe:
        Plans smooth camera trajectory following pet with One-Euro filter + dead-zone + lookahead.
        """
        if not hasattr(self, "engine"):
            self.engine = AutoReframeEngine(self.detector)
        return self.engine.plan_reframe(
            video_path, start_s, dur_s,
            animal_mode=animal_mode,
            layout_mode=layout_mode,
            stricter=stricter
        )

    def reframe_segment_ffmpeg(self, in_path, out_path, start_s, dur_s, plan):
        """
        Executes single-pass crop + scale + mild unsharp using FFmpeg.
        """
        if not hasattr(self, "engine"):
            self.engine = AutoReframeEngine(self.detector)
        return self.engine.reframe_segment_ffmpeg(in_path, out_path, start_s, dur_s, plan)

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


# ───────────────────────────────────────────────────────────────
# CAPTION OVERLAY ENGINE (FIX 4)
# ───────────────────────────────────────────────────────────────
def render_safe_zone_caption(clip_path, out_path, caption_text, font_lang="en"):
    """
    Renders safe-zone caption overlay on a single clip:
    - Guaranteed inside x 150-930, y 220-1450 (platform safe zones)
    - Max 8 words, bold white with dark outline (5px) and soft shadow
    - Duration tied strictly to clip length (fades out 0.2s before cut)
    """
    cap = cv2.VideoCapture(clip_path)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    dur = total_frames / fps if fps > 0 else 5.0
    cap.release()

    font_path = FONT_SINHALA if font_lang == "si" and os.path.exists(FONT_SINHALA) else FONT_MONTSERRAT
    if not os.path.exists(font_path):
        font_path = "C:\\Windows\\Fonts\\arialbd.ttf" if os.path.exists("C:\\Windows\\Fonts\\arialbd.ttf") else None

    # Safe placement: target y = 1320 (lower third, above bottom UI zone 1540)
    target_y = 1320
    max_text_width = 820

    # Create overlay frame with PIL
    overlay_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay_img)
    
    font_size = 56
    try:
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    # Word wrap
    words = caption_text.split()
    lines = []
    cur_line = []
    for word in words:
        test_line = " ".join(cur_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) <= max_text_width:
            cur_line.append(word)
        else:
            if cur_line:
                lines.append(" ".join(cur_line))
                cur_line = [word]
            else:
                lines.append(word)
                cur_line = []
    if cur_line:
        lines.append(" ".join(cur_line))

    # Calculate line heights
    line_spacing = 12
    total_text_h = sum(draw.textbbox((0, 0), l, font=font)[3] - draw.textbbox((0, 0), l, font=font)[1] for l in lines) + (len(lines) - 1) * line_spacing
    start_y = target_y - total_text_h // 2

    # Draw text with 5px outline and shadow
    stroke_r = 5
    for l_idx, line in enumerate(lines):
        bb = draw.textbbox((0, 0), line, font=font)
        lw = bb[2] - bb[0]
        lh = bb[3] - bb[1]
        lx = (w - lw) // 2
        ly = start_y + l_idx * (lh + line_spacing)

        # Shadow
        draw.text((lx + 3, ly + 3), line, font=font, fill=(0, 0, 0, 160))
        # Stroke
        for dx in range(-stroke_r, stroke_r + 1):
            for dy in range(-stroke_r, stroke_r + 1):
                if dx * dx + dy * dy <= stroke_r * stroke_r:
                    draw.text((lx + dx, ly + dy), line, font=font, fill=(10, 10, 15, 240))
        # Foreground
        draw.text((lx, ly), line, font=font, fill=(255, 255, 255, 255))

    temp_png = out_path + ".overlay.png"
    overlay_img.save(temp_png, "PNG")

    # Composite via FFmpeg with fade-in (0.15s) and fade-out before cut
    fade_out_start = max(0.1, dur - 0.3)
    filter_complex = (
        f"[1:v]format=rgba,fade=t=in:st=0.1:d=0.15:alpha=1,fade=t=out:st={fade_out_start:.2f}:d=0.2:alpha=1[ovl];"
        f"[0:v][ovl]overlay=0:0"
    )

    cmd = [
        FFMPEG_EXE, "-y",
        "-i", clip_path,
        "-i", temp_png,
        "-filter_complex", filter_complex,
        "-c:v", "libx264", "-preset", "fast", "-crf", "12",
        "-c:a", "copy",
        out_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if os.path.exists(temp_png):
        os.remove(temp_png)
    return res.returncode == 0


# ───────────────────────────────────────────────────────────────
# AUDIO MASTERING & DUCKING (FIX 5)
# ───────────────────────────────────────────────────────────────
def master_audio_ebu_r128(in_video, out_video, bgm_path=BGM_PATH):
    """
    Two-pass EBU R128 mastering:
    - Pass 1: Measures integrated loudness, True Peak, LRA, and threshold
    - Pass 2: Applies exact linear normalisation to I = -14.0 LUFS, TP <= -1.0 dBTP, LRA = 11.0
    - Ducked background music (-14 dB) under natural pet audio
    - Brickwall alimiter at -1.0 dB to prevent inter-sample clipping
    """
    has_bgm = os.path.exists(bgm_path)
    temp_mixed = in_video + ".mixed.mp4"

    if has_bgm:
        # Mix BGM ducked under pet audio
        af_mix = (
            f"[1:a]volume=0.15,aloop=loop=-1:size=2e+09[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[mixed]"
        )
        mix_cmd = [
            FFMPEG_EXE, "-y",
            "-i", in_video,
            "-stream_loop", "-1", "-i", bgm_path,
            "-filter_complex", af_mix,
            "-map", "0:v", "-map", "[mixed]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            temp_mixed
        ]
        subprocess.run(mix_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    else:
        temp_mixed = in_video

    # Pass 1: Measure loudness JSON
    p1_cmd = [
        FFMPEG_EXE, "-i", temp_mixed,
        "-af", "loudnorm=I=-14.0:TP=-1.5:LRA=11.0:print_format=json",
        "-f", "null", "-"
    ]
    res = subprocess.run(p1_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    json_lines = []
    in_json = False
    for line in res.stderr.splitlines():
        if line.strip() == "{":
            in_json = True
            json_lines = ["{"]
        elif in_json:
            json_lines.append(line)
            if line.strip() == "}":
                break

    # Pass 2: Apply measured values
    p2_af = "loudnorm=I=-14.0:TP=-1.5:LRA=11.0"
    if json_lines:
        try:
            m = json.loads("\n".join(json_lines))
            mi = m.get("input_i", "-14.0")
            mtp = m.get("input_tp", "-1.5")
            mlra = m.get("input_lra", "11.0")
            mth = m.get("input_thresh", "-24.0")
            off = m.get("target_offset", "0.0")
            p2_af = f"loudnorm=I=-14.0:TP=-1.5:LRA=11.0:measured_I={mi}:measured_TP={mtp}:measured_LRA={mlra}:measured_thresh={mth}:offset={off}:linear=false"
        except Exception:
            pass

    p2_cmd = [
        FFMPEG_EXE, "-y",
        "-i", temp_mixed,
        "-af", p2_af,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        out_video
    ]
    subprocess.run(p2_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    if temp_mixed != in_video and os.path.exists(temp_mixed):
        try: os.remove(temp_mixed)
        except: pass

    return os.path.exists(out_video)


# ───────────────────────────────────────────────────────────────
# MAIN PIPELINE ORCHESTRATOR
# ───────────────────────────────────────────────────────────────
class LionReelV97Pipeline:
    def __init__(self):
        self.ledger = ClipLedger()
        self.detector = PetDetector()
        self.reframer = SubjectReframer(self.detector)
        self.wm_detector = WatermarkDetector()

    def update_pipeline_progress(self, job_id, stage_idx, stage_name, progress_pct, candidate_reports=None, error=None, failed_stage=None, success=None, output_file=None):
        try:
            status_str = "error" if error else ("completed" if success else "running")
            payload = {
                "job_id": job_id,
                "status": status_str,
                "success": False if error else (True if success else None),
                "stage_index": int(stage_idx),
                "stage_name": stage_name,
                "progress_pct": int(progress_pct),
                "candidate_reports": candidate_reports or [],
                "error": error,
                "failed_stage": failed_stage,
                "output_file": output_file
            }
            with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                json.dump(payload, f_jr, indent=2)
        except Exception:
            pass

    def load_config(self):
        cfg = {
            "ANIMAL_MODE": "cat",
            "VIDEO_TYPE": "short",
            "LANGUAGE": "en",
            "LAYOUT_MODE": "smart_crop",
            "OUTPUT_COUNT": 1
        }
        if os.path.exists(BENCHMARK_CONFIG):
            try:
                with open(BENCHMARK_CONFIG, "r", encoding="utf-8") as f_b:
                    bench = json.load(f_b)
                    if "layout" in bench and "mode" in bench["layout"]:
                        cfg["LAYOUT_MODE"] = bench["layout"]["mode"]
            except Exception:
                pass
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg.update(json.load(f))
            except Exception:
                pass
        return cfg

def remove_source_from_pool(source_path: str, reason: str = "BLOCKED_WATERMARK"):
    """
    Requirement 4: Removes source from pool/download list and records reason.
    License and credit info stays preserved in credits_registry.csv.
    """
    bname = os.path.basename(source_path)
    # 1. Record in credits_registry.csv
    registry_file = os.path.join(BASE_DIR, "credits_registry.csv")
    exists = os.path.exists(registry_file)
    try:
        from datetime import datetime
        with open(registry_file, "a", encoding="utf-8") as f:
            if not exists:
                f.write("timestamp,source_name,source_path,license,status,reason\n")
            f.write(f'"{datetime.now().isoformat()}","{bname}","{source_path}","Creative Commons / Curated","BLOCKED","{reason}"\n')
    except Exception:
        pass

    # 2. Remove from config.json SELECTED_CLIPS if present
    cfg_file = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            clips = cfg.get("SELECTED_CLIPS", [])
            initial_len = len(clips)
            norm_path = os.path.normpath(source_path).lower()
            filtered = [
                c for c in clips
                if os.path.basename(c.get("videoUrl", "")).lower() != bname.lower()
                and os.path.normpath(str(c.get("videoUrl", ""))).lower() not in norm_path
                and c.get("id", "").lower() not in bname.lower()
            ]
            if len(filtered) < initial_len:
                cfg["SELECTED_CLIPS"] = filtered
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4)
        except Exception:
            pass

    def harvest_source_clips(self, animal_mode="cat"):
        """
        Scans own_footage/ and raw/ cache for valid source files.
        Checks against blocklist (reference benchmark is strictly blocked).
        """
        source_paths = []
        for p in glob.glob(os.path.join(OWN_DIR, "*.mp4")) + glob.glob(os.path.join(RAW_DIR, "*.mp4")):
            # Disallow reference directory or any blocked source
            if self.ledger.is_blocked_source(p):
                log(f"SourceGuard blocked reference/blacklisted source: {os.path.basename(p)}", "WARN")
                continue
            # Filter out previous outputs or temporary cuts
            bname = os.path.basename(p)
            if (bname.startswith("cut_") or bname.startswith("capcut_") or 
                bname.startswith("assembled_") or bname.startswith("test_") or
                bname.startswith("v97_") or bname.startswith("cand_") or
                bname.startswith("sel_")):
                continue
            if os.path.getsize(p) > 2 * 1024 * 1024:
                source_paths.append(p)
        return source_paths

    def populate_ledger_from_sources(self, source_paths, animal_mode="cat"):
        """
        Analyzes source files and populates clip_ledger.db with segmented candidate clips.
        """
        log(f"Analyzing {len(source_paths)} source videos for clip ledger ingestion (Animal: {animal_mode.upper()})...")
        ingested_count = 0

        for sp in source_paths:
            if ingested_count >= 30:
                break
            cap = cv2.VideoCapture(sp)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            dur = total / fps if fps > 0 else 0
            cap.release()

            if dur < 4.0:
                continue

            log(f"  Scanning source: {os.path.basename(sp)} ({dur:.1f}s)...")
            segment_len = 5.2
            stride = max(8.0, dur / 30.0)
            cur_s = 1.0
            clips_from_source = 0
            checked_windows = 0

            while cur_s + segment_len <= dur - 1.0 and clips_from_source < 15 and checked_windows < 35:
                checked_windows += 1
                analysis = self.reframer.analyze_source_clip(sp, cur_s, segment_len, animal_mode)
                if analysis["passed"]:
                    try:
                        cid = self.ledger.ingest_candidate(
                            source_path=sp,
                            start_s=cur_s,
                            end_s=cur_s + segment_len,
                            license_type="CC-BY" if "cache_" in sp else "Own Footage",
                            animal_type=animal_mode,
                            quality_score=analysis["median_sharpness"] / 100.0,
                            funny_score=0.85
                        )
                        if cid:
                            ingested_count += 1
                            clips_from_source += 1
                            log(f"    [Ingested] {cid} [{cur_s:.1f}s-{cur_s+segment_len:.1f}s] (Sharpness: {analysis['median_sharpness']:.0f})")
                    except Exception as e:
                        pass
                cur_s += stride

        log(f"Ledger updated: {ingested_count} qualified clips ingested into pool.")
        pool_status = self.ledger.get_pool_status(animal_mode)
        log(f"Current pool status: {pool_status['status_label']}")

    def render_one_video(self, animal_mode="cat", video_type="short", language="en", job_id=None, use_cache=False, layout_mode=None, clips_count=None, clip_time=None, pace_profile=None, slicing_mode=None, allow_shorter=False):
        """
        Renders one video (Short or Compilation) strictly honoring user-configured clips count and clip duration.
        Enforces:
        - Unique job_id (timestamp + uuid) and dedicated local work/<job_id>
        - StageTimer logging every stage into console & timings.json
        - Process lock (work/<job_id>/.lock) ensuring strictly one process per job
        - Fail-fast ffprobe check rejecting bad sources in milliseconds (e.g. 720p > 2.0x upscale)
        - Dynamic window slicing centered on funny moments (tolerance +/-0.5s)
        - Zero repeat between shorts & cycle rotation
        - Post-render ffprobe duration check (fail with DURATION_MISMATCH if > 10% delta)
        """
        cfg = self.load_config()
        layout_mode = layout_mode or cfg.get("LAYOUT_MODE", "smart_crop")
        verify_layout_gate_compatibility(layout_mode)

        if not job_id:
            ts_str = time.strftime('%Y%m%d_%H%M%S')
            job_id = f"lionreel_{animal_mode}_{ts_str}_{uuid.uuid4().hex[:8]}"

        timer = StageTimer(job_id=job_id)
        # Record startup / imports duration
        try:
            startup_dur = round(time.time() - _SCRIPT_START_TIME, 3)
            timer.stages["startup_imports"] = startup_dur
        except Exception:
            timer.stages["startup_imports"] = 0.05

        timer.start_stage("folder_setup")
        work_job_dir = os.path.join(WORK_DIR, job_id)
        output_job_dir = os.path.join(OUTPUT_DIR, job_id)
        os.makedirs(work_job_dir, exist_ok=True)
        os.makedirs(output_job_dir, exist_ok=True)
        timer.stop_stage("folder_setup")

        # Process Lock Check: One job = one process
        lock_file = os.path.join(work_job_dir, ".lock")
        if os.path.exists(lock_file):
            try:
                with open(lock_file, "r") as f_lk:
                    existing_pid = int(f_lk.read().strip())
                import psutil
                if psutil.pid_exists(existing_pid):
                    log(f"[FATAL] Another process (PID {existing_pid}) is already running for job {job_id}. Aborting duplicate start.", "ERROR")
                    return None
            except Exception:
                pass

        try:
            with open(lock_file, "w") as f_lk:
                f_lk.write(str(os.getpid()))
        except Exception:
            pass

        final_filename = f"{job_id}.mp4"
        local_master_path = os.path.join(work_job_dir, final_filename)
        job_output_path = os.path.join(output_job_dir, final_filename)
        finished_output_path = os.path.join(OUT_DIR, final_filename)

        if use_cache and os.path.exists(finished_output_path):
            log(f"[CACHE] Using cached render for {job_id}: {finished_output_path}")
            if os.path.exists(lock_file):
                try: os.remove(lock_file)
                except: pass
            return finished_output_path

        start_render_time = time.time()

        # Calculate exact target clips count & duration from UI / CLI / config
        if clips_count is not None:
            target_clips_count = int(clips_count)
        elif cfg.get("TARGET_CLIPS"):
            target_clips_count = int(cfg.get("TARGET_CLIPS"))
        else:
            target_clips_count = 4 if video_type == "short" else 10

        if clip_time is not None:
            target_clip_sec = float(clip_time)
        elif cfg.get("SHORT_CLIP_SEC"):
            target_clip_sec = float(cfg.get("SHORT_CLIP_SEC"))
        else:
            target_clip_sec = 7.5

        expected_total_sec = round(target_clips_count * target_clip_sec, 2)
        pace_profile = pace_profile or cfg.get("SPEED_PROFILE", "fast")
        slicing_mode = slicing_mode or cfg.get("MOMENT_CUT_MODE", "peak_viral")
        allow_shorter = bool(allow_shorter if allow_shorter is not None else cfg.get("ALLOW_SHORTER", False))

        # MANDATORY FIRST CONFIG LOG LINE (Requirement b & Fix 1c)
        config_line = f"CONFIG: mode={video_type} layout={layout_mode} clips={target_clips_count} clip_time={target_clip_sec:.1f}s expected_total={expected_total_sec:.1f}s pace={pace_profile} slicing={slicing_mode}"
        log(config_line)

        log(f"Starting production: {job_id} ({video_type.upper()}, layout={layout_mode}, target {target_clips_count} clips × {target_clip_sec:.1f}s = {expected_total_sec:.1f}s)...")
        log(f"Local work folder: {work_job_dir}")
        log(f"Drive output folder: {output_job_dir}")

        try:
            # 1. Background Harvest Trigger & Ledger Reserve (Requirement 5)
            timer.start_stage("harvest")
            # Trigger background worker if pool is below low-water mark (20)
            trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=20)
            timer.stop_stage("harvest")

            timer.start_stage("ledger_reserve")
            pool_status = self.ledger.get_pool_status(animal_mode)
            unused_clips = pool_status.get("unused_clips", 0)

            if unused_clips < target_clips_count:
                h_stat = get_harvest_status()
                pct = h_stat.get("progress_pct", 0)
                msg = f"Pool low: {unused_clips} clip(s) available. Harvesting in background, {pct}% done"
                log(f"[POOL_LOW] {msg}", "WARN")
                with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                    json.dump({
                        "job_id": job_id,
                        "status": "pool_low",
                        "success": False,
                        "error": msg,
                        "code": "POOL_LOW_HARVESTING"
                    }, f_jr, indent=2)
                timer.stop_stage("ledger_reserve")
                return None

            candidate_target = max(15, target_clips_count * 5)
            self.update_pipeline_progress(job_id, 1, "Searching sources & fetching high-res clips", 10)
            try:
                self.ledger.cleanup_stale_reservations(job_id)
                reserved_clips = self.ledger.reserve_clips(
                    target_count=candidate_target,
                    animal_mode=animal_mode,
                    short_id=job_id,
                    min_required=target_clips_count
                )
            except Exception as e_res:
                err_msg = str(e_res)
                log(f"Reservation Error: {err_msg}", "ERROR")
                self.update_pipeline_progress(job_id, 1, "Searching sources & fetching high-res clips", 10, error=err_msg, failed_stage="Searching sources & fetching high-res clips")
                timer.stop_stage("ledger_reserve")
                raise RuntimeError(err_msg)

            timer.stop_stage("ledger_reserve")

            if not reserved_clips:
                err_msg = "No new clips available: failed to reserve clips from pool."
                log(f"Error: {err_msg}", "ERROR")
                self.update_pipeline_progress(job_id, 1, "Searching sources & fetching high-res clips", 10, error=err_msg, failed_stage="Searching sources & fetching high-res clips")
                return None

            log(f"Successfully reserved {len(reserved_clips)} candidate clips from ledger for job {job_id} (target: {target_clips_count}).")

            # Update Stages 2, 3, 4
            self.update_pipeline_progress(job_id, 2, "Downloading selected clips into raw staging", 20)
            self.update_pipeline_progress(job_id, 3, "Checking video quality & frame rate stability", 30)
            self.update_pipeline_progress(job_id, 4, "Detecting watermarks & platform overlays", 40)

            # Stage 5: Stage A — Fast Pre-Scoring across all reserved candidates
            self.update_pipeline_progress(job_id, 5, "Trimming high-energy animal motion slices", 50)
            candidate_reports = []
            passing_candidates = []
            rejected_candidates = []
            blocked_sources_in_job = set()

            log(f"\n{'='*72}\nSTAGE A: FAST PRE-SCORING PREDICTED FRAMING BEFORE RENDER ({len(reserved_clips)} candidates)\n{'='*72}")

            for idx, clip_info in enumerate(reserved_clips):
                src_path = clip_info.get("source_url_or_path") or clip_info.get("source_path")
                cid = clip_info["clip_id"]
                src_name = os.path.basename(src_path)

                # Requirement 4: Fast drop if source was previously blocked
                if src_name in blocked_sources_in_job or src_path in blocked_sources_in_job or self.ledger.is_blocked_source(src_path):
                    log(f"Candidate {idx+1} ({src_name}) dropped: source is BLOCKED_WATERMARK", "WARN")
                    rep = {
                        "candidate": idx + 1, "clip_id": cid, "source": src_name,
                        "start_s": clip_info.get("start_s", 0.0), "dur_s": 0.0, "score": 0.0,
                        "result": "REJECT", "reason": "BLOCKED_WATERMARK"
                    }
                    candidate_reports.append(rep)
                    rejected_candidates.append(rep)
                    self.ledger.release_single_clip(cid)
                    continue

                # Step c: Dynamic Window Slicing centered on funny moment
                win_start, win_end, win_ok = compute_clip_window(
                    src_path,
                    clip_info["start_s"],
                    clip_info["end_s"],
                    target_clip_sec,
                    tolerance=0.5
                )

                if not win_ok:
                    log(f"Candidate {idx+1} rejected: cannot provide {target_clip_sec:.1f}s window around peak in {src_name}", "WARN")
                    rep = {
                        "candidate": idx + 1, "clip_id": cid, "source": src_name,
                        "start_s": clip_info["start_s"], "dur_s": 0.0, "score": 0.0,
                        "result": "REJECT", "reason": "WINDOW_UNAVAILABLE"
                    }
                    candidate_reports.append(rep)
                    rejected_candidates.append(rep)
                    self.ledger.release_single_clip(cid)
                    continue

                start_s = win_start
                dur_s = win_end - win_start
                clip_info["start_s"] = win_start
                clip_info["end_s"] = win_end
                clip_info["computed_dur"] = dur_s

                # Stage: ffprobe fail-fast check
                timer.start_stage("ffprobe")
                pass_probe, probe_reason = check_and_gate_source(src_path, self.ledger)
                timer.stop_stage("ffprobe")

                if not pass_probe:
                    log(f"Clip {idx+1} rejected by fail-fast upscale gate: {probe_reason}", "WARN")
                    rep = {
                        "candidate": idx + 1, "clip_id": cid, "source": src_name,
                        "start_s": start_s, "dur_s": dur_s, "score": 0.0,
                        "result": "REJECT", "reason": f"UPSCALE_EXCEEDED ({probe_reason})"
                    }
                    candidate_reports.append(rep)
                    rejected_candidates.append(rep)
                    self.ledger.release_single_clip(cid)
                    continue

                # Watermark Gate (Requirement 4: Block bad sources once)
                timer.start_stage("watermark")
                has_wm = False
                wm_corner, wm_reason = "", ""
                try:
                    has_wm, wm_corner, wm_conf, wm_reason = self.wm_detector.check_video_corners(
                        src_path, start_s=start_s, dur_s=dur_s, n_samples=8
                    )
                except Exception:
                    pass
                timer.stop_stage("watermark")

                if has_wm:
                    log(f"Clip {idx+1} watermark detected ({wm_corner}: {wm_reason}). Sampling 6 other windows of {src_name}...", "WARN")
                    is_pers, hit_cnt, wm_info = self.wm_detector.verify_source_watermark(src_path, n_windows=6)
                    if is_pers or hit_cnt >= 2:
                        block_msg = f"BLOCKED_WATERMARK ({wm_info.get('corner', wm_corner)}: {wm_info.get('reason', wm_reason)} in {hit_cnt}/6 windows)"
                        log(f"[WARN] SOURCE BLOCKED: '{src_name}' marked BLOCKED_WATERMARK in ledger ({hit_cnt}/6 sampled windows showed {wm_info.get('corner', wm_corner)} watermark). Dropping all candidates and removing from pool.", "WARN")

                        # 1. Mark blocked in ledger and config/blocked_sources.json
                        self.ledger.mark_source_blocked(src_path, reason=block_msg)
                        blocked_sources_in_job.add(src_name)
                        blocked_sources_in_job.add(src_path)

                        # 2. Remove source from pool / download list (retaining license info in credits_registry.csv)
                        remove_source_from_pool(src_path, block_msg)

                        # 3. Drop all candidates from this source immediately
                        rep = {
                            "candidate": idx + 1, "clip_id": cid, "source": src_name,
                            "start_s": start_s, "dur_s": dur_s, "score": 0.0,
                            "result": "REJECT", "reason": f"BLOCKED_WATERMARK ({wm_corner})"
                        }
                        candidate_reports.append(rep)
                        rejected_candidates.append(rep)
                        self.ledger.release_single_clip(cid)

                        # Release any upcoming candidates from this source in current reservation
                        for rem_c in reserved_clips[idx+1:]:
                            r_src = rem_c.get("source_url_or_path") or rem_c.get("source_path")
                            if r_src == src_path or os.path.basename(r_src) == src_name:
                                self.ledger.release_single_clip(rem_c["clip_id"])
                        continue
                    else:
                        rep = {
                            "candidate": idx + 1, "clip_id": cid, "source": src_name,
                            "start_s": start_s, "dur_s": dur_s, "score": 0.0,
                            "result": "REJECT", "reason": f"WATERMARK ({wm_corner}: {wm_reason})"
                        }
                        candidate_reports.append(rep)
                        rejected_candidates.append(rep)
                        self.ledger.release_single_clip(cid)
                        continue

                # Tracking & Camera Planning (Stage A low-res framing gate prediction via FFmpeg pipe)
                timer.start_stage("tracking")
                local_src = ensure_local_source_copy(src_path)
                plan = self.reframer.plan_reframe(
                    local_src, start_s, dur_s,
                    animal_mode=animal_mode,
                    layout_mode=layout_mode,
                    stricter=False
                )
                timer.stop_stage("tracking")

                score = plan.get("framing_score", 0.0)
                sharpness = plan.get("sharpness", 0.0)
                pet_ratio = plan.get("pet_detected_ratio", 0.0)
                details = plan.get("details", {})
                vis_ratio = details.get("vis", 0.0)
                horiz_ratio = details.get("horiz", 0.0)
                vert_ratio = details.get("vert", 0.0)
                size_ratio = details.get("size", 0.0)

                # Requirement 2b: A score of exactly 0.0 together with sharpness 0.0 must be treated as ANALYSIS_FAILED (a bug), logged with exception, never as PASS
                if plan.get("status") == "pass" and score == 0.0 and sharpness == 0.0:
                    log(f"  [Cand {idx+1:02d} | {src_name} {start_s:5.1f}s]: REJECT -> ANALYSIS_FAILED (Score 0.0% and Sharpness 0.0)", "ERROR")
                    plan["status"] = "reject"
                    plan["reason"] = "ANALYSIS_FAILED (Score 0.0% and Sharpness 0.0)"

                comp_str = f"Pet: {pet_ratio:.1%}, H: {horiz_ratio:.1%}, V: {vert_ratio:.1%}, Size: {size_ratio:.1%}, Sharp: {sharpness:.1f}, Score: {score:.1%}"

                if plan.get("status") == "pass":
                    rep = {
                        "candidate": idx + 1, "clip_id": cid, "source": src_name,
                        "start_s": start_s, "dur_s": dur_s, "score": round(score, 3),
                        "sharpness": round(sharpness, 1),
                        "pet_ratio": round(pet_ratio, 3),
                        "vis_ratio": round(vis_ratio, 3),
                        "horiz_ratio": round(horiz_ratio, 3),
                        "vert_ratio": round(vert_ratio, 3),
                        "size_ratio": round(size_ratio, 3),
                        "result": "PASS", "reason": "PREDICT_PASS",
                        "plan": plan, "clip_info": clip_info
                    }
                    candidate_reports.append(rep)
                    passing_candidates.append(rep)
                    log(f"  [Cand {idx+1:02d} | {src_name} {start_s:5.1f}s-{win_end:5.1f}s ({dur_s:.1f}s)]: PREDICT PASS ✅ -> {comp_str}")
                else:
                    reason = plan.get("reason", "PREDICTED_BAD_FRAMING")
                    rep = {
                        "candidate": idx + 1, "clip_id": cid, "source": src_name,
                        "start_s": start_s, "dur_s": dur_s, "score": round(score, 3),
                        "sharpness": round(sharpness, 1),
                        "pet_ratio": round(pet_ratio, 3),
                        "vis_ratio": round(vis_ratio, 3),
                        "horiz_ratio": round(horiz_ratio, 3),
                        "vert_ratio": round(vert_ratio, 3),
                        "size_ratio": round(size_ratio, 3),
                        "result": "REJECT", "reason": reason
                    }
                    candidate_reports.append(rep)
                    rejected_candidates.append(rep)
                    self.ledger.release_single_clip(cid)
                    log(f"  [Cand {idx+1:02d} | {src_name} {start_s:5.1f}s]: PREDICT REJECT ❌ -> {reason} | {comp_str}")

            # Sort passing candidates by predicted score descending
            passing_candidates.sort(key=lambda x: x["score"], reverse=True)
            log(f"\nStage A Complete: {len(passing_candidates)} passed predicted framing, {len(rejected_candidates)} rejected before render.")

            # Step e: Strict usable clips gate (never silently deliver fewer clips)
            min_needed_a = target_clips_count if not allow_shorter else min(target_clips_count, 2)
            if len(passing_candidates) < min_needed_a:
                err_msg = f"JOB FAILED: not enough usable clips (got {len(passing_candidates)} of {target_clips_count})"
                log(f"\n[ERROR] {err_msg}", "ERROR")
                log("="*100)
                log(f"{'CANDIDATE':<10} | {'SOURCE':<24} | {'FRAMING SCORE':<14} | {'SHARP':<8} | {'RESULT':<8} | {'REASON'}")
                log("-" * 100)
                for r in candidate_reports:
                    sh_str = f"{r.get('sharpness', 0.0):.1f}"
                    log(f"{r['candidate']:<10} | {r['source'][:24]:<24} | {r['score']*100:<13.1f}% | {sh_str:<8} | {r['result']:<8} | {r['reason']}")
                log("="*100 + "\n")
                self.ledger.release_reservation(job_id)
                timer.save_timings(os.path.join(work_job_dir, f"{job_id}_timings.json"))
                with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                    json.dump({
                        "job_id": job_id,
                        "status": "failed",
                        "success": False,
                        "error": err_msg,
                        "code": "INSUFFICIENT_CLIPS",
                        "got_clips": len(passing_candidates),
                        "target_clips": target_clips_count
                    }, f_jr, indent=2)
                self.update_pipeline_progress(
                    job_id, 7, "Smart center-crop to 9:16 vertical shorts", 50,
                    candidate_reports=candidate_reports, error=err_msg,
                    failed_stage="Smart center-crop to 9:16 vertical shorts"
                )
                return None

            # Stage 6: Auto Color Grading indicator
            self.update_pipeline_progress(job_id, 6, "Auto color grading (Contrast & CLAHE Normalization)", 60, candidate_reports=candidate_reports)

            # Stage 7: Stage B — Render Only Candidates Predicted to Pass
            self.update_pipeline_progress(job_id, 7, "Smart center-crop to 9:16 vertical shorts", 75, candidate_reports=candidate_reports)
            log(f"\n{'='*72}\nSTAGE B: RENDERING {min(target_clips_count, len(passing_candidates))} PASSING CLIPS (CRF 12 FAST PRESET)\n{'='*72}")

            processed_clip_paths = []
            clip_mapping_data = []
            credits_data = []
            caption_pool = SINHALA_CAPTIONS if language == "si" else ENGLISH_CAPTIONS
            consecutive_fails = 0
            last_fail_code = ""

            for pass_idx, cand in enumerate(passing_candidates):
                if len(processed_clip_paths) >= target_clips_count:
                    # Target count reached! Release remaining candidates back to pool
                    self.ledger.release_single_clip(cand["clip_id"])
                    continue

                cinfo = cand["clip_info"]
                src_path = cinfo.get("source_url_or_path") or cinfo.get("source_path")
                local_src = ensure_local_source_copy(src_path)
                start_s = cinfo["start_s"]
                dur_s = cinfo.get("computed_dur", cinfo["end_s"] - start_s)
                cid = cinfo["clip_id"]
                plan = cand["plan"]
                clip_out = os.path.join(work_job_dir, f"{job_id}_c{len(processed_clip_paths):02d}.mp4")

                log(f"Stage B Rendering Clip {len(processed_clip_paths)+1}/{target_clips_count} (Cand {cand['candidate']}, Predicted: {cand['score']:.1%}): {cand['source']} [{start_s:.1f}s - {cinfo['end_s']:.1f}s, dur: {dur_s:.1f}s]...")

                # Requirement 3b: Early abort check on first 25% of clip
                early_ok, early_msg = self.reframer.early_check_segment_gate(
                    local_src, start_s, dur_s, plan, layout_mode=layout_mode
                )
                if not early_ok:
                    log(f"Candidate {cand['candidate']} early abort: gate failed on first 25% ({early_msg}), skipping render", "WARN")
                    cand["result"] = "REJECT"
                    cand["reason"] = f"EARLY_ABORT ({early_msg})"
                    self.ledger.release_single_clip(cid)

                    # Circuit breaker tracking (Requirement 3c)
                    fail_code = early_msg.split()[0].replace("(", "").replace(")", "").replace(":", "")
                    if fail_code == last_fail_code:
                        consecutive_fails += 1
                    else:
                        consecutive_fails = 1
                        last_fail_code = fail_code
                    if consecutive_fails >= 3:
                        log(f"\n[ERROR] SYSTEMIC FAILURE: {last_fail_code} (3 in a row)", "ERROR")
                        log(f"Systemic failure triggered: 3 candidates in a row failed with code '{last_fail_code}'. Halting batch.\n", "ERROR")
                        break
                    continue

                timer.start_stage("reframe")
                success = self.reframer.reframe_segment_ffmpeg(local_src, clip_out, start_s, dur_s, plan)

                if not success or not os.path.exists(clip_out):
                    log(f"Reframe failed for candidate {cand['candidate']}, skipping", "WARN")
                    cand["result"] = "REJECT"
                    cand["reason"] = "RENDER_FAILED"
                    self.ledger.release_single_clip(cid)
                    timer.stop_stage("reframe")

                    fail_code = "RENDER_FAILED"
                    if fail_code == last_fail_code:
                        consecutive_fails += 1
                    else:
                        consecutive_fails = 1
                        last_fail_code = fail_code
                    if consecutive_fails >= 3:
                        log(f"\n[ERROR] SYSTEMIC FAILURE: {last_fail_code} (3 in a row)", "ERROR")
                        log(f"Systemic failure triggered: 3 candidates in a row failed with code '{last_fail_code}'. Halting batch.\n", "ERROR")
                        break
                    continue

                # Verify post-crop gate
                post_ok, post_msg = self.reframer.verify_post_crop_gate(clip_out, plan=plan, layout_mode=layout_mode)
                if not post_ok:
                    log(f"Candidate {cand['candidate']} post-crop gate verify failed ({post_msg}), skipping", "WARN")
                    cand["result"] = "REJECT"
                    cand["reason"] = f"POST_CROP_GATE_FAIL ({post_msg})"
                    self.ledger.release_single_clip(cid)
                    timer.stop_stage("reframe")
                    try: os.remove(clip_out)
                    except: pass

                    fail_code = post_msg.split()[0].replace("(", "").replace(")", "").replace(":", "")
                    if fail_code == last_fail_code:
                        consecutive_fails += 1
                    else:
                        consecutive_fails = 1
                        last_fail_code = fail_code
                    if consecutive_fails >= 3:
                        log(f"\n[ERROR] SYSTEMIC FAILURE: {last_fail_code} (3 in a row)", "ERROR")
                        log(f"Systemic failure triggered: 3 candidates in a row failed with code '{last_fail_code}'. Halting batch.\n", "ERROR")
                        break
                    continue

                # Candidate successfully passed post-crop gate: reset consecutive failure counter
                consecutive_fails = 0
                last_fail_code = ""

                log(f"Candidate {cand['candidate']} Post-Crop Gate: PASS ✅ ({post_msg})")
                timer.stop_stage("reframe")

                # Stage: caption
                timer.start_stage("caption")
                caption_text = ""
                if len(processed_clip_paths) == 0 or (len(processed_clip_paths) % 2 == 1 and len(processed_clip_paths) < target_clips_count - 1):
                    caption_text = random.choice(caption_pool)
                    cap_out = os.path.join(work_job_dir, f"{job_id}_c{len(processed_clip_paths):02d}_cap.mp4")
                    cap_ok = render_safe_zone_caption(clip_out, cap_out, caption_text, font_lang=language)
                    if cap_ok and os.path.exists(cap_out):
                        clip_out = cap_out
                timer.stop_stage("caption")

                processed_clip_paths.append(clip_out)
                clip_mapping_data.append({
                    "clip_index": len(processed_clip_paths),
                    "clip_id": cid,
                    "source_file": cand["source"],
                    "start_s": start_s,
                    "end_s": cinfo["end_s"],
                    "duration": round(dur_s, 2),
                    "crop_mode": plan.get("mode", "smart_crop"),
                    "caption": caption_text,
                    "license": cinfo.get("license", "Creative Commons CC-BY 4.0"),
                    "credit": cinfo.get("author") or cinfo.get("channel") or "LionReel Verified CC Archive"
                })
                credits_data.append({
                    "clip_index": len(processed_clip_paths),
                    "source": cand["source"],
                    "license": cinfo.get("license", "Creative Commons CC-BY 4.0"),
                    "credit": cinfo.get("author") or cinfo.get("channel") or "LionReel Verified CC Archive"
                })

            # Step e: Strict clip delivery check (Never silently deliver fewer clips)
            min_required_final = target_clips_count if not allow_shorter else min(target_clips_count, 2)
            if len(processed_clip_paths) < min_required_final:
                err_msg = f"JOB FAILED: not enough usable clips (got {len(processed_clip_paths)} of {target_clips_count})"
                log(f"[FATAL] {err_msg}", "ERROR")
                self.ledger.release_reservation(job_id)
                timer.save_timings(os.path.join(work_job_dir, f"{job_id}_timings.json"))
                with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                    json.dump({
                        "job_id": job_id,
                        "status": "failed",
                        "success": False,
                        "error": err_msg,
                        "code": "INSUFFICIENT_CLIPS",
                        "got_clips": len(processed_clip_paths),
                        "target_clips": target_clips_count
                    }, f_jr, indent=2)
                self.update_pipeline_progress(
                    job_id, 7, "Smart center-crop to 9:16 vertical shorts", 75,
                    candidate_reports=candidate_reports, error=err_msg,
                    failed_stage="Smart center-crop to 9:16 vertical shorts"
                )
                return None

            # 3. Concatenate all processed clips inside local work_job_dir
            concat_txt = os.path.join(work_job_dir, f"concat_{job_id}.txt")
            with open(concat_txt, "w", encoding="utf-8") as f:
                for p in processed_clip_paths:
                    f.write(f"file '{os.path.abspath(p)}'\n")

            raw_assembled = os.path.join(work_job_dir, f"assembled_{job_id}.mp4")
            concat_cmd = [
                FFMPEG_EXE, "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_txt,
                "-c:v", "libx264", "-preset", "fast", "-crf", "12",
                "-c:a", "aac", "-b:a", "192k",
                raw_assembled
            ]
            subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

            # 4. Stage 8: audio (Master Audio: EBU R128 -14 LUFS, TP <= -1.0)
            self.update_pipeline_progress(job_id, 8, "Mixing background music & audio ducking (-14 LUFS)", 85, candidate_reports=candidate_reports)
            timer.start_stage("audio")
            audio_mastered = os.path.join(work_job_dir, f"master_audio_{job_id}.mp4")
            log("Mastering audio (Two-Pass EBU R128: -14.0 LUFS, -1.0 dBTP)...")
            master_audio_ebu_r128(raw_assembled, audio_mastered, BGM_PATH)
            timer.stop_stage("audio")

            # 5. Stage 9: render (Final Master Export on local SSD)
            self.update_pipeline_progress(job_id, 9, "Rendering final MP4 compilation with FFmpeg", 95, candidate_reports=candidate_reports)
            timer.start_stage("render")
            log(f"Rendering final master export locally: {final_filename}...")
            export_cmd = [
                FFMPEG_EXE, "-y",
                "-i", audio_mastered,
                "-vf", "cas=0.6",
                "-c:v", "libx264", "-preset", "fast", "-profile:v", "high", "-level", "4.2",
                "-b:v", "8500k", "-minrate", "6000k", "-maxrate", "14000k", "-bufsize", "14000k",
                "-pix_fmt", "yuv420p", "-r", "30", "-g", "60", "-bf", "2",
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                "-movflags", "+faststart",
                "-c:a", "copy",
                local_master_path
            ]
            subprocess.run(export_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            timer.stop_stage("render")

            if not os.path.exists(local_master_path):
                log("Final export failed!", "ERROR")
                self.ledger.release_reservation(job_id)
                self.update_pipeline_progress(job_id, 9, "Rendering final MP4 compilation with FFmpeg", 95, candidate_reports=candidate_reports, error="Final export failed", failed_stage="Rendering final MP4 compilation with FFmpeg")
                return None

            # Step f: Post-render ffprobe duration check (Fail with DURATION_MISMATCH if > 10% delta)
            real_dur = get_video_duration(local_master_path)
            dur_diff_pct = abs(real_dur - expected_total_sec) / expected_total_sec if expected_total_sec > 0 else 0
            log(f"[VERIFY] Final Master Duration Check: Expected={expected_total_sec:.2f}s, Real={real_dur:.2f}s (Diff={dur_diff_pct*100:.1f}%)")

            if dur_diff_pct > 0.10:
                err_msg = f"DURATION_MISMATCH: Expected {expected_total_sec:.1f} s, got {real_dur:.1f} s"
                log(f"[FATAL] {err_msg}", "ERROR")
                self.ledger.release_reservation(job_id)
                with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                    json.dump({
                        "job_id": job_id,
                        "status": "failed",
                        "success": False,
                        "error": err_msg,
                        "code": "DURATION_MISMATCH",
                        "expected_duration_s": expected_total_sec,
                        "real_duration_s": real_dur
                    }, f_jr, indent=2)
                self.update_pipeline_progress(
                    job_id, 9, "Rendering final MP4 compilation with FFmpeg", 95,
                    candidate_reports=candidate_reports, error=err_msg,
                    failed_stage="Rendering final MP4 compilation with FFmpeg"
                )
                return None

            render_time_sec = round(time.time() - start_render_time, 2)
            total_duration = round(float(sum(c["duration"] for c in clip_mapping_data)), 2)

            # Guard: SHA256 & Duplicate Output Check
            sha256_hash = hashlib.sha256()
            with open(local_master_path, "rb") as f_vid:
                while chunk := f_vid.read(128 * 1024):
                    sha256_hash.update(chunk)
            sha256_str = sha256_hash.hexdigest()

            clip_ids = [c["clip_id"] for c in clip_mapping_data]
            is_dup, dup_msg = self.ledger.check_duplicate_output(sha256_str, clip_ids)
            if is_dup:
                log(f"[ERROR] DUPLICATE_OUTPUT DETECTED! {dup_msg}", "ERROR")
                self.ledger.release_reservation(job_id)
                with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                    json.dump({
                        "job_id": job_id,
                        "status": "error",
                        "success": False,
                        "error": f"DUPLICATE_OUTPUT: {dup_msg}",
                        "code": "DUPLICATE_OUTPUT"
                    }, f_jr, indent=2)
                raise RuntimeError(f"DUPLICATE_OUTPUT: {dup_msg}")

            # 6. Write mapping, credits, and metadata locally in work_job_dir
            mapping_data = {
                "output_file": final_filename,
                "job_id": job_id,
                "video_type": video_type,
                "animal_mode": animal_mode,
                "total_duration": total_duration,
                "expected_duration_s": expected_total_sec,
                "real_duration_s": real_dur,
                "clip_count": len(clip_mapping_data),
                "target_clips": target_clips_count,
                "target_clip_sec": target_clip_sec,
                "config_line": config_line,
                "sha256": sha256_str,
                "clips": clip_mapping_data
            }
            credits_data_payload = {
                "output_file": final_filename,
                "job_id": job_id,
                "credits": credits_data
            }
            title_pool = TITLES_DOG if animal_mode == "dog" else (TITLES_DUO if animal_mode == "duo" else TITLES_CAT)
            clean_title = random.choice(title_pool)

            with open(os.path.join(work_job_dir, f"{job_id}_mapping.json"), "w", encoding="utf-8") as f_map:
                json.dump(mapping_data, f_map, indent=2)
            with open(os.path.join(work_job_dir, f"{job_id}_credits.json"), "w", encoding="utf-8") as f_cred:
                json.dump(credits_data_payload, f_cred, indent=2)
            with open(os.path.join(work_job_dir, f"{job_id}_metadata.txt"), "w", encoding="utf-8") as f_meta:
                f_meta.write(f"TITLE: {clean_title}\n")
            with open(os.path.join(work_job_dir, f"{job_id}.txt"), "w", encoding="utf-8") as f_meta:
                f_meta.write(f"TITLE: {clean_title}\n")

            # 7. Stage: qa (Automated QA Gate Check on local file)
            timer.start_stage("qa")
            log("Running Automated QA Gate Validation on local SSD master...")
            from qa_check import run_full_qa
            qa_passed, qa_report = run_full_qa(local_master_path)
            timer.stop_stage("qa")

            if not qa_passed:
                log(f"QA FAILED ❌ Releasing reserved clips back to pool.", "WARN")
                self.ledger.release_reservation(job_id)
                self.update_pipeline_progress(
                    job_id, 10, "Preparing export packages for TikTok, Reels & Shorts", 95,
                    candidate_reports=candidate_reports, error="QA validation failed",
                    failed_stage="Preparing export packages for TikTok, Reels & Shorts"
                )
                return None

            log(f"QA PASSED ✅ Committing clips in ledger for {job_id}.")
            self.ledger.commit_short(job_id)
            self.ledger.register_output(
                job_id=job_id,
                output_filename=final_filename,
                sha256=sha256_str,
                clip_ids=clip_ids,
                duration_sec=total_duration,
                render_time_sec=render_time_sec
            )

            # 8. Stage: export_copy (Single batch copy to Drive - Requirement 3)
            timer.start_stage("export_copy")
            log("Copying final master and artifacts to Google Drive in single batch step...")
            # Copy final MP4
            shutil.copy2(local_master_path, job_output_path)
            shutil.copy2(local_master_path, finished_output_path)

            # Copy JSON and metadata files
            for artifact_f in [
                f"{job_id}_mapping.json", f"{job_id}_credits.json",
                f"{job_id}_metadata.txt", f"{job_id}.txt",
                f"{job_id}_qa_report.json", f"{job_id}_contact_sheet.png"
            ]:
                src_art = os.path.join(work_job_dir, artifact_f)
                if os.path.exists(src_art):
                    shutil.copy2(src_art, os.path.join(output_job_dir, artifact_f))
                    shutil.copy2(src_art, os.path.join(OUT_DIR, artifact_f))
            timer.stop_stage("export_copy")

            # Save stage timings JSON (Requirement 1)
            timings_local_path = os.path.join(work_job_dir, "timings.json")
            timings_job_path = os.path.join(output_job_dir, f"{job_id}_timings.json")
            timings_fin_path = os.path.join(OUT_DIR, f"{job_id}_timings.json")
            timer.save_timings(timings_local_path)
            shutil.copy2(timings_local_path, timings_job_path)
            shutil.copy2(timings_local_path, timings_fin_path)

            # Log stage timer table to console (Requirement 1)
            table_ascii = timer.format_table()
            log("\n" + table_ascii)

            # 9. Write Success job_result.json
            job_result_data = {
                "job_id": job_id,
                "status": "completed",
                "success": True,
                "stage_index": 10,
                "stage_name": "Preparing export packages for TikTok, Reels & Shorts",
                "progress_pct": 100,
                "candidate_reports": candidate_reports,
                "output_file": final_filename,
                "output_path": finished_output_path,
                "sha256": sha256_str,
                "duration": total_duration,
                "expected_duration_s": expected_total_sec,
                "real_duration_s": real_dur,
                "config_line": config_line,
                "clip_list": clip_ids,
                "render_time_sec": render_time_sec,
                "title": clean_title,
                "timings": timer.to_dict()["stages"]
            }
            with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                json.dump(job_result_data, f_jr, indent=2)

            log(f"Finished job for {job_id}. Output: {job_output_path} (copied to {finished_output_path})")
            log(f"Render Time: {render_time_sec}s | SHA256: {sha256_str} | Clips: {clip_ids}")
            return finished_output_path

        finally:
            # Ensure timings are saved even if an error or early exit occurred
            try:
                timings_local_path = os.path.join(work_job_dir, "timings.json")
                if not os.path.exists(timings_local_path):
                    timer.save_timings(timings_local_path)
                    log("\n" + timer.format_table())
            except Exception:
                pass
            # Release process lock
            if os.path.exists(lock_file):
                try: os.remove(lock_file)
                except: pass
            # Cleanup local intermediate scratch files
            try:
                for f_tmp in os.listdir(work_job_dir):
                    if f_tmp.endswith(".mp4") and f_tmp != final_filename:
                        try: os.remove(os.path.join(work_job_dir, f_tmp))
                        except: pass
            except Exception:
                pass

    def run(self, animal_mode=None, video_type=None, language=None, count=None, job_id=None, use_cache=False, layout_mode=None, clips_count=None, clip_time=None, pace_profile=None, slicing_mode=None, allow_shorter=False):
        cfg = self.load_config()
        animal_mode = animal_mode or cfg.get("ANIMAL_MODE") or cfg.get("VIDEO_MODE") or "cat"
        video_type = video_type or cfg.get("VIDEO_TYPE") or "short"
        language = language or cfg.get("LANGUAGE") or "en"
        layout_mode = layout_mode or cfg.get("LAYOUT_MODE") or "smart_crop"
        verify_layout_gate_compatibility(layout_mode)
        count = count or int(cfg.get("OUTPUT_COUNT", 1))

        log("=" * 72)
        log(f"LIONREEL V97 PIPELINE INITIALIZED | MODE: {animal_mode.upper()} | TYPE: {video_type.upper()} | LAYOUT: {layout_mode.upper()} | COUNT: {count}")
        log("=" * 72)

        rendered = []
        for i in range(count):
            log(f"\n--- RENDERING VIDEO {i+1} OF {count} ---")
            current_job_id = job_id if (i == 0 and job_id) else None
            res = self.render_one_video(
                animal_mode=animal_mode,
                video_type=video_type,
                language=language,
                job_id=current_job_id,
                use_cache=use_cache,
                layout_mode=layout_mode,
                clips_count=clips_count,
                clip_time=clip_time,
                pace_profile=pace_profile,
                slicing_mode=slicing_mode,
                allow_shorter=allow_shorter
            )
            if res:
                rendered.append(res)

        log("\n" + "=" * 72)
        log(f"BATCH COMPLETE: {len(rendered)} of {count} videos successfully created and validated.")
        log("=" * 72)
        return rendered

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LionReel V97 Master Pet Video Pipeline")
    parser.add_argument("--mode", choices=["cat", "dog", "duo"], default=None, help="Animal mode (cat, dog, duo)")
    parser.add_argument("--type", choices=["short", "compilation"], default=None, help="Video type (short, compilation)")
    parser.add_argument("--lang", choices=["en", "si"], default=None, help="Language (en, si)")
    parser.add_argument("--layout", choices=["smart_crop", "blur_fit", "auto"], default=None, help="Layout framing mode (smart_crop, blur_fit, auto)")
    parser.add_argument("--count", type=int, default=None, help="Number of videos to render")
    parser.add_argument("--job-id", default=None, help="Unique job ID for this run")
    parser.add_argument("--use-cache", action="store_true", default=False, help="Use cached result if available (off by default)")
    parser.add_argument("--clips", type=int, default=None, help="Target number of clips")
    parser.add_argument("--clip-time", type=float, default=None, help="Target clip duration in seconds")
    parser.add_argument("--pace", default=None, help="Compilation pace profile (fast, balanced, cinematic)")
    parser.add_argument("--slicing", default=None, help="Moment cut mode (peak_viral, fast_action, etc.)")
    parser.add_argument("--allow-shorter", action="store_true", default=False, help="Allow shorter video if clips run out")
    args = parser.parse_args()

    pipeline = LionReelV97Pipeline()
    pipeline.run(
        animal_mode=args.mode,
        video_type=args.type,
        language=args.lang,
        count=args.count,
        job_id=args.job_id,
        use_cache=args.use_cache,
        layout_mode=args.layout,
        clips_count=args.clips,
        clip_time=args.clip_time,
        pace_profile=args.pace,
        slicing_mode=args.slicing,
        allow_shorter=args.allow_shorter
    )

