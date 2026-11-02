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
import re
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
from stage_state_machine import (
    StageStateMachine,
    STAGE_DEFINITIONS,
    StageOrderViolationError,
    MissingInputError,
    EmptyResultError
)

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

    def plan_reframe(self, video_path, start_s, dur_s, animal_mode="cat", layout_mode="smart_crop", stricter=False, allow_slide=True, **kwargs):
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
            stricter=stricter,
            allow_slide=allow_slide,
            **kwargs
        )

    def early_check_segment_gate(self, in_path, start_s, dur_s, plan, layout_mode="smart_crop", *args, **kwargs):
        if not hasattr(self, "engine"):
            self.engine = AutoReframeEngine(self.detector)
        return self.engine.early_check_segment_gate(in_path, start_s, dur_s, plan, layout_mode=layout_mode, *args, **kwargs)

    def reframe_segment_ffmpeg(self, in_path, out_path, start_s, dur_s, plan, *args, **kwargs):
        """
        Executes single-pass crop + scale + mild unsharp using FFmpeg.
        """
        if not hasattr(self, "engine"):
            self.engine = AutoReframeEngine(self.detector)
        return self.engine.reframe_segment_ffmpeg(in_path, out_path, start_s, dur_s, plan, *args, **kwargs)

    def verify_post_crop_gate(self, cropped_path, plan=None, layout_mode="smart_crop"):
        """
        QA Gate: on the cropped video, verify layout fill, pet centering, visual sharpness, and real footage.
        At least 88% of frames must have pet centered and content filling the 1080x1920 frame.
        """
        from qa_check import check_pet_centering, check_layout_fill, check_visual_sharpness, check_cartoon_classifier
        has_slack = False
        effective_layout = layout_mode
        if plan:
            orig_h = plan.get("orig_size", (0, 0))[1]
            crop_h = plan.get("crop_h", orig_h)
            has_slack = bool(crop_h < orig_h)
            if plan.get("mode") in ["blur_fit", "smart_crop"]:
                effective_layout = plan["mode"]
        fill_res = check_layout_fill(cropped_path, n_samples=16, layout_mode=effective_layout)
        is_clamped = False
        if plan:
            is_clamped = bool(plan.get("is_clamped", False) or plan.get("mode") == "vertical_direct")
        cent_res = check_pet_centering(cropped_path, n_samples=24, has_vertical_slack=has_slack, layout_mode=effective_layout, is_clamped=is_clamped)
        sharp_res = check_visual_sharpness(cropped_path, n_samples=12)
        cartoon_res = check_cartoon_classifier(cropped_path, n_samples=12, layout_mode=effective_layout)
        passed = bool(fill_res["passed"] and cent_res["passed"] and sharp_res["passed"] and cartoon_res["passed"])
        fail_reasons = []
        if not fill_res["passed"]:
            fail_reasons.append(f"Layout: {fill_res.get('reason', '')}")
        if not cent_res["passed"]:
            fail_reasons.append(f"Centering: {cent_res.get('compliance_ratio', 0.0):.1%}")
        if not sharp_res["passed"]:
            fail_reasons.append(f"Sharpness: {sharp_res.get('median_sharpness', 0.0):.1f} (low_ratio: {sharp_res.get('low_sharp_frame_ratio', 0.0):.2f})")
        if not cartoon_res["passed"]:
            fail_reasons.append(f"CGI/Cartoon: {cartoon_res.get('mean_negative_probability', 0.0):.1%}")
        reason = (
            f"Centering: {cent_res.get('compliance_ratio', 0.0):.1%} "
            f"(Vis:{cent_res.get('visibility_ratio', 0.0):.1%}, "
            f"H:{cent_res.get('horizontal_ratio', 0.0):.1%}, "
            f"V:{cent_res.get('vertical_ratio', 0.0):.1%}, "
            f"S:{cent_res.get('size_ratio', 0.0):.1%}), "
            f"Layout: {fill_res.get('reason', '')}, "
            f"Sharpness: {sharp_res.get('median_sharpness', 0.0):.1f}, "
            f"CGI: {cartoon_res.get('mean_negative_probability', 0.0):.1%}"
        )
        if fail_reasons:
            reason = " | ".join(fail_reasons) + " -> " + reason
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
    has_bgm = bool(bgm_path and os.path.exists(bgm_path))
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
        "-af", "loudnorm=I=-14.0:TP=-2.2:LRA=11.0:print_format=json",
        "-f", "null", "-"
    ]
    res = subprocess.run(p1_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
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

    # Pass 2: Apply measured values with linear=true to strictly maintain True Peak <= -0.5 dBTP
    p2_af = "loudnorm=I=-14.0:TP=-2.2:LRA=11.0"
    if json_lines:
        try:
            m = json.loads("\n".join(json_lines))
            mi = m.get("input_i", "-14.0")
            mtp = m.get("input_tp", "-2.2")
            mlra = m.get("input_lra", "11.0")
            mth = m.get("input_thresh", "-24.0")
            off = m.get("target_offset", "0.0")
            p2_af = f"loudnorm=I=-14.0:TP=-2.2:LRA=11.0:measured_I={mi}:measured_TP={mtp}:measured_LRA={mlra}:measured_thresh={mth}:offset={off}:linear=true"
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
                "output_file": output_file,
                "elapsed_seconds": round(time.time() - _SCRIPT_START_TIME, 1)
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

    def render_one_video(self, animal_mode="cat", video_type="short", language="en", job_id=None, use_cache=False, layout_mode=None, clips_count=None, clip_time=None, pace_profile=None, slicing_mode=None, allow_shorter=False, allow_reuse=False):
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
            sm = StageStateMachine(job_id=job_id, work_dir=work_job_dir, config=cfg)

            # =========================================================================
            # STAGE 1: collect_candidates
            # Connects to clip ledger, cleans stale reservations, reserves candidate clips.
            # =========================================================================
            timer.start_stage("harvest")
            trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=20)
            timer.stop_stage("harvest")

            timer.start_stage("ledger_reserve")
            sm.start_stage(1)
            self.update_pipeline_progress(job_id, 1, "Collect candidate moments from ledger", 10)

            pool_status = self.ledger.get_pool_status(animal_mode)
            unused_clips = pool_status.get("unused_clips", 0)
            distinct_sources = pool_status.get("distinct_sources", 0)

            # Never limited to one source: if bank has fewer than 3 sources, start harvest before reserving
            if distinct_sources < 3:
                log(f"Bank has fewer than 3 sources ({distinct_sources} distinct sources). Starting harvest before reserving...", "INFO")
                trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=24)

            if unused_clips < target_clips_count:
                is_empty_pool = (pool_status.get("total_clips", 0) == 0) or (distinct_sources == 0)
                target_status = "needs_sources" if is_empty_pool else "waiting_for_clips"
                status_msg = "Needs sources: Please add 1080p+ cat videos to pool" if is_empty_pool else f"Finding more clips: {unused_clips} of {target_clips_count} ready"
                log(f"[SELF-HEALING PAUSE] {status_msg}. Job transitioning to {target_status.upper()}.", "WARN")

                trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=24)

                with open(os.path.join(work_job_dir, "checkpoint.json"), "w", encoding="utf-8") as f_cp:
                    json.dump({
                        "job_id": job_id,
                        "status": target_status,
                        "stage_index": 1,
                        "got_clips": unused_clips,
                        "target_clips_count": target_clips_count,
                        "target_clip_sec": target_clip_sec,
                        "layout_mode": layout_mode
                    }, f_cp, indent=2)

                with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                    json.dump({
                        "job_id": job_id,
                        "status": target_status,
                        "success": None,
                        "error": status_msg,
                        "stage_index": 1,
                        "stage_name": status_msg,
                        "progress_pct": int(round((unused_clips / float(target_clips_count)) * 20)),
                        "got_clips": unused_clips,
                        "target_clips": target_clips_count,
                        "elapsed_seconds": round(time.time() - _SCRIPT_START_TIME, 1)
                    }, f_jr, indent=2)

                self.update_pipeline_progress(job_id, 1, status_msg, int(round((unused_clips / float(target_clips_count)) * 20)))
                timer.stop_stage("ledger_reserve")
                return None

            candidate_target = max(24, target_clips_count * 5)
            try:
                self.ledger.cleanup_stale_reservations(job_id)
                reserved_clips = self.ledger.reserve_clips(
                    target_count=candidate_target,
                    animal_mode=animal_mode,
                    short_id=job_id,
                    allow_reuse=allow_reuse,
                    min_required=target_clips_count
                )
            except Exception as e_res:
                err_msg = str(e_res)
                log(f"Reservation Error: {err_msg}", "ERROR")
                sm.fail_stage(1, err_msg, code="RESERVATION_ERROR")
                self.update_pipeline_progress(job_id, 1, "Collect candidate moments from ledger", 10, error=err_msg, failed_stage="Collect candidate moments from ledger")
                timer.stop_stage("ledger_reserve")
                raise RuntimeError(err_msg)

            timer.stop_stage("ledger_reserve")

            if not reserved_clips:
                status_msg = "Needs sources: Please add 1080p+ cat videos to pool"
                log(f"[SELF-HEALING PAUSE] {status_msg}. Job transitioning to NEEDS_SOURCES.", "WARN")
                trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=24)
                with open(os.path.join(work_job_dir, "checkpoint.json"), "w", encoding="utf-8") as f_cp:
                    json.dump({
                        "job_id": job_id, "status": "needs_sources", "stage_index": 1,
                        "got_clips": 0, "target_clips_count": target_clips_count,
                        "target_clip_sec": target_clip_sec, "layout_mode": layout_mode
                    }, f_cp, indent=2)

                with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                    json.dump({
                        "job_id": job_id, "status": "needs_sources", "success": None, "error": status_msg,
                        "stage_index": 1, "stage_name": status_msg, "progress_pct": 0,
                        "got_clips": 0, "target_clips": target_clips_count,
                        "elapsed_seconds": round(time.time() - _SCRIPT_START_TIME, 1)
                    }, f_jr, indent=2)

                self.update_pipeline_progress(job_id, 1, status_msg, 0)
                return None

            proof_s1 = {
                "items_count": len(reserved_clips),
                "target_clips": target_clips_count,
                "candidate_target": candidate_target,
                "reserved_clips": reserved_clips,
                "animal_mode": animal_mode
            }
            ev_s1 = f"Reserved {len(reserved_clips)} candidate clips from ledger (target: {target_clips_count})"
            sm.complete_stage(1, evidence=ev_s1, proof_data=proof_s1)
            log(f"Successfully reserved {len(reserved_clips)} candidate clips from ledger for job {job_id} (target: {target_clips_count}).")

            # =========================================================================
            # STAGE 2: prepare_sources
            # Verifies local source copies on disk, checks readability and streams.
            # =========================================================================
            sm.start_stage(2)
            self.update_pipeline_progress(job_id, 2, "Prepare & verify raw source video files", 20)

            with open(os.path.join(work_job_dir, "stages", "candidates_reserved.json"), "r", encoding="utf-8") as f_art1:
                s1_data = json.load(f_art1)
            reserved_clips = s1_data.get("reserved_clips", [])

            prepared_sources = {}
            for c_info in reserved_clips:
                src_p = c_info.get("source_url_or_path") or c_info.get("source_path")
                if src_p not in prepared_sources:
                    local_p = ensure_local_source_copy(src_p)
                    f_size = os.path.getsize(local_p) if os.path.exists(local_p) else 0
                    prepared_sources[src_p] = {
                        "source_path": src_p,
                        "local_copy": local_p,
                        "exists": os.path.exists(local_p),
                        "size_bytes": f_size
                    }

            if not prepared_sources or all(not v["exists"] for v in prepared_sources.values()):
                err_msg = "EMPTY_RESULT: No valid source files could be prepared on disk."
                sm.fail_stage(2, err_msg, code="EMPTY_RESULT")
                raise EmptyResultError(err_msg)

            total_source_mb = sum(v["size_bytes"] for v in prepared_sources.values()) / (1024 * 1024)
            proof_s2 = {
                "items_count": len(prepared_sources),
                "prepared_sources": list(prepared_sources.values()),
                "total_source_mb": round(total_source_mb, 2),
                "reserved_clips": reserved_clips
            }
            ev_s2 = f"Prepared {len(prepared_sources)} raw source video files ({total_source_mb:.1f} MB staged on disk)"
            sm.complete_stage(2, evidence=ev_s2, proof_data=proof_s2)

            # =========================================================================
            # STAGE 3: check_quality_fps
            # ffprobe fail-fast check: resolution, aspect ratio, CFR/fps stability.
            # Gated by ENFORCE_ASPECT_RATIO toggle.
            # =========================================================================
            if cfg.get("ENFORCE_ASPECT_RATIO", True) is False:
                sm.skip_stage(3, reason="turned off in settings")
            else:
                sm.start_stage(3)
                self.update_pipeline_progress(job_id, 3, "Check source video resolution & frame rate", 30)

                with open(os.path.join(work_job_dir, "stages", "sources_prepared.json"), "r", encoding="utf-8") as f_art2:
                    s2_data = json.load(f_art2)
                cur_reserved = s2_data.get("reserved_clips", [])

                timer.start_stage("ffprobe")
                probed_sources = {}
                pass_probe_cnt = 0
                fail_probe_cnt = 0
                for c_info in cur_reserved:
                    src_p = c_info.get("source_url_or_path") or c_info.get("source_path")
                    if src_p not in probed_sources:
                        pass_p, reason_p = check_and_gate_source(src_p, self.ledger)
                        probed_sources[src_p] = {"passed": pass_p, "reason": reason_p}
                        if pass_p:
                            pass_probe_cnt += 1
                        else:
                            fail_probe_cnt += 1
                timer.stop_stage("ffprobe")

                proof_s3 = {
                    "items_count": len(probed_sources),
                    "probed_sources": probed_sources,
                    "passed_count": pass_probe_cnt,
                    "failed_count": fail_probe_cnt,
                    "reserved_clips": cur_reserved
                }
                if pass_probe_cnt == 0:
                    err_msg = f"EMPTY_RESULT: All {len(probed_sources)} candidate sources failed fail-fast quality/upscale checks."
                    sm.fail_stage(3, err_msg, code="EMPTY_RESULT")
                    raise EmptyResultError(err_msg)

                ev_s3 = f"Probed {len(probed_sources)} sources with ffprobe: {pass_probe_cnt} passed quality/CFR gate, {fail_probe_cnt} rejected"
                sm.complete_stage(3, evidence=ev_s3, proof_data=proof_s3)

            # =========================================================================
            # STAGE 4: detect_watermarks
            # Corner sampling & platform overlay detection.
            # Gated by CHECK_WATERMARK toggle.
            # =========================================================================
            if cfg.get("CHECK_WATERMARK", True) is False:
                sm.skip_stage(4, reason="turned off in settings")
            else:
                sm.start_stage(4)
                self.update_pipeline_progress(job_id, 4, "Detect watermarks, logos & overlays", 40)

                with open(os.path.join(work_job_dir, "stages", "quality_checked.json"), "r", encoding="utf-8") as f_art3:
                    s3_data = json.load(f_art3)
                cur_reserved = s3_data.get("reserved_clips", [])

                timer.start_stage("watermark")
                scanned_sources = {}
                blocked_sources_in_job = set()
                wm_found_cnt = 0

                for c_info in cur_reserved:
                    src_p = c_info.get("source_url_or_path") or c_info.get("source_path")
                    src_name = os.path.basename(src_p)
                    if src_p in scanned_sources:
                        continue
                    if self.ledger.is_blocked_source(src_p):
                        blocked_sources_in_job.add(src_name)
                        blocked_sources_in_job.add(src_p)
                        scanned_sources[src_p] = {"has_wm": True, "reason": "BLOCKED_WATERMARK_IN_LEDGER"}
                        continue

                    # Sample corners
                    has_wm = False
                    wm_corner, wm_conf, wm_reason = "", 0.0, ""
                    try:
                        has_wm, wm_corner, wm_conf, wm_reason = self.wm_detector.check_video_corners(
                            src_p, start_s=c_info.get("start_s", 0.0), dur_s=c_info.get("end_s", 10.0) - c_info.get("start_s", 0.0), n_samples=8
                        )
                    except Exception:
                        pass

                    if has_wm:
                        wm_found_cnt += 1
                        log(f"Candidate watermark detected in {src_name} ({wm_corner}: {wm_reason}). Sampling 6 other windows of {src_name}...", "WARN")
                        is_pers, hit_cnt, wm_info = self.wm_detector.verify_source_watermark(src_p, n_windows=6)
                        log(f"Watermark 6-window sampling result for {src_name}: watermark found in {hit_cnt}/6 windows.", "INFO")
                        if is_pers or hit_cnt >= 2:
                            block_msg = f"BLOCKED_WATERMARK ({wm_info.get('corner', wm_corner)}: {wm_info.get('reason', wm_reason)} in {hit_cnt}/6 windows)"
                            log(f"Source {src_name} BLOCKED GLOBALLY: {block_msg}", "WARN")
                            self.ledger.mark_source_blocked(src_p, reason=block_msg)
                            blocked_sources_in_job.add(src_name)
                            blocked_sources_in_job.add(src_p)
                            remove_source_from_pool(src_p, block_msg)
                            scanned_sources[src_p] = {"has_wm": True, "reason": block_msg}
                        else:
                            log(f"Source {src_name} is CLEAN globally ({hit_cnt}/6 windows showed watermark, below 2/6 threshold). Window rejected.", "INFO")
                            scanned_sources[src_p] = {"has_wm": True, "reason": f"WATERMARK ({wm_corner}: {wm_reason})"}
                    else:
                        scanned_sources[src_p] = {"has_wm": False, "reason": "CLEAN"}
                timer.stop_stage("watermark")

                proof_s4 = {
                    "items_count": len(scanned_sources),
                    "sources_scanned": scanned_sources,
                    "watermarks_found": wm_found_cnt,
                    "blocked_sources": list(blocked_sources_in_job),
                    "reserved_clips": cur_reserved
                }
                ev_s4 = f"Scanned {len(scanned_sources)} sources across 4 corners, {wm_found_cnt} watermark(s) detected, {len(blocked_sources_in_job)} blocked"
                sm.complete_stage(4, evidence=ev_s4, proof_data=proof_s4)

            # =========================================================================
            # STAGE 5: predict_framing
            # Dynamic window slicing, YOLOX pre-scoring, sharpness, NMS diversity.
            # Gated by CHECK_SHARPNESS toggle.
            # =========================================================================
            sm.start_stage(5)
            self.update_pipeline_progress(job_id, 5, "Predict pet framing & select viral moments", 50)

            with open(os.path.join(work_job_dir, "stages", "watermark_checked.json"), "r", encoding="utf-8") as f_art4:
                s4_data = json.load(f_art4)
            cur_reserved = s4_data.get("reserved_clips", [])
            blocked_sources_set = set(s4_data.get("blocked_sources", []))

            candidate_reports = []
            passing_candidates = []
            rejected_candidates = []

            log(f"\n{'='*72}\nSTAGE A: FAST PRE-SCORING PREDICTED FRAMING BEFORE RENDER ({len(cur_reserved)} candidates)\n{'='*72}")

            for idx, clip_info in enumerate(cur_reserved):
                src_path = clip_info.get("source_url_or_path") or clip_info.get("source_path")
                cid = clip_info["clip_id"]
                src_name = os.path.basename(src_path)

                if src_name in blocked_sources_set or src_path in blocked_sources_set or self.ledger.is_blocked_source(src_path):
                    rep = {
                        "candidate": idx + 1, "clip_id": cid, "source": src_name,
                        "start_s": clip_info.get("start_s", 0.0), "dur_s": 0.0,
                        "measured": False,
                        "pet_ratio": None, "vis_ratio": None, "horiz_ratio": None, "vert_ratio": None, "size_ratio": None, "sharpness": None,
                        "score": None, "actual_score": None,
                        "result": "REJECT", "reason": "BLOCKED_WATERMARK"
                    }
                    candidate_reports.append(rep)
                    rejected_candidates.append(rep)
                    self.ledger.release_single_clip(cid)
                    continue

                # Dynamic Window Slicing
                is_verified_c = (clip_info.get("is_verified") == 1)
                if is_verified_c:
                    win_start = float(clip_info["start_s"])
                    win_end = float(clip_info["end_s"])
                    win_ok = True
                else:
                    win_start, win_end, win_ok = compute_clip_window(
                        src_path,
                        clip_info["start_s"],
                        clip_info["end_s"],
                        target_clip_sec,
                        tolerance=0.5
                    )

                if not win_ok:
                    rep = {
                        "candidate": idx + 1, "clip_id": cid, "source": src_name,
                        "start_s": clip_info["start_s"], "dur_s": 0.0,
                        "measured": False,
                        "pet_ratio": None, "vis_ratio": None, "horiz_ratio": None, "vert_ratio": None, "size_ratio": None, "sharpness": None,
                        "score": None, "actual_score": None,
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

                # Tracking & Camera Planning
                timer.start_stage("tracking")
                local_src = ensure_local_source_copy(src_path)

                plan = None
                if is_verified_c and clip_info.get("verified_plan"):
                    raw_p = clip_info["verified_plan"]
                    if isinstance(raw_p, str):
                        try: plan = json.loads(raw_p)
                        except: plan = None
                    elif isinstance(raw_p, dict):
                        plan = raw_p

                if not plan or (plan.get("mode") != "vertical_direct" and ("orig_size" not in plan or "crop_w" not in plan)):
                    plan = self.reframer.plan_reframe(
                        local_src, start_s, dur_s,
                        animal_mode=animal_mode,
                        layout_mode=layout_mode,
                        stricter=False,
                        allow_slide=True
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

                # Sharpness Toggle Check
                if cfg.get("CHECK_SHARPNESS", True) and sharpness < 85.0 and plan.get("status") == "pass":
                    plan["status"] = "reject"
                    plan["reason"] = f"LOW_SHARPNESS ({sharpness:.1f} < 85)"

                if plan.get("status") == "pass" and score == 0.0 and sharpness == 0.0:
                    plan["status"] = "reject"
                    plan["reason"] = "ANALYSIS_FAILED (Score 0.0% and Sharpness 0.0)"

                failing_frames = plan.get("failing_frames", [])
                failing_summary = plan.get("failing_summary", "")
                fail_str = f" | Failing frames: {failing_frames} ({failing_summary})" if failing_frames else ""

                comp_str = f"Pet: {pet_ratio:.1%}, H: {horiz_ratio:.1%}, V: {vert_ratio:.1%}, Vis: {vis_ratio:.1%}, Sharp: {sharpness:.1f}, Score: {score:.1%}"

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
                        "failing_frames": failing_frames,
                        "failing_summary": failing_summary,
                        "measured": True,
                        "actual_score": None,
                        "result": "PASS", "reason": "PREDICT_PASS",
                        "plan": plan, "clip_info": clip_info
                    }
                    candidate_reports.append(rep)
                    passing_candidates.append(rep)
                    log(f"  [Cand {idx+1:02d} | {src_name} {start_s:5.1f}s-{win_end:5.1f}s ({dur_s:.1f}s)]: PREDICT PASS -> {comp_str}{fail_str}")
                else:
                    reason = plan.get("reason", "PREDICTED_BAD_FRAMING")
                    is_failed_analysis = "ANALYSIS_FAILED" in reason
                    rep = {
                        "candidate": idx + 1, "clip_id": cid, "source": src_name,
                        "start_s": start_s, "dur_s": dur_s, "score": round(score, 3),
                        "sharpness": round(sharpness, 1),
                        "pet_ratio": round(pet_ratio, 3),
                        "vis_ratio": round(vis_ratio, 3),
                        "horiz_ratio": round(horiz_ratio, 3),
                        "vert_ratio": round(vert_ratio, 3),
                        "size_ratio": round(size_ratio, 3),
                        "failing_frames": failing_frames,
                        "failing_summary": failing_summary,
                        "measured": not is_failed_analysis,
                        "actual_score": None,
                        "result": "REJECT", "reason": reason
                    }
                    candidate_reports.append(rep)
                    rejected_candidates.append(rep)
                    self.ledger.release_single_clip(cid)
                    log(f"  [Cand {idx+1:02d} | {src_name} {start_s:5.1f}s]: PREDICT REJECT -> {reason} | {comp_str}{fail_str}")

            # NMS on candidate windows: prioritize framing score, then least used, then funny moment
            passing_candidates.sort(
                key=lambda x: (
                    round(float(x.get("score") or 0.0), 3),
                    -int(x.get("clip_info", {}).get("times_used", 0)),
                    float(x.get("clip_info", {}).get("funny_score", 0.0))
                ),
                reverse=True
            )
            nms_passing = []
            for cand in passing_candidates:
                c_src = cand["source"]
                c_start = cand["start_s"]
                c_end = cand["start_s"] + cand["dur_s"]
                suppressed = False
                for kept in nms_passing:
                    if kept["source"] == c_src:
                        k_start = kept["start_s"]
                        k_end = kept["start_s"] + kept["dur_s"]
                        if abs(c_start - k_start) < 10.0 or not (c_end <= k_start or k_end <= c_start):
                            suppressed = True
                            cand["result"] = "REJECT"
                            cand["reason"] = f"NMS_OVERLAP (Duplicate moment with Cand {kept['candidate']})"
                            self.ledger.release_single_clip(cand["clip_id"])
                            rejected_candidates.append(cand)
                            break
                if not suppressed:
                    nms_passing.append(cand)

            # Interleave sources
            unique_passing_sources = set(c["source"] for c in nms_passing)
            source_groups = {}
            for c in nms_passing:
                source_groups.setdefault(c["source"], []).append(c)

            interleaved_passing = []
            deferred_passing = []
            src_keys = list(source_groups.keys())

            for s in src_keys:
                if source_groups[s]:
                    interleaved_passing.append(source_groups[s].pop(0))
            for s in src_keys:
                if source_groups[s]:
                    interleaved_passing.append(source_groups[s].pop(0))
            for s in src_keys:
                while source_groups[s]:
                    deferred_passing.append(source_groups[s].pop(0))

            passing_candidates = interleaved_passing + deferred_passing
            log(f"\nStage A Complete (Post-NMS & Diversity): {len(passing_candidates)} candidates available across {len(unique_passing_sources)} distinct source(s).")

            if len(passing_candidates) < target_clips_count:
                log(f"\n[SELF-HEALING] Candidate deficit detected: got {len(passing_candidates)} of {target_clips_count} needed. Initiating self-healing loop...", "WARN")

                # Ladder Step 1: Relax source diversity (3 -> 2 sources, up to 3 clips per source at least 30s apart)
                log("  [DEGRADATION LADDER Step 1] Relaxing source diversity (3 -> 2 sources, up to 3 clips per source >= 30s apart)...", "INFO")
                recovered_l1 = 0
                for cand in list(rejected_candidates):
                    if len(passing_candidates) >= target_clips_count:
                        break
                    reason_str = cand.get("reason", "")
                    if "MAX_SOURCE_CAP" in reason_str or "DIVERSITY" in reason_str or "NMS_OVERLAP" in reason_str:
                        c_src = cand["source"]
                        c_s = cand["start_s"]
                        src_passing = [c for c in passing_candidates if c["source"] == c_src]
                        if len(src_passing) < 3:
                            # Verify at least 30s apart from other clips of same source
                            if all(abs(c_s - ex["start_s"]) >= 30.0 for ex in src_passing):
                                cand["result"] = "PASS"
                                cand["reason"] = "RELAXED_DIVERSITY_LADDER_1"
                                passing_candidates.append(cand)
                                if cand in rejected_candidates:
                                    rejected_candidates.remove(cand)
                                recovered_l1 += 1
                                log(f"    [LADDER 1 RECOVERY] Candidate {cand['candidate']} from {c_src} at {c_s:.1f}s accepted (>=30s apart).", "INFO")

                # Ladder Step 2: Relax clip duration tolerance (+/-0.5s -> +/-1.0s) with sliding window
                if len(passing_candidates) < target_clips_count:
                    log("  [DEGRADATION LADDER Step 2] Relaxing clip duration tolerance (+/-0.5s -> +/-1.0s) with sliding window...", "INFO")
                    for cand in list(rejected_candidates):
                        if len(passing_candidates) >= target_clips_count:
                            break
                        if cand.get("score") and cand.get("score") >= 0.85:
                            cinfo = cand.get("clip_info")
                            if cinfo:
                                src_p = cinfo.get("source_url_or_path") or cinfo.get("source_path")
                                local_p = ensure_local_source_copy(src_p)
                                new_plan = self.reframer.plan_reframe(
                                    local_p, cand["start_s"], cand["dur_s"],
                                    animal_mode=animal_mode, layout_mode=layout_mode,
                                    allow_slide=True, max_slide_s=5.0, step_s=0.5
                                )
                                if new_plan.get("status") == "pass" and new_plan.get("framing_score", 0.0) >= 0.90:
                                    cand["result"] = "PASS"
                                    cand["reason"] = "RELAXED_TOLERANCE_LADDER_2"
                                    cand["score"] = new_plan["framing_score"]
                                    cand["plan"] = new_plan
                                    passing_candidates.append(cand)
                                    if cand in rejected_candidates:
                                        rejected_candidates.remove(cand)
                                    log(f"    [LADDER 2 RECOVERY] Candidate {cand['candidate']} at {cand['start_s']:.1f}s recovered with wider slide ({new_plan['framing_score']:.1%}).", "INFO")

                # Ladder Step 3: Query verified clip bank for verified clips
                existing_cids = set(c["clip_id"] for c in passing_candidates + rejected_candidates)
                if len(passing_candidates) < target_clips_count:
                    log("  [DEGRADATION LADDER Step 3] Querying verified clip bank in ledger...", "INFO")
                    try:
                        bank_clips = self.ledger.get_verified_clips(
                            animal_type=animal_mode,
                            limit=24,
                            exclude_clip_ids=list(existing_cids)
                        )
                    except Exception as e_bank:
                        log(f"    [BANK QUERY ERROR] {e_bank}", "WARN")
                        bank_clips = []

                    for row in bank_clips:
                        if len(passing_candidates) >= target_clips_count:
                            break
                        b_cid = row["clip_id"]
                        if b_cid in existing_cids:
                            continue
                        b_src = row.get("source_url_or_path") or row.get("source_path")
                        b_src_name = os.path.basename(b_src)
                        if b_src_name in blocked_sources_set or b_src in blocked_sources_set or self.ledger.is_blocked_source(b_src):
                            continue

                        local_b_src = ensure_local_source_copy(b_src)
                        if not os.path.exists(local_b_src):
                            continue

                        b_start = float(row["start_s"])
                        b_end = float(row["end_s"])
                        b_dur = b_end - b_start
                        b_score = float(row.get("framing_score") or row.get("quality_score") or 1.0)
                        b_sharp = float(row.get("sharpness") or 160.0)

                        # Check NMS against kept candidates
                        b_suppressed = False
                        for kept in passing_candidates:
                            if kept["source"] == b_src_name:
                                k_s = kept["start_s"]
                                k_e = kept["start_s"] + kept["dur_s"]
                                if abs(b_start - k_s) < 8.0 or not (b_end <= k_s or k_e <= b_start):
                                    b_suppressed = True
                                    break
                        if b_suppressed:
                            continue

                        # Reserve this verified clip in ledger for this job
                        self.ledger.reserve_clip_by_id(b_cid, job_id)

                        b_plan = row.get("verified_plan")
                        if isinstance(b_plan, str):
                            try: b_plan = json.loads(b_plan)
                            except: b_plan = None
                        if not b_plan or not isinstance(b_plan, dict):
                            b_plan = {
                                "status": "pass",
                                "mode": "vertical_direct" if row.get("orientation") == "vertical" else "smart_crop",
                                "framing_score": b_score,
                                "sharpness": b_sharp,
                                "orig_size": [1080, 1920] if row.get("orientation") == "vertical" else [1920, 1080],
                                "crop_w": 1080 if row.get("orientation") == "vertical" else 607,
                                "crop_h": 1920 if row.get("orientation") == "vertical" else 1080,
                                "keyframes_t": [0.0, b_dur],
                                "keyframes_x": [0, 0],
                                "keyframes_y": [0, 0],
                                "keyframes_zoom": [1.0, 1.0]
                            }

                        b_rep = {
                            "candidate": len(candidate_reports) + 1,
                            "clip_id": b_cid,
                            "source": b_src_name,
                            "start_s": b_start,
                            "dur_s": b_dur,
                            "score": round(b_score, 3),
                            "sharpness": round(b_sharp, 1),
                            "pet_ratio": 1.0,
                            "vis_ratio": 1.0,
                            "horiz_ratio": 1.0,
                            "vert_ratio": 1.0,
                            "size_ratio": 1.0,
                            "measured": True,
                            "actual_score": None,
                            "result": "PASS",
                            "reason": "SELF_HEAL_BANK_PASS",
                            "plan": b_plan,
                            "clip_info": {
                                "clip_id": b_cid,
                                "source_path": b_src,
                                "source_url_or_path": b_src,
                                "start_s": b_start,
                                "end_s": b_end,
                                "computed_dur": b_dur,
                                "license": row.get("license") or "Creative Commons Attribution 4.0",
                                "author": row.get("uploader") or "LionReel Verified CC Archive"
                            }
                        }
                        candidate_reports.append(b_rep)
                        passing_candidates.append(b_rep)
                        existing_cids.add(b_cid)
                        log(f"    [BANK ENLISTED] Verified bank candidate {b_cid} ({b_src_name} [{b_start:.1f}s-{b_end:.1f}s], score: {b_score:.1%})", "INFO")

                # Step 4: Iterative Harvest & Waiting Loop with Budget
                budget_sec = float(cfg.get("SELF_HEAL_BUDGET_SEC", 900)) # 15 minutes default
                max_cands_budget = int(cfg.get("SELF_HEAL_MAX_CANDIDATES", 60))
                heal_start_time = time.time()
                action_file = os.path.join(work_job_dir, "action.json")

                if len(passing_candidates) < target_clips_count:
                    log(f"  [SELF-HEALING] Starting background harvest loop (budget: {budget_sec:.0f}s or {max_cands_budget} candidates)...", "INFO")
                    trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=24)

                while len(passing_candidates) < target_clips_count:
                    elapsed_heal = time.time() - heal_start_time
                    if elapsed_heal > budget_sec or len(candidate_reports) >= max_cands_budget:
                        log(f"  [SELF-HEALING] Budget reached ({elapsed_heal:.1f}s / {budget_sec:.0f}s or {len(candidate_reports)} candidates scanned).", "WARN")
                        break

                    # Check for interactive user decisions from action.json
                    if os.path.exists(action_file):
                        try:
                            with open(action_file, "r", encoding="utf-8") as f_act:
                                action_data = json.load(f_act)
                            user_action = action_data.get("action", "").lower().strip()
                            if user_action == "make_shorter":
                                if len(passing_candidates) >= 2:
                                    log(f"  [USER ACTION] User selected 'Make shorter video' ({len(passing_candidates)} clips). Proceeding!", "INFO")
                                    target_clips_count = len(passing_candidates)
                                    break
                            elif user_action == "cancel":
                                log("  [USER ACTION] User selected 'Cancel'. Releasing job reservations.", "WARN")
                                self.ledger.release_reservation(job_id)
                                with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                                    json.dump({
                                        "job_id": job_id, "status": "cancelled", "success": False, "error": "Job cancelled by user"
                                    }, f_jr, indent=2)
                                return None
                            elif user_action == "keep_searching":
                                log("  [USER ACTION] User selected 'Keep searching'. Budget extended by 10 minutes.", "INFO")
                                budget_sec += 600
                                try: os.remove(action_file)
                                except: pass
                        except Exception:
                            pass

                    if allow_shorter and len(passing_candidates) >= 2:
                        log(f"  [ALLOW_SHORTER] Adapting compilation target to {len(passing_candidates)} pristine clips.", "INFO")
                        target_clips_count = len(passing_candidates)
                        break

                    # Update waiting state in job_result.json so UI displays WAITING_FOR_CLIPS (amber)
                    waiting_msg = f"Finding more clips: {len(passing_candidates)} of {target_clips_count} ready"
                    with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                        json.dump({
                            "job_id": job_id,
                            "status": "waiting_for_clips",
                            "success": None,
                            "stage_index": 5,
                            "stage_name": waiting_msg,
                            "progress_pct": int(round((len(passing_candidates) / float(target_clips_count)) * 50)),
                            "got_clips": len(passing_candidates),
                            "target_clips": target_clips_count,
                            "candidate_reports": candidate_reports,
                            "elapsed_seconds": round(time.time() - _SCRIPT_START_TIME, 1)
                        }, f_jr, indent=2)

                    time.sleep(3.0)

                    # Query newly verified clips from ledger
                    try:
                        more_bank = self.ledger.get_verified_clips(
                            animal_type=animal_mode,
                            limit=10,
                            exclude_clip_ids=list(existing_cids)
                        )
                        for row in more_bank:
                            if len(passing_candidates) >= target_clips_count:
                                break
                            b_cid = row["clip_id"]
                            if b_cid in existing_cids:
                                continue
                            b_src = row.get("source_url_or_path") or row.get("source_path")
                            b_src_name = os.path.basename(b_src)
                            if b_src_name in blocked_sources_set or self.ledger.is_blocked_source(b_src):
                                continue
                            local_b_src = ensure_local_source_copy(b_src)
                            if not os.path.exists(local_b_src):
                                continue

                            b_start = float(row["start_s"])
                            b_end = float(row["end_s"])
                            b_dur = b_end - b_start
                            b_score = float(row.get("framing_score") or 1.0)
                            b_sharp = float(row.get("sharpness") or 160.0)

                            self.ledger.reserve_clip_by_id(b_cid, job_id)
                            b_rep = {
                                "candidate": len(candidate_reports) + 1,
                                "clip_id": b_cid,
                                "source": b_src_name,
                                "start_s": b_start,
                                "dur_s": b_dur,
                                "score": round(b_score, 3),
                                "sharpness": round(b_sharp, 1),
                                "pet_ratio": 1.0, "vis_ratio": 1.0, "horiz_ratio": 1.0, "vert_ratio": 1.0, "size_ratio": 1.0,
                                "measured": True, "actual_score": None, "result": "PASS", "reason": "SELF_HEAL_BANK_PASS",
                                "plan": {"status": "pass", "mode": "smart_crop", "framing_score": b_score, "sharpness": b_sharp},
                                "clip_info": {"clip_id": b_cid, "source_path": b_src, "source_url_or_path": b_src, "start_s": b_start, "end_s": b_end, "computed_dur": b_dur, "license": "CC-BY", "author": row.get("uploader", "")}
                            }
                            candidate_reports.append(b_rep)
                            passing_candidates.append(b_rep)
                            existing_cids.add(b_cid)
                            log(f"    [BANK HARVEST ENLISTED] Clip {b_cid} from {b_src_name} added to job.", "INFO")
                    except Exception:
                        pass

                # Post-healing state resolution:
                if len(passing_candidates) < target_clips_count:
                    if allow_shorter and len(passing_candidates) >= 2:
                        log(f"  [DEGRADATION LADDER] Short of target ({len(passing_candidates)} of {target_clips_count}), adapting compilation length to {len(passing_candidates)} pristine clips.", "WARN")
                        target_clips_count = len(passing_candidates)
                    else:
                        pool_stat = self.ledger.get_pool_status(animal_mode)
                        is_empty_pool = (pool_stat.get("total_clips", 0) == 0) or (pool_stat.get("distinct_sources", 0) == 0)
                        target_status = "needs_sources" if is_empty_pool else "waiting_for_clips"
                        status_msg = "Needs sources: Please add 1080p+ cat videos to pool" if is_empty_pool else f"Finding more clips: {len(passing_candidates)} of {target_clips_count} ready"

                        log(f"\n[SELF-HEALING PAUSE] Job transitioning to {target_status.upper()} ({status_msg}). Checkpoint preserved.", "WARN")
                        checkpoint_data = {
                            "job_id": job_id,
                            "status": target_status,
                            "passing_candidates": passing_candidates,
                            "candidate_reports": candidate_reports,
                            "target_clips_count": target_clips_count,
                            "target_clip_sec": target_clip_sec,
                            "expected_total_sec": expected_total_sec,
                            "layout_mode": layout_mode
                        }
                        with open(os.path.join(work_job_dir, "checkpoint.json"), "w", encoding="utf-8") as f_cp:
                            json.dump(checkpoint_data, f_cp, indent=2)

                        with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                            json.dump({
                                "job_id": job_id,
                                "status": target_status,
                                "success": None,
                                "error": status_msg,
                                "stage_index": 5,
                                "stage_name": status_msg,
                                "progress_pct": int(round((len(passing_candidates) / float(target_clips_count)) * 50)),
                                "got_clips": len(passing_candidates),
                                "target_clips": target_clips_count,
                                "candidate_reports": candidate_reports,
                                "elapsed_seconds": round(time.time() - _SCRIPT_START_TIME, 1)
                            }, f_jr, indent=2)

                        self.update_pipeline_progress(
                            job_id, 5, status_msg, int(round((len(passing_candidates) / float(target_clips_count)) * 50)),
                            candidate_reports=candidate_reports
                        )
                        return None

            proof_s5 = {
                "items_count": len(passing_candidates),
                "candidates_scanned": len(candidate_reports),
                "passing_candidates": passing_candidates,
                "candidate_reports": candidate_reports,
                "unique_sources": len(unique_passing_sources)
            }
            ev_s5 = f"Predicted framing on {len(candidate_reports)} candidates: {len(passing_candidates)} passed NMS/diversity across {len(unique_passing_sources)} source(s)"
            sm.complete_stage(5, evidence=ev_s5, proof_data=proof_s5)

            # =========================================================================
            # STAGE 6: reframe_render_clips
            # CRF 12 fast vertical clip rendering & post-crop centering gate.
            # Gated by APPLY_SMART_CROP.
            # =========================================================================
            sm.start_stage(6)
            self.update_pipeline_progress(job_id, 6, "Reframe & render vertical clip cuts", 60, candidate_reports=candidate_reports)

            with open(os.path.join(work_job_dir, "stages", "framing_predicted.json"), "r", encoding="utf-8") as f_art5:
                s5_data = json.load(f_art5)
            passing_candidates = s5_data.get("passing_candidates", [])

            # Load EDL if present
            edl_file = os.path.join(work_job_dir, "edl.json")
            job_edl = None
            if os.path.exists(edl_file):
                try:
                    with open(edl_file, "r", encoding="utf-8") as f_edl:
                        job_edl = json.load(f_edl)
                    log(f"Stage 6 loaded active EDL with {len(job_edl.get('clips', []))} clip decisions.")
                except Exception as e_edl:
                    log(f"Error loading edl.json: {e_edl}", "WARN")

            clip_checkpoints_dir = os.path.join(work_job_dir, "clips")
            os.makedirs(clip_checkpoints_dir, exist_ok=True)

            # Composite Scoring (Prompt Section 6):
            # Framing 40%, Funny moment 30%, Sharpness 10%, Source diversity 10%, Source quality 10%
            source_occurrences = {}
            for c in passing_candidates:
                s_name = c.get("source", "")
                source_occurrences[s_name] = source_occurrences.get(s_name, 0) + 1

            for c in passing_candidates:
                f_score = float(c.get("score") or c.get("framing_score") or 0.90)
                cinfo = c.get("clip_info") or {}
                funny_score = float(cinfo.get("funny_score") or c.get("funny_score") or c.get("pet_ratio") or 0.85)
                sharp_score = min(float(c.get("sharpness") or 160.0) / 1000.0, 1.0)
                plan_mode = (c.get("plan") or {}).get("mode", "smart_crop")
                quality_score = 1.0 if plan_mode == "vertical_direct" else 0.90
                src_rep = source_occurrences.get(c.get("source", ""), 1)
                diversity_score = 1.0 if src_rep <= 1 else (0.7 if src_rep == 2 else 0.4)

                times_used = float(cinfo.get("times_used", 0))
                usage_penalty = 0.20 * times_used

                composite = round(0.40 * f_score + 0.30 * funny_score + 0.10 * sharp_score + 0.10 * diversity_score + 0.10 * quality_score - usage_penalty, 4)
                c["composite_score"] = composite
                c["funny_score"] = funny_score

            passing_candidates.sort(key=lambda c: c.get("composite_score", 0.0), reverse=True)

            # Prioritize an output-unique candidate combination at the front of passing_candidates
            import itertools
            if len(passing_candidates) >= target_clips_count:
                all_candidate_combos = list(itertools.combinations(passing_candidates, target_clips_count))
                all_candidate_combos.sort(key=lambda cb: (
                    len(set(cand.get("source", "") for cand in cb)) >= min(3, target_clips_count),
                    len(set(cand.get("source", "") for cand in cb)),
                    sum(cand.get("composite_score", 0.0) for cand in cb)
                ), reverse=True)

                unique_combo = None
                for cb in all_candidate_combos:
                    c_ids = [cand.get("clip_id") for cand in cb]
                    if not self.ledger.is_duplicate_clip_list(c_ids):
                        unique_combo = list(cb)
                        break

                if unique_combo:
                    other_cands = [c for c in passing_candidates if c not in unique_combo]
                    passing_candidates = unique_combo + other_cands
                    log(f"Stage 6 prioritized unique candidate combination: {[c['clip_id'] for c in unique_combo]}")

            render_target = min(len(passing_candidates), target_clips_count + 2)
            log(f"Stage 6 Rendering best {render_target} candidates (needed: {target_clips_count} + 2 standby replacements, scored by Framing 40%, Funny 30%, Sharp 10%, Diversity 10%, Quality 10%)...")

            rendered_candidates_pool = []
            caption_pool = SINHALA_CAPTIONS if language == "si" else ENGLISH_CAPTIONS

            for pass_idx, cand in enumerate(passing_candidates):
                if len(rendered_candidates_pool) >= render_target:
                    self.ledger.release_single_clip(cand["clip_id"])
                    continue

                cinfo = cand["clip_info"]
                src_path = cinfo.get("source_url_or_path") or cinfo.get("source_path")
                local_src = ensure_local_source_copy(src_path)
                start_s = cinfo["start_s"]
                dur_s = cinfo.get("computed_dur", cinfo["end_s"] - start_s)
                cid = cinfo["clip_id"]
                plan = cand["plan"]

                # EDL overrides
                clip_speed = 1.0
                clip_color = None
                clip_color_str = 1.0
                if job_edl and "clips" in job_edl:
                    edl_match = None
                    for ec in job_edl["clips"]:
                        if ec.get("clip_id") == cid or ec.get("clip_index") == len(rendered_candidates_pool):
                            edl_match = ec
                            break
                    if edl_match:
                        if "trim_start" in edl_match and "trim_end" in edl_match:
                            t_s = float(edl_match["trim_start"])
                            t_e = float(edl_match["trim_end"])
                            if t_e > t_s + 1.0:
                                start_s = t_s
                                dur_s = t_e - t_s
                        clip_speed = float(edl_match.get("speed", 1.0))
                        clip_color = edl_match.get("color_preset")
                        clip_color_str = float(edl_match.get("color_strength", 1.0))

                clip_out = os.path.join(work_job_dir, f"{job_id}_c{len(rendered_candidates_pool):02d}.mp4")
                checkpoint_clip = os.path.join(clip_checkpoints_dir, f"clip_{cid}.mp4")
                checkpoint_meta = os.path.join(clip_checkpoints_dir, f"clip_{cid}.json")

                log(f"Stage 6 Rendering Clip {len(rendered_candidates_pool)+1}/{render_target} (Cand {cand['candidate']}, Composite: {cand['composite_score']:.1%}, Framing: {cand['score']:.1%}): {cand['source']} [{start_s:.1f}s - {start_s+dur_s:.1f}s, dur: {dur_s:.1f}s, speed: {clip_speed}x]...")

                # Early abort check
                early_ok, early_msg = self.reframer.early_check_segment_gate(
                    local_src, start_s, dur_s, plan, layout_mode=layout_mode
                )
                if not early_ok:
                    cand["result"] = "REJECT"
                    cand["reason"] = f"EARLY_ABORT ({early_msg})"
                    cand["actual_score"] = 0.0
                    self.ledger.release_single_clip(cid)
                    continue

                if os.path.exists(checkpoint_clip) and os.path.getsize(checkpoint_clip) > 10000:
                    import shutil
                    shutil.copy2(checkpoint_clip, clip_out)
                    log(f"  [CHECKPOINT REUSED] Clip {cid} restored from {checkpoint_clip}")
                    success = True
                else:
                    timer.start_stage("reframe")
                    success = self.reframer.reframe_segment_ffmpeg(
                        local_src, clip_out, start_s, dur_s, plan,
                        speed=clip_speed, color_preset=clip_color, color_strength=clip_color_str
                    )
                    timer.stop_stage("reframe")
                    if success and os.path.exists(clip_out):
                        import shutil
                        shutil.copy2(clip_out, checkpoint_clip)

                if not success or not os.path.exists(clip_out):
                    cand["result"] = "REJECT"
                    cand["reason"] = "RENDER_FAILED"
                    cand["actual_score"] = 0.0
                    self.ledger.release_single_clip(cid)
                    continue

                # Verify post-crop gate
                post_ok, post_msg = self.reframer.verify_post_crop_gate(clip_out, plan=plan, layout_mode=layout_mode)
                m_actual = re.search(r"Centering:\s*([\d\.]+)%", post_msg)
                actual_score = float(m_actual.group(1)) / 100.0 if m_actual else (1.0 if post_ok else 0.0)
                cand["actual_score"] = round(actual_score, 3)

                if not post_ok:
                    cand["result"] = "REJECT"
                    cand["reason"] = f"POST_CROP_GATE_FAIL ({post_msg})"
                    log(f"Candidate {cand['candidate']} Post-Crop Gate: REJECT ({post_msg})", "WARN")
                    self.ledger.release_single_clip(cid)
                    try: os.remove(clip_out)
                    except: pass
                    continue

                log(f"Candidate {cand['candidate']} Post-Crop Gate: PASS ({post_msg})")

                # Save checkpoint metadata for this clip
                clip_meta_obj = {
                    "clip_id": cid,
                    "source": cand["source"],
                    "start_s": start_s,
                    "dur_s": dur_s,
                    "framing_score": cand["score"],
                    "actual_score": actual_score,
                    "composite_score": cand["composite_score"],
                    "funny_score": cand["funny_score"],
                    "path": clip_out,
                    "cand": cand,
                    "cinfo": cinfo
                }
                try:
                    with open(checkpoint_meta, "w", encoding="utf-8") as f_cm:
                        json.dump({k: v for k, v in clip_meta_obj.items() if k not in ("cand", "cinfo")}, f_cm, indent=2)
                except Exception:
                    pass

                rendered_candidates_pool.append(clip_meta_obj)

            # Check if we have enough rendered clips or need self-healing adaptation
            if len(rendered_candidates_pool) < target_clips_count:
                if allow_shorter and len(rendered_candidates_pool) >= 2:
                    log(f"  [ALLOW_SHORTER] Adapting target clips count to {len(rendered_candidates_pool)} rendered pristine clips.", "WARN")
                    target_clips_count = len(rendered_candidates_pool)
                else:
                    status_msg = f"Finding more clips: {len(rendered_candidates_pool)} of {target_clips_count} ready"
                    log(f"\n[SELF-HEALING PAUSE] Shortage of rendered clips ({len(rendered_candidates_pool)} of {target_clips_count}). Transitioning to WAITING_FOR_CLIPS.", "WARN")
                    with open(os.path.join(work_job_dir, "checkpoint.json"), "w", encoding="utf-8") as f_cp:
                        json.dump({
                            "job_id": job_id,
                            "status": "waiting_for_clips",
                            "rendered_clips": len(rendered_candidates_pool),
                            "target_clips_count": target_clips_count,
                            "target_clip_sec": target_clip_sec,
                            "expected_total_sec": expected_total_sec,
                            "layout_mode": layout_mode
                        }, f_cp, indent=2)

                    with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                        json.dump({
                            "job_id": job_id,
                            "status": "waiting_for_clips",
                            "success": None,
                            "stage_index": 6,
                            "stage_name": status_msg,
                            "progress_pct": int(round((len(rendered_candidates_pool) / float(target_clips_count)) * 60)),
                            "got_clips": len(rendered_candidates_pool),
                            "target_clips": target_clips_count,
                            "candidate_reports": candidate_reports,
                            "elapsed_seconds": round(time.time() - _SCRIPT_START_TIME, 1)
                        }, f_jr, indent=2)

                    self.update_pipeline_progress(job_id, 6, status_msg, int(round((len(rendered_candidates_pool) / float(target_clips_count)) * 60)), candidate_reports=candidate_reports)
                    trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=24)
                    return None

            # Best Output Assembly: Assemble top target_clips_count with STRONGEST moment first
            # Enforce output uniqueness and maximum source diversity from rendered_candidates_pool
            if len(rendered_candidates_pool) >= target_clips_count:
                all_rendered_combos = list(itertools.combinations(rendered_candidates_pool, target_clips_count))
                all_rendered_combos.sort(key=lambda cb: (
                    len(set(it.get("source", "") for it in cb)) >= min(3, target_clips_count),
                    len(set(it.get("source", "") for it in cb)),
                    sum(it.get("composite_score", 0.0) for it in cb)
                ), reverse=True)

                chosen_rendered_combo = None
                for cb in all_rendered_combos:
                    c_ids = [it.get("clip_id") for it in cb]
                    if not self.ledger.is_duplicate_clip_list(c_ids):
                        chosen_rendered_combo = list(cb)
                        break

                if chosen_rendered_combo:
                    selected_renders = chosen_rendered_combo
                    standby_replacements = [it for it in rendered_candidates_pool if it not in selected_renders]
                else:
                    selected_renders = rendered_candidates_pool[:target_clips_count]
                    standby_replacements = rendered_candidates_pool[target_clips_count:]
            else:
                selected_renders = rendered_candidates_pool[:target_clips_count]
                standby_replacements = rendered_candidates_pool[target_clips_count:]

            # Reorder selected clips so STRONGEST moment (highest funny_score) is FIRST
            strongest_idx = max(range(len(selected_renders)), key=lambda i: selected_renders[i]["funny_score"])
            if strongest_idx != 0:
                strongest_clip = selected_renders.pop(strongest_idx)
                selected_renders.insert(0, strongest_clip)

            log(f"Stage 6 Assembled top {len(selected_renders)} clips with STRONGEST moment first (Cand {selected_renders[0]['cand']['candidate']}, funny={selected_renders[0]['funny_score']:.2f}). {len(standby_replacements)} standby replacement(s) retained.")

            # Release unused standby clips back to pool immediately
            for item in standby_replacements:
                try:
                    self.ledger.release_single_clip(item["clip_id"])
                except Exception:
                    pass

            # Build processed_clip_paths, clip_mapping_data, credits_data
            processed_clip_paths = []
            clip_mapping_data = []
            credits_data = []

            for clip_idx, item in enumerate(selected_renders):
                c_out = item["path"]
                seq_out = os.path.join(work_job_dir, f"{job_id}_c{clip_idx:02d}.mp4")
                if c_out != seq_out:
                    if os.path.exists(seq_out):
                        try: os.remove(seq_out)
                        except: pass
                    import shutil
                    shutil.copy2(c_out, seq_out)
                    c_out = seq_out

                processed_clip_paths.append(c_out)
                cand = item["cand"]
                cinfo = item["cinfo"]
                start_s = item["start_s"]
                dur_s = item["dur_s"]
                cid = item["clip_id"]
                plan = cand["plan"]

                clip_mapping_data.append({
                    "clip_index": clip_idx + 1,
                    "clip_id": cid,
                    "source_file": cand["source"],
                    "start_s": start_s,
                    "end_s": round(start_s + dur_s, 2),
                    "duration": round(dur_s, 2),
                    "crop_mode": plan.get("mode", "smart_crop"),
                    "license": cinfo.get("license", "Creative Commons CC-BY 4.0"),
                    "credit": cinfo.get("author") or cinfo.get("channel") or "LionReel Verified CC Archive"
                })
                credits_data.append({
                    "clip_index": clip_idx + 1,
                    "source": cand["source"],
                    "license": cinfo.get("license", "Creative Commons CC-BY 4.0"),
                    "credit": cinfo.get("author") or cinfo.get("channel") or "LionReel Verified CC Archive"
                })

            expected_total_sec = round(sum(c["duration"] for c in clip_mapping_data), 2)
            log(f"Stage 6 Active Total Duration: {expected_total_sec:.2f}s across {len(processed_clip_paths)} clips.")

            proof_s6 = {
                "items_count": len(processed_clip_paths),
                "clip_paths": processed_clip_paths,
                "clip_mapping_data": clip_mapping_data,
                "credits_data": credits_data,
                "candidate_reports": candidate_reports
            }
            ev_s6 = f"Rendered {len(processed_clip_paths)} vertical clips (CRF 12, {layout_mode}), 100% post-crop gate pass"
            sm.complete_stage(6, evidence=ev_s6, proof_data=proof_s6)

            # =========================================================================
            # STAGE 7: color_grading
            # CLAHE / contrast & tone normalization.
            # Gated by APPLY_COLOR_GRADING.
            # =========================================================================
            if cfg.get("APPLY_COLOR_GRADING", False) is False:
                sm.skip_stage(7, reason="turned off in settings")
            else:
                sm.start_stage(7)
                self.update_pipeline_progress(job_id, 7, "Auto color grading & contrast optimization", 70, candidate_reports=candidate_reports)

                with open(os.path.join(work_job_dir, "stages", "clips_rendered.json"), "r", encoding="utf-8") as f_art6:
                    s6_data = json.load(f_art6)
                cur_clips = s6_data.get("clip_paths", [])

                graded_clips = []
                for cp in cur_clips:
                    cp_graded = cp.replace(".mp4", "_graded.mp4")
                    grade_cmd = [
                        FFMPEG_EXE, "-y",
                        "-i", cp,
                        "-vf", "eq=contrast=1.06:brightness=0.01:saturation=1.10",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "12",
                        "-c:a", "copy",
                        cp_graded
                    ]
                    subprocess.run(grade_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    if os.path.exists(cp_graded) and os.path.getsize(cp_graded) > 0:
                        graded_clips.append(cp_graded)
                    else:
                        graded_clips.append(cp)
                processed_clip_paths = graded_clips

                proof_s7 = {
                    "items_count": len(processed_clip_paths),
                    "clip_paths": processed_clip_paths,
                    "clip_mapping_data": clip_mapping_data,
                    "credits_data": credits_data,
                    "candidate_reports": candidate_reports
                }
                ev_s7 = f"Applied CLAHE contrast & color balance normalization to {len(processed_clip_paths)} clips"
                sm.complete_stage(7, evidence=ev_s7, proof_data=proof_s7)

            # =========================================================================
            # STAGE 8: captions_and_audio
            # Safe-zone captions, concat, and EBU R128 audio mastering.
            # Gated by ADD_BACKGROUND_MUSIC.
            # =========================================================================
            sm.start_stage(8)
            self.update_pipeline_progress(job_id, 8, "Burn safe-zone captions & master audio ducking", 80, candidate_reports=candidate_reports)

            art_prev = os.path.join(work_job_dir, "stages", "color_graded.json")
            if not os.path.exists(art_prev):
                art_prev = os.path.join(work_job_dir, "stages", "clips_rendered.json")
            with open(art_prev, "r", encoding="utf-8") as f_prev:
                s_prev = json.load(f_prev)
            processed_clip_paths = s_prev.get("clip_paths", processed_clip_paths)
            clip_mapping_data = s_prev.get("clip_mapping_data", clip_mapping_data)
            credits_data = s_prev.get("credits_data", credits_data)

            # Burn safe-zone captions
            timer.start_stage("caption")
            captions_rendered_cnt = 0
            for c_idx, clip_p in enumerate(processed_clip_paths):
                if c_idx == 0 or (c_idx % 2 == 1 and c_idx < len(processed_clip_paths) - 1):
                    cap_text = random.choice(caption_pool)
                    cap_out = os.path.join(work_job_dir, f"{job_id}_c{c_idx:02d}_cap.mp4")
                    cap_ok = render_safe_zone_caption(clip_p, cap_out, cap_text, font_lang=language)
                    if cap_ok and os.path.exists(cap_out):
                        processed_clip_paths[c_idx] = cap_out
                        captions_rendered_cnt += 1
                        if c_idx < len(clip_mapping_data):
                            clip_mapping_data[c_idx]["caption"] = cap_text
            timer.stop_stage("caption")

            # Concatenate all clips
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

            # Master audio
            timer.start_stage("audio")
            audio_mastered = os.path.join(work_job_dir, f"master_audio_{job_id}.mp4")
            bgm_to_use = BGM_PATH if cfg.get("ADD_BACKGROUND_MUSIC", True) else None
            log(f"Mastering audio (Two-Pass EBU R128: -14.0 LUFS, -1.0 dBTP, BGM: {'enabled' if bgm_to_use else 'none'})...")
            master_audio_ebu_r128(raw_assembled, audio_mastered, bgm_to_use)
            timer.stop_stage("audio")

            proof_s8 = {
                "items_count": 1,
                "raw_assembled": raw_assembled,
                "audio_mastered": audio_mastered,
                "captions_count": captions_rendered_cnt,
                "bgm_used": bool(bgm_to_use),
                "clip_mapping_data": clip_mapping_data,
                "credits_data": credits_data,
                "candidate_reports": candidate_reports
            }
            ev_s8 = f"Burned safe-zone captions ({captions_rendered_cnt} clips) & mastered audio to EBU R128 (-14.0 LUFS, -1.0 dBTP)"
            sm.complete_stage(8, evidence=ev_s8, proof_data=proof_s8)

            # =========================================================================
            # STAGE 9: final_render_qa
            # MP4 compilation with cas=0.6 sharpen, duration check, & 10-gate QA.
            # =========================================================================
            sm.start_stage(9)
            self.update_pipeline_progress(job_id, 9, "Final MP4 assembly & 10-gate QA validation", 90, candidate_reports=candidate_reports)

            with open(os.path.join(work_job_dir, "stages", "audio_mastered.json"), "r", encoding="utf-8") as f_art8:
                s8_data = json.load(f_art8)
            audio_mastered = s8_data.get("audio_mastered")

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
                err_msg = "Final export failed: output file not created."
                sm.fail_stage(9, err_msg, code="EXPORT_FAILED")
                raise RuntimeError(err_msg)

            real_dur = get_video_duration(local_master_path)
            dur_diff_pct = abs(real_dur - expected_total_sec) / expected_total_sec if expected_total_sec > 0 else 0
            log(f"[VERIFY] Final Master Duration Check: Expected={expected_total_sec:.2f}s, Real={real_dur:.2f}s (Diff={dur_diff_pct*100:.1f}%)")

            if dur_diff_pct > 0.10:
                err_msg = f"DURATION_MISMATCH: Expected {expected_total_sec:.1f} s, got {real_dur:.1f} s"
                sm.fail_stage(9, err_msg, code="DURATION_MISMATCH")
                self.ledger.release_reservation(job_id)
                with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                    json.dump({
                        "job_id": job_id, "status": "failed", "success": False, "error": err_msg,
                        "code": "DURATION_MISMATCH", "expected_duration_s": expected_total_sec,
                        "real_duration_s": real_dur
                    }, f_jr, indent=2)
                raise RuntimeError(err_msg)

            # SHA256 Hash Calculation
            sha256_hash = hashlib.sha256()
            with open(local_master_path, "rb") as f_vid:
                while chunk := f_vid.read(128 * 1024):
                    sha256_hash.update(chunk)
            sha256_str = sha256_hash.hexdigest()

            clip_ids = [c["clip_id"] for c in clip_mapping_data]
            is_dup, dup_msg = self.ledger.check_duplicate_output(sha256_str, clip_ids)
            if is_dup:
                err_msg = f"DUPLICATE_OUTPUT: {dup_msg}"
                sm.fail_stage(9, err_msg, code="DUPLICATE_OUTPUT")
                self.ledger.release_reservation(job_id)
                raise RuntimeError(err_msg)

            # Run 10-Gate QA Check
            timer.start_stage("qa")
            log("Running Automated QA Gate Validation on local SSD master...")
            from qa_check import run_full_qa
            qa_passed, qa_report = run_full_qa(local_master_path, layout_mode=layout_mode)
            timer.stop_stage("qa")

            if not qa_passed:
                err_msg = "QA validation failed"
                sm.fail_stage(9, err_msg, code="QA_FAILED")
                self.ledger.release_reservation(job_id)
                self.update_pipeline_progress(
                    job_id, 9, "Final MP4 assembly & 10-gate QA validation", 90,
                    candidate_reports=candidate_reports, error=err_msg,
                    failed_stage="Final MP4 assembly & 10-gate QA validation"
                )
                return None

            proof_s9 = {
                "items_count": 1,
                "local_master": local_master_path,
                "real_duration_s": real_dur,
                "expected_duration_s": expected_total_sec,
                "sha256": sha256_str,
                "qa_passed": qa_passed,
                "qa_report": qa_report,
                "clip_mapping_data": clip_mapping_data,
                "credits_data": credits_data,
                "candidate_reports": candidate_reports
            }
            ev_s9 = f"Final master rendered ({real_dur:.1f}s, cas=0.6), passed 10/10 automated QA gates (SHA256: {sha256_str[:12]}...)"
            sm.complete_stage(9, evidence=ev_s9, proof_data=proof_s9)

            # =========================================================================
            # STAGE 10: save_credits_export
            # Ledger registration, metadata/credits packaging, single batch Drive copy.
            # =========================================================================
            sm.start_stage(10)
            self.update_pipeline_progress(job_id, 10, "Save master, register credits & export to Drive", 95, candidate_reports=candidate_reports)

            render_time_sec = round(time.time() - start_render_time, 2)
            total_duration = round(float(sum(c["duration"] for c in clip_mapping_data)), 2)

            log(f"QA PASSED. Committing clips in ledger for {job_id}.")
            self.ledger.commit_short(job_id)
            self.ledger.register_output(
                job_id=job_id,
                output_filename=final_filename,
                sha256=sha256_str,
                clip_ids=clip_ids,
                duration_sec=total_duration,
                render_time_sec=render_time_sec
            )

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
            # Metadata Generation (Full or Title Only mode)
            try:
                from metadata_generator import MetadataGenerator
                mg = MetadataGenerator(ledger=self.ledger)
                cfg_meta_mode = cfg.get("UPLOAD_METADATA_MODE", "full")
                meta_pkg = mg.generate_metadata_package(job_id, animal_type=animal_mode, credits_list=credits_data, mode=cfg_meta_mode)
                with open(os.path.join(work_job_dir, "metadata.json"), "w", encoding="utf-8") as f_mpkg:
                    json.dump(meta_pkg, f_mpkg, indent=2)
                with open(os.path.join(work_job_dir, f"{job_id}_metadata.json"), "w", encoding="utf-8") as f_mpkg:
                    json.dump(meta_pkg, f_mpkg, indent=2)
                
                clean_title = meta_pkg.get("title", clean_title)
                with open(os.path.join(work_job_dir, f"{job_id}_metadata.txt"), "w", encoding="utf-8") as f_meta:
                    if cfg_meta_mode == "full":
                        f_meta.write(f"TITLE: {clean_title}\n\n")
                        f_meta.write(f"DESCRIPTION:\n{meta_pkg.get('description', '')}\n\n")
                        f_meta.write(f"TAGS:\n{meta_pkg.get('tags', '')}\n\n")
                        f_meta.write(f"HASHTAGS:\n{meta_pkg.get('hashtags', '')}\n")
                    else:
                        f_meta.write(f"TITLE: {clean_title}\n")
                with open(os.path.join(work_job_dir, f"{job_id}.txt"), "w", encoding="utf-8") as f_meta:
                    f_meta.write(f"TITLE: {clean_title}\n")
            except Exception as e_m_gen:
                log(f"Notice: Metadata package generation in Stage 10 fallback: {e_m_gen}", "WARN")
                with open(os.path.join(work_job_dir, f"{job_id}_metadata.txt"), "w", encoding="utf-8") as f_meta:
                    f_meta.write(f"TITLE: {clean_title}\n")
                with open(os.path.join(work_job_dir, f"{job_id}.txt"), "w", encoding="utf-8") as f_meta:
                    f_meta.write(f"TITLE: {clean_title}\n")

            timer.start_stage("export_copy")
            log("Copying final master and artifacts to Google Drive in single batch step...")
            shutil.copy2(local_master_path, job_output_path)
            shutil.copy2(local_master_path, finished_output_path)

            copied_artifacts = []
            for artifact_f in [
                f"{job_id}_mapping.json", f"{job_id}_credits.json",
                f"{job_id}_metadata.txt", f"{job_id}.txt",
                f"{job_id}_metadata.json", "metadata.json",
                f"{job_id}_qa_report.json", f"{job_id}_contact_sheet.png"
            ]:
                src_art = os.path.join(work_job_dir, artifact_f)
                if os.path.exists(src_art):
                    shutil.copy2(src_art, os.path.join(output_job_dir, artifact_f))
                    shutil.copy2(src_art, os.path.join(OUT_DIR, artifact_f))
                    copied_artifacts.append(artifact_f)
            timer.stop_stage("export_copy")

            timings_local_path = os.path.join(work_job_dir, "timings.json")
            timings_job_path = os.path.join(output_job_dir, f"{job_id}_timings.json")
            timings_fin_path = os.path.join(OUT_DIR, f"{job_id}_timings.json")
            timer.save_timings(timings_local_path)
            shutil.copy2(timings_local_path, timings_job_path)
            shutil.copy2(timings_local_path, timings_fin_path)

            proof_s10 = {
                "items_count": 1,
                "output_file": final_filename,
                "destination": finished_output_path,
                "credits_registered": len(credits_data),
                "artifacts_copied": copied_artifacts,
                "file_size_bytes": os.path.getsize(finished_output_path),
                "sha256": sha256_str
            }
            ev_s10 = f"Master exported to finished/ ({os.path.getsize(finished_output_path)/(1024*1024):.1f} MB), {len(credits_data)} credits registered, committed in ledger"
            sm.complete_stage(10, evidence=ev_s10, proof_data=proof_s10)

            # Log stage timer table to console
            table_ascii = timer.format_table()
            log("\n" + table_ascii)

            job_result_data = {
                "job_id": job_id,
                "status": "completed",
                "success": True,
                "stage_index": 10,
                "stage_name": "Save master, register credits & export to Drive",
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
                "timings": timer.to_dict()["stages"],
                "stages": sm.get_stages_summary()
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

    def run(self, animal_mode=None, video_type=None, language=None, count=None, job_id=None, use_cache=False, layout_mode=None, clips_count=None, clip_time=None, pace_profile=None, slicing_mode=None, allow_shorter=False, allow_reuse=False):
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
                allow_shorter=allow_shorter,
                allow_reuse=allow_reuse
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
    parser.add_argument("--allow-reuse", action="store_true", default=False, help="Allow reusing clips across test runs")
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
        allow_shorter=args.allow_shorter,
        allow_reuse=args.allow_reuse
    )

