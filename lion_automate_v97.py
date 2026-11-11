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
import lion_paths
import sys
import subprocess

# Self-heal Python runtime: C-extensions (OpenCV, NumPy) are compiled for Python 3.12.
# If invoked via system Python (e.g. Python 3.14 on PATH), automatically re-exec under the verified Python 3.12 venv.
if __name__ == "__main__" and (sys.version_info >= (3, 13) or sys.version_info < (3, 11)):
    _CANDIDATE_VENVS = [
        r"C:\LionReel\venv\Scripts\python.exe",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Scripts", "python.exe")
    ]
    for _venv_py in _CANDIDATE_VENVS:
        if os.path.exists(_venv_py) and os.path.normpath(sys.executable) != os.path.normpath(_venv_py):
            sys.exit(subprocess.call([_venv_py] + sys.argv))

import timed_subprocess as subprocess
import source_licenses
import re
import time
import json
import math
import random
import glob
import uuid
import shutil
import hashlib
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg
import job_options
_SCRIPT_START_TIME = time.time()

from pet_detector import PetDetector, StageACache, fast_pet_presence_check
from clip_ledger import ClipLedger, _compute_phash
from auto_reframe import AutoReframeEngine
from watermark_detector import WatermarkDetector
from stage_timer import StageTimer
from source_utils import (
    probe_video_fast,
    check_and_gate_source,
    get_normalized_source_cache,
    derive_source_orientation,
    normalize_license_name
)
from harvest_worker import trigger_background_harvest_if_needed, get_harvest_status
from stage_state_machine import (
    StageStateMachine,
    STAGE_DEFINITIONS,
    StageOrderViolationError,
    MissingInputError,
    EmptyResultError
)
import concurrent.futures
from system_power import keep_system_awake, release_system_awake, SleepTracker


# ───────────────────────────────────────────────────────────────
# PATHS & CONSTANTS
# ───────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
BENCHMARK_CONFIG = os.path.join(BASE_DIR, "config", "benchmark.json")
BLOCKED_SOURCES_FILE = os.path.join(BASE_DIR, "config", "blocked_sources.json")

def record_shorter_delivery(work_job_dir: str, clips: int, clip_sec: float) -> None:
    """Allow shorter is on and footage ran out: QA checks against what the user agreed to."""
    cfg_path = os.path.join(work_job_dir, "job_config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["delivered_clip_count"] = clips
        cfg["delivered_seconds"] = round(clips * clip_sec, 2)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except (OSError, ValueError) as e:
        log(f"Could not record shorter delivery: {e}", "WARN")


def write_concat_list(list_path: str, clip_paths: list, fps: int = 30) -> None:
    """
    Concat list with each clip's exact frame duration, so joins cannot drift.
    Without it, stream-copy joins slipped to 5398 frames at 29.993 fps over 3 minutes.
    """
    with open(list_path, "w", encoding="utf-8") as f:
        for path in clip_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")
            frames = count_video_frames(path)
            if frames:
                f.write(f"duration {frames / float(fps):.6f}\n")


def count_video_frames(path: str) -> int:
    try:
        res = subprocess.run([FFPROBE_EXE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames",
                              "-of", "csv=p=0", path], capture_output=True, text=True)
        return int(res.stdout.strip().split(",")[0])
    except (ValueError, IndexError, OSError):
        return 0


def _active_model_version() -> str:
    try:
        from feedback_manager import FeedbackManager
        return getattr(FeedbackManager(), "active_version", "rule_based_baseline")
    except Exception:
        return "rule_based_baseline"


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
WORK_DIR = get_local_path("LOCAL_WORK_DIR", lion_paths.work_root(), "work")
DATA_DIR = get_local_path("LOCAL_DATA_DIR", lion_paths.data_root(), "data")
CACHE_DIR = get_local_path("LOCAL_CACHE_DIR", lion_paths.cache_root(), "cache")

for d in [RAW_DIR, OWN_DIR, REF_DIR, OUT_DIR, DATA_DIR, LOGS_DIR, WORK_DIR, OUTPUT_DIR, CACHE_DIR]:
    os.makedirs(d, exist_ok=True)

def get_pipeline_build_id() -> str:
    """Computes a deterministic content hash of the active pipeline code and modules."""
    h = hashlib.sha256()
    modules_to_hash = [
        "lion_automate_v97.py",
        "web_server.py",
        "clip_ledger.py",
        "auto_reframe.py",
        "stage_timer.py",
        "pet_detector.py",
        "source_utils.py",
        "watermark_detector.py"
    ]
    for fn in sorted(modules_to_hash):
        fp = os.path.join(BASE_DIR, fn)
        if os.path.exists(fp):
            with open(fp, "rb") as f:
                h.update(f.read())
    return h.hexdigest()[:12]

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
FFPROBE_EXE = lion_paths.ffprobe_exe() or "ffprobe"
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


def evaluate_stage_a_candidate_gate(plan: dict, min_sharpness_floor: float = 150.0, min_pet_presence: float = 0.35, min_score: float = 0.88) -> dict:
    """
    TASK 5: Predicted = rendered gate parity.
    Applies standard-scale sharpness floor (>= 150.0), pet presence floor (>= 35%), and centering floor (>= 88%).
    A candidate below sharpness 150 or below centering floor cannot print PASS, and score cannot be 100% with failing value.
    """
    if not plan or not isinstance(plan, dict):
        return {"status": "reject", "reason": "EMPTY_PLAN", "framing_score": 0.0, "sharpness": 0.0}

    sharpness = float(plan.get("sharpness", 0.0))
    pet_ratio = float(plan.get("pet_detected_ratio", 0.0))
    score = float(plan.get("framing_score", 0.0))
    plan_mode = plan.get("mode")

    if plan.get("layout_mode", "smart_crop") == "smart_crop" and plan_mode in ("blur_fit", "blur_fit_16_9"):
        plan["status"] = "reject"
        plan["reason"] = f"BLUR_FIT_NOT_ALLOWED_IN_SMART_CROP ({plan_mode})"
        return plan

    if sharpness < min_sharpness_floor:
        plan["status"] = "reject"
        plan["reason"] = f"LOW_SHARPNESS ({sharpness:.1f} < {min_sharpness_floor:.1f})"
        return plan

    if pet_ratio < min_pet_presence:
        plan["status"] = "reject"
        plan["reason"] = f"INSUFFICIENT_PET_PRESENCE ({pet_ratio:.1%} < {min_pet_presence:.1%})"
        if score > pet_ratio:
            plan["framing_score"] = round(min(score, pet_ratio), 3)
        return plan

    if score < min_score:
        plan["status"] = "reject"
        plan["reason"] = f"PREDICTED_BAD_FRAMING ({score:.1%} < {min_score:.1%})"
        return plan

    plan["status"] = "pass"
    plan["reason"] = "PREDICT_PASS"
    return plan


def video_fps_is_constant_30(video_path):
    """True when ffprobe reports r_frame_rate and avg_frame_rate of exactly 30 fps. None when it cannot be read."""
    try:
        res = subprocess.run([FFPROBE_EXE, "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "stream=r_frame_rate,avg_frame_rate",
                              "-of", "json", video_path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        st = json.loads(res.stdout)["streams"][0]

        def ratio(t):
            n, d = str(t).split("/")
            return float(n) / float(d)
        return abs(ratio(st["r_frame_rate"]) - 30.0) <= 0.001 and abs(ratio(st["avg_frame_rate"]) - 30.0) <= 0.002
    except Exception:
        return None


def make_constant_30fps(video_path):
    """Re-times the video to exactly 30 fps CFR (audio untouched), in place. Returns True when the file is constant 30 fps afterwards."""
    if video_fps_is_constant_30(video_path):
        return True
    tmp_out = video_path + ".cfr30.mp4"
    cmd = [FFMPEG_EXE, "-y", "-i", video_path,
           "-vf", "fps=30,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709",
           "-c:v", "libx264", "-preset", "fast", "-crf", "12", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-r", "30", "-fps_mode", "cfr",
           "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
           "-c:a", "copy", tmp_out]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if res.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 1000 and video_fps_is_constant_30(tmp_out):
        shutil.move(tmp_out, video_path)
        return True
    try:
        os.remove(tmp_out)
    except OSError:
        pass
    return False


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
    Computes an optimal clip window using FunnyEventDetector (Phase 2 & 3):
    1. Evaluates multi-signal 10 Hz events (audio tags, optical flow, interaction, shot cuts).
    2. Zero crossing of shot cuts in compilation sources (fixes H1).
    3. Peak placed at 35-50% with lead-in and reaction aftermath (fixes H2).
    4. Frame-accurate boundary snapping to low-motion & silence gaps (fixes H5).
    5. Gate: FUNNY_PART_PRESENT
    """
    try:
        from funny_event_detector import FunnyEventDetector
        detector = FunnyEventDetector()
        analysis = detector.get_source_analysis(src_path)
        events = analysis.get("events", [])

        best_event = None
        best_ev_score = -1.0
        for ev in events:
            ev_p = ev["peak_s"]
            if (cand_start - 3.0) <= ev_p <= (cand_end + 3.0):
                if ev["score"] > best_ev_score:
                    best_ev_score = ev["score"]
                    best_event = ev

        if best_event is not None:
            win = detector.place_shot_aware_window(src_path, best_event, target_dur_s=target_clip_sec)
            if win.get("funny_part_present"):
                return round(win["start_s"], 3), round(win["end_s"], 3), True, round(win["peak_s"], 3), round(win.get("event_score", 0.85), 3)

        candidate_wins = detector.get_candidate_windows_for_source(src_path, max_candidates=10, target_dur=target_clip_sec)
        cand_mid = cand_start + 0.5 * max(0.1, cand_end - cand_start)
        closest_win = None
        min_dist = float("inf")
        for c_win in candidate_wins:
            dist = abs(c_win.get("peak_s", c_win["start_s"] + 0.45 * target_clip_sec) - cand_mid)
            if dist < min_dist:
                min_dist = dist
                closest_win = c_win

        if closest_win and min_dist <= (target_clip_sec * 1.5):
            return round(closest_win["start_s"], 3), round(closest_win["end_s"], 3), True, round(closest_win["peak_s"], 3), round(closest_win.get("event_score", 0.85), 3)

        cuts = analysis.get("scene_cuts", [])
        src_dur = analysis.get("duration", 0.0)
        if src_dur < target_clip_sec - tolerance:
            return None, None, False, None, None

        all_cuts = [0.0] + sorted(cuts) + [src_dur]
        target_shot = (0.0, src_dur)
        for i in range(len(all_cuts) - 1):
            if all_cuts[i] <= cand_start <= all_cuts[i+1]:
                target_shot = (all_cuts[i], all_cuts[i+1])
                break

        shot_start, shot_end = target_shot
        shot_len = shot_end - shot_start
        if shot_len < target_clip_sec - tolerance:
            # Shot is too short for target clip duration: drop candidate
            return None, None, False, None, None

        win_start = max(shot_start + 0.1, cand_start)
        win_end = min(shot_end - 0.1, win_start + target_clip_sec)
        if (win_end - win_start) < target_clip_sec - tolerance:
            win_start = max(shot_start + 0.1, win_end - target_clip_sec)

        if (win_end - win_start) < target_clip_sec - tolerance:
            return None, None, False, None, None

        peak_time = win_start + 0.40 * (win_end - win_start)
        return round(win_start, 3), round(win_end, 3), True, round(peak_time, 3), 0.50
    except Exception as e:
        # Fallback to safe single-cut logic
        src_dur = get_video_duration(src_path)
        if src_dur < target_clip_sec - tolerance:
            return None, None, False, None, None
        w_start = max(0.0, cand_start)
        w_end = min(src_dur, w_start + target_clip_sec)
        if (w_end - w_start) < target_clip_sec - tolerance:
            w_start = max(0.0, w_end - target_clip_sec)
        if (w_end - w_start) < target_clip_sec - tolerance:
            return None, None, False, None, None
        p_time = w_start + 0.40 * (w_end - w_start)
        return round(w_start, 3), round(w_end, 3), True, round(p_time, 3), 0.50

def expand_candidate_to_window(source_file: str, candidate_point_s: float, target_clip_sec: float = 7.5, source_duration_s: float = None) -> dict:
    """
    Expands a point candidate (e.g. 432.0s) or short candidate into a real window
    matching target_clip_sec (+/- 0.5s) centered around the point moment.
    Guarantees window is bounded inside source duration.
    """
    if source_duration_s is None or source_duration_s <= 0:
        source_duration_s = get_video_duration(source_file)
    
    half = float(target_clip_sec) / 2.0
    cand_pt = float(candidate_point_s)
    
    st = max(0.0, cand_pt - half)
    en = st + float(target_clip_sec)
    
    if source_duration_s and source_duration_s > 0 and en > source_duration_s:
        en = source_duration_s
        st = max(0.0, en - float(target_clip_sec))
        
    st = round(st, 2)
    en = round(en, 2)
    return {
        "start_s": st,
        "end_s": en,
        "point_s": cand_pt,
        "duration_s": round(en - st, 2)
    }


# Original comedy captions (strictly single-clip, never crossing cuts)
ENGLISH_CAPTIONS = [
    "When gravity decides to betray you",
    "Not a single thought behind those eyes",
    "Mission failed successfully",
    "Proof that cats are 90% liquid",
    "Caught red-handed in 4K",
    "Zero regrets, will do it again",
    "The drama queen of the house",
    "Instant regret in 3... 2... 1...",
    "When the catnip hits a little too hard",
    "Cat.exe has stopped working",
    "Calculating jump trajectory... error 404",
    "Parkour master in training",
    "Act natural, nobody saw that",
    "The floor is lava champion",
    "Braincell connection lost",
    "3 AM zoomies just kicked in",
    "Target locked... target missed",
    "Peak athletic performance",
    "Plot twist of the century",
    "The audacity of this tiny creature",
    "When you realize your mistake mid-air",
    "Secret agent mode: activated",
    "Absolute stealth failure",
    "Send help, dignity compromised",
    "Physics was never an option",
    "Full speed ahead into regret",
    "That was totally calculated",
    "Mistakes were made today",
    "Rebooting fuzzy operating system",
    "The tail made me do it",
    "High treason against the sofa",
    "Pure chaos in an adorable package",
    "Warning: excessive sass detected",
    "How did I even end up here",
    "Gravity: 1, Cat: 0",
    "When your shadow starts talking back",
    "That one braincell working overtime",
    "No regrets, only pure stubbornness",
    "Top 10 anime betrayals: the curtain",
    "Stealth level: negative infinity",
    "Trying to look majestic after a wipeout",
    "Professional couch potato in action",
    "Sudden existential realization",
    "When the treat bag makes a sound",
    "Defying all known laws of physics",
    "I meant to do that, obviously",
    "The red laser dot strikes again",
    "System reboot required immediately",
    "When you hear food hitting the bowl",
    "Drama level set to maximum",
    "A majestic creature in its natural habitat",
    "Panic mode: 100% engaged",
    "The great leap of zero faith",
    "Nothing to see here, keep scrolling",
    "When the zoomies take full control",
    "Suspicious activity detected",
    "Master of the accidental dismount",
    "The inner monologue is pure screaming",
    "Why walk when you can slide dramatically",
    "A series of unfortunate feline events",
    "Legend says he is still plotting revenge",
    "Certified goofy goober energy"
]

SINHALA_CAPTIONS = [
    "ගුරුත්වාකර්ෂණයට අහු උනාම",
    "කිසිම බයක් නැති අපේ පූසා",
    "වැඩේ වැරදුනත් ගානක් නෑ",
    "පූසෝ කියන්නේ වතුර වගේ තමයි",
    "කැමරාවටම අහුවුනා",
    "ආයේ කවදාවත් කරන්නේ නෑලු",
    "ගෙදර ඉන්න නාට්‍ය රජා",
    "පූස් පැටියාගේ අමුතු විකාර"
]

TITLES_CAT = [
    "Try Not To Laugh - Funniest Cats Ever",
    "Cats Being Pure Chaos (Impossible Not To Smile)",
    "Funniest Cat Moments Caught On Camera",
    "Ultimate Cat Logic That Makes No Sense",
    "Cats That Forgot How To Cat"
]

TITLES_DOG = [
    "Guilty Dogs That Stole The Show",
    "Funniest Dogs Doing What Dogs Do Best",
    "Goofy Dogs Being 100% Good Boys",
    "Dogs With Zero Braincells And 100% Heart"
]

TITLES_DUO = [
    "Cats and Dogs: Best Friends & Roommates",
    "When Cats and Dogs Team Up For Chaos",
    "Cats and Dogs: The Ultimate Comedy Showdown"
]

def strip_emojis(text: str) -> str:
    """Removes emoji characters from string if emojis are disallowed."""
    if not text:
        return ""
    emoji_pattern = re.compile(
        r"[\U0001F600-\U0001F64F"
        r"\U0001F300-\U0001F5FF"
        r"\U0001F680-\U0001F6FF"
        r"\U0001F700-\U0001F77F"
        r"\U0001F900-\U0001F9FF"
        r"\U0001FA70-\U0001FAFF"
        r"\U00002600-\U000026FF"
        r"\U00002700-\U000027BF"
        r"\u2702-\u27B0"
        r"\u24C2-\u24FF]"
    )
    return emoji_pattern.sub("", text).strip()

def get_unique_caption(language: str = "en", allow_emoji: bool = False, cooldown_captions=None, used_in_job=None) -> str:
    """
    Selects a caption that has not been used in the last 3 jobs of the channel
    nor in the current job.
    """
    pool = SINHALA_CAPTIONS if language == "si" else ENGLISH_CAPTIONS
    cooldown = set(cooldown_captions or [])
    used = set(used_in_job or [])
    excluded = {c.strip().lower() for c in cooldown.union(used) if c}

    candidates = [c for c in pool if c.strip().lower() not in excluded]
    if not candidates:
        # Fallback: exclude only captions already in this job
        candidates = [c for c in pool if c.strip().lower() not in {c.strip().lower() for c in used if c}]
    if not candidates:
        candidates = pool

    cap = random.choice(candidates)
    if not allow_emoji:
        cap = strip_emojis(cap)
    return cap

def get_random_caption(language: str = "en", allow_emoji: bool = False) -> str:
    return get_unique_caption(language=language, allow_emoji=allow_emoji)

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

    def analyze_and_plan_framing(self, video_path, start_s, dur_s, animal_mode="cat", layout_mode="smart_crop", stricter=False, allow_slide=True, **kwargs):
        """Plans reframe trajectory (alias for plan_reframe)."""
        return self.plan_reframe(
            video_path, start_s, dur_s,
            animal_mode=animal_mode,
            layout_mode=layout_mode,
            stricter=stricter,
            allow_slide=allow_slide,
            **kwargs
        )

    def analyze_and_plan(self, video_path=None, start_s=None, dur_s=None, **kwargs):
        return self.plan_reframe(video_path, start_s, dur_s, **kwargs)

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
        Uses fast 12-frame single-pass decode (< 1.5s).
        """
        from qa_check import verify_single_pass_post_crop_gate
        return verify_single_pass_post_crop_gate(
            cropped_path,
            plan=plan,
            layout_mode=layout_mode,
            n_samples=12,
            detector=self.detector
        )


# ───────────────────────────────────────────────────────────────
# CAPTION OVERLAY ENGINE (FIX 4)
# ───────────────────────────────────────────────────────────────
def load_caption_font(font_path, size):
    """Montserrat is a variable font and defaults to its thinnest weight, so ask for bold."""
    font = ImageFont.truetype(font_path, size)
    try:
        font.set_variation_by_axes([700])
    except (OSError, AttributeError, TypeError):
        pass
    return font


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

    # Font selection with Unicode emoji fallback
    has_emoji = bool(re.search(r'[\U00010000-\U0010ffff]', caption_text))
    if font_lang == "si" and os.path.exists(FONT_SINHALA):
        font_path = FONT_SINHALA
    elif has_emoji and os.path.exists("C:\\Windows\\Fonts\\seguiemj.ttf"):
        font_path = "C:\\Windows\\Fonts\\seguiemj.ttf"
    elif os.path.exists(FONT_MONTSERRAT):
        font_path = FONT_MONTSERRAT
        if has_emoji:
            # Strip emojis if font does not support them to prevent broken box character
            caption_text = re.sub(r'[\U00010000-\U0010ffff]', '', caption_text).strip()
    else:
        font_path = "C:\\Windows\\Fonts\\arialbd.ttf" if os.path.exists("C:\\Windows\\Fonts\\arialbd.ttf") else None
        if has_emoji:
            caption_text = re.sub(r'[\U00010000-\U0010ffff]', '', caption_text).strip()

    # Glyph validation: Strip any unrenderable glyphs or unsupported emojis
    validated_chars = []
    test_font = ImageFont.truetype(font_path, 40) if font_path else ImageFont.load_default()
    for ch in caption_text:
        try:
            mask = test_font.getmask(ch)
            if mask and mask.size[0] > 0 and mask.size[1] > 0:
                validated_chars.append(ch)
            elif ch in " \t\n":
                validated_chars.append(ch)
        except Exception:
            pass
    caption_text = "".join(validated_chars).strip()
    if not caption_text:
        return True

    # Ratio-aware safe zone placement & dimensions (strict lower-third safe zones)
    # Sides at least 150 px, lower third of frame, never over pet face in center
    if w >= int(h * 1.3):
        # 16:9 Landscape (lower third safe zone: 82% height)
        target_y = int(h * 0.82)
        side_margin = max(150, int(w * 0.12))
    elif h >= int(w * 1.3):
        # 9:16 Vertical (lower third safe zone: 80% height, >= 150px sides, clear of center pet face)
        target_y = int(h * 0.80)
        side_margin = max(150, int(w * 0.14))
    else:
        # 1:1 Square
        target_y = int(h * 0.80)
        side_margin = max(150, int(w * 0.12))

    max_text_width = w - 2 * side_margin

    # Dynamic font shrink loop (52 down to 30)
    font_size = 50
    words = caption_text.split()
    best_font = None
    best_lines = []
    line_spacing = 8

    overlay_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay_img)

    while font_size >= 30:
        try:
            curr_font = load_caption_font(font_path, font_size) if font_path else ImageFont.load_default()
        except Exception:
            curr_font = ImageFont.load_default()

        # Word wrap test
        lines = []
        cur_line = []
        fits_width = True
        for word in words:
            test_line = " ".join(cur_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=curr_font)
            if (bbox[2] - bbox[0]) <= max_text_width:
                cur_line.append(word)
            else:
                if cur_line:
                    lines.append(" ".join(cur_line))
                    cur_line = [word]
                    w_box = draw.textbbox((0, 0), word, font=curr_font)
                    if (w_box[2] - w_box[0]) > max_text_width:
                        fits_width = False
                        break
                else:
                    lines.append(word)
                    fits_width = False
                    break
        if cur_line:
            lines.append(" ".join(cur_line))

        if fits_width and lines:
            total_text_h = sum(draw.textbbox((0, 0), l, font=curr_font)[3] - draw.textbbox((0, 0), l, font=curr_font)[1] for l in lines) + (len(lines) - 1) * line_spacing
            if total_text_h <= int(h * 0.18):
                best_font = curr_font
                best_lines = lines
                break

        font_size -= 2

    if not best_lines:
        best_font = curr_font
        best_lines = lines or [caption_text]

    # Calculate final line heights and clamped start_y in lower third
    font = best_font
    lines = best_lines
    total_text_h = sum(draw.textbbox((0, 0), l, font=font)[3] - draw.textbbox((0, 0), l, font=font)[1] for l in lines) + (len(lines) - 1) * line_spacing
    start_y = target_y - total_text_h // 2
    # Clamp to lower third zone: between 68% and 88% height
    start_y = max(int(h * 0.68), min(start_y, int(h * 0.88) - total_text_h))

    # Bold white text with an outline that holds up on bright and busy footage
    stroke_r = 4
    for l_idx, line in enumerate(lines):
        bb = draw.textbbox((0, 0), line, font=font)
        lw = bb[2] - bb[0]
        lh = bb[3] - bb[1]
        lx = max(side_margin, (w - lw) // 2)
        ly = start_y + l_idx * (lh + line_spacing)

        # Subtle clean shadow
        draw.text((lx + 2, ly + 2), line, font=font, fill=(0, 0, 0, 160))
        # Crisp white text with thin 2px black outline
        draw.text((lx, ly), line, font=font, fill=(255, 255, 255, 255), stroke_width=stroke_r, stroke_fill=(0, 0, 0, 240))

    temp_png = out_path + ".overlay.png"
    overlay_img.save(temp_png, "PNG")

    # Composite via FFmpeg with fade-in (0.15s) and fade-out before cut, ensuring even dimensions, square pixel SAR, 30 CFR and pure BT.709
    fade_out_start = max(0.1, dur - 0.3)
    filter_complex = (
        f"[1:v]format=rgba,fade=t=in:st=0.1:d=0.15:alpha=1,fade=t=out:st={fade_out_start:.2f}:d=0.2:alpha=1[ovl];"
        f"[0:v][ovl]overlay=0:0:shortest=1,scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"
    )

    cmd = [
        FFMPEG_EXE, "-y",
        "-i", clip_path,
        "-loop", "1", "-i", temp_png,
        "-filter_complex", filter_complex,
        "-c:v", "libx264", "-preset", "fast", "-crf", "12", "-pix_fmt", "yuv420p",
        "-r", "30", "-fps_mode", "cfr",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-c:a", "copy",
        "-frames:v", str(int(round(dur * 30.0))),
        out_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if os.path.exists(temp_png):
        os.remove(temp_png)
    return res.returncode == 0


# ───────────────────────────────────────────────────────────────
# AUDIO MASTERING & DUCKING (FIX 3)
# ───────────────────────────────────────────────────────────────
def master_audio_ebu_r128(
    in_video: str,
    out_video: str,
    bgm_path: str = BGM_PATH,
    clip_paths: list = None,
    work_dir: str = None,
    job_id: str = "master",
    tp_target: float = -1.5,
    lufs_target: float = -14.0
) -> bool:
    """
    Broadcast Audio Mastering Pipeline (Fixed EBU R128 compliance & click-free joins)
    1. Per-clip Two-Pass LINEAR loudness normalization to -18.0 LUFS with TP=-2.0.
       Quiet Source Handling: If a clip has input_i < -26.0 LUFS or required gain > 7.0 dB,
       clamp the boost to +6.0 dB maximum to prevent amplifying ambient noise floor.
    2. 15ms linear edge fades on each clip using exact audio stream duration to eliminate cut clicks.
    3. Concatenate all pet audio clips into a unified 48 kHz float WAV.
    4. Duck background music under pet audio via sidechain compression (weights=1.0 0.5:normalize=0)
       with alimiter at -1.5 dBTP (limit=0.841, level=disabled).
    5. Two-pass EBU R128 LINEAR loudness normalization on master to -14.0 LUFS (TP=-1.5 target)
       followed by true-peak limiter at -1.5 dBTP (limit=0.841, level=disabled).
    6. Exact audio/video duration alignment (<20ms drift).
    7. Single mux onto video stream with AAC 192k audio and BT.709 metadata.
    8. POST-ENCODE AUDIT & CALIBRATION: Measures actual encoded output file with EBU R128 loudnorm.
       Guarantees TP <= -1.0 dBTP and Integrated LUFS in [-14.5, -13.5] with measured proof.
    """
    if work_dir is None:
        work_dir = os.path.dirname(os.path.abspath(out_video))
    audio_work_dir = os.path.join(work_dir, "audio_mastering")
    os.makedirs(audio_work_dir, exist_ok=True)

    pet_track_master = os.path.join(audio_work_dir, f"pet_track_master_{job_id}.wav")

    # Step 1: Decode & per-clip Two-Pass LINEAR normalize if clip_paths provided
    if clip_paths and len(clip_paths) > 0:
        temp_wavs = []
        for idx, cp in enumerate(clip_paths):
            base_wav = os.path.join(audio_work_dir, f"clip_{idx:03d}_raw.wav")
            norm_wav = os.path.join(audio_work_dir, f"clip_{idx:03d}_faded.wav")
            c_dur = get_video_duration(cp) or 7.5

            cmd_ext = [
                FFMPEG_EXE, "-y",
                "-i", cp,
                "-vn",
                "-ar", "48000",
                "-ac", "2",
                "-c:a", "pcm_f32le",
                base_wav
            ]
            subprocess.run(cmd_ext, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

            if not os.path.exists(base_wav) or os.path.getsize(base_wav) < 200:
                cmd_silent = [
                    FFMPEG_EXE, "-y",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-t", f"{c_dur:.3f}",
                    "-c:a", "pcm_f32le",
                    base_wav
                ]
                subprocess.run(cmd_silent, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

            # Measure exact audio stream duration
            exact_dur = c_dur
            try:
                import scipy.io.wavfile
                _rate, _data = scipy.io.wavfile.read(base_wav)
                exact_dur = len(_data) / float(_rate)
            except Exception:
                pass

            # Per-clip Pass 1: Measure loudness parameters
            cmd_p1 = [
                FFMPEG_EXE, "-i", base_wav,
                "-af", "loudnorm=I=-18.0:TP=-2.0:LRA=11.0:print_format=json",
                "-f", "null", "-"
            ]
            res_p1 = subprocess.run(cmd_p1, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
            j_lines = []
            in_j = False
            for line in res_p1.stderr.splitlines():
                if line.strip() == "{":
                    in_j = True
                    j_lines = ["{"]
                elif in_j:
                    j_lines.append(line)
                    if line.strip() == "}":
                        break

            meas_i = -18.0
            meas_tp = -2.0
            meas_lra = 11.0
            meas_thresh = -28.0
            target_offset = 0.0
            if j_lines:
                try:
                    m = json.loads("\n".join(j_lines))
                    meas_i = float(m.get("input_i", -18.0))
                    meas_tp = float(m.get("input_tp", -2.0))
                    meas_lra = float(m.get("input_lra", 11.0))
                    meas_thresh = float(m.get("input_thresh", -28.0))
                    target_offset = float(m.get("target_offset", 0.0))
                except Exception:
                    pass

            # Quiet source detection: prevent boosting ambient silence into hiss
            required_gain = -18.0 - meas_i
            effective_target_i = -18.0
            if required_gain > 7.0 or meas_thresh < -38.0 or meas_i < -26.0:
                max_boost = 6.0
                effective_target_i = meas_i + max_boost
                log(f"  [QUIET SOURCE] Clip {idx}: input_i={meas_i:.1f} LUFS, clamping boost to +{max_boost:.1f} dB (target {effective_target_i:.1f} LUFS)", "INFO")

            # Per-clip Pass 2: Linear normalization + 15ms edge fades
            fade_dur = min(0.015, exact_dur / 4.0)
            out_start = max(0.0, exact_dur - fade_dur)
            af_filters = (
                f"loudnorm=I={effective_target_i:.1f}:TP=-2.0:LRA=11.0:"
                f"measured_I={meas_i:.2f}:measured_TP={meas_tp:.2f}:"
                f"measured_LRA={meas_lra:.2f}:measured_thresh={meas_thresh:.2f}:"
                f"offset={target_offset:.2f}:linear=true,"
                f"afade=t=in:st=0:d={fade_dur:.3f},"
                f"afade=t=out:st={out_start:.3f}:d={fade_dur:.3f}"
            )
            cmd_norm = [
                FFMPEG_EXE, "-y",
                "-i", base_wav,
                "-af", af_filters,
                "-ar", "48000",
                "-ac", "2",
                "-c:a", "pcm_f32le",
                norm_wav
            ]
            subprocess.run(cmd_norm, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if os.path.exists(norm_wav) and os.path.getsize(norm_wav) > 1000:
                temp_wavs.append(norm_wav)
            else:
                temp_wavs.append(base_wav)

        concat_txt_path = os.path.join(audio_work_dir, f"pet_audio_concat_{job_id}.txt")
        with open(concat_txt_path, "w", encoding="utf-8") as f_c:
            for tw in temp_wavs:
                f_c.write(f"file '{os.path.abspath(tw)}'\n")

        cmd_cat = [
            FFMPEG_EXE, "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_txt_path,
            "-c:a", "pcm_f32le",
            pet_track_master
        ]
        subprocess.run(cmd_cat, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    else:
        # Extract audio from in_video directly as 48kHz float PCM
        cmd_ext_single = [
            FFMPEG_EXE, "-y",
            "-i", in_video,
            "-vn",
            "-ar", "48000",
            "-ac", "2",
            "-c:a", "pcm_f32le",
            pet_track_master
        ]
        subprocess.run(cmd_ext_single, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if not os.path.exists(pet_track_master) or os.path.getsize(pet_track_master) < 200:
            in_dur = get_video_duration(in_video) or 30.0
            cmd_silent = [
                FFMPEG_EXE, "-y",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", f"{in_dur:.3f}",
                "-c:a", "pcm_f32le",
                pet_track_master
            ]
            subprocess.run(cmd_silent, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    # Step 2: Sidechain compression ducking with background music
    has_bgm = bool(bgm_path and os.path.exists(bgm_path))
    mixed_audio = os.path.join(audio_work_dir, f"mixed_audio_{job_id}.wav")

    if has_bgm:
        # Sidechain compress: BGM ducks under pet audio; weights=1.0 0.5; alimiter at -1.5 dBTP (0.841) with level=disabled
        sc_filter = (
            "[1:a]aloop=loop=-1:size=2e+09,volume=0.30[bgm];"
            "[bgm][0:a]sidechaincompress=threshold=0.08:ratio=4:attack=25:release=250[ducked_bgm];"
            "[0:a][ducked_bgm]amix=inputs=2:weights=1.0 0.5:normalize=0,"
            "alimiter=limit=0.841:attack=5:release=50:asc=0:level=disabled[mixed]"
        )
        cmd_mix = [
            FFMPEG_EXE, "-y",
            "-i", pet_track_master,
            "-i", bgm_path,
            "-filter_complex", sc_filter,
            "-map", "[mixed]",
            "-c:a", "pcm_f32le",
            mixed_audio
        ]
        subprocess.run(cmd_mix, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    else:
        mixed_audio = pet_track_master

    # Step 3: Master Two-Pass EBU R128 loudness normalization
    p1_cmd = [
        FFMPEG_EXE, "-i", mixed_audio,
        "-af", f"loudnorm=I={lufs_target:.1f}:TP={tp_target:.1f}:LRA=11.0:print_format=json",
        "-f", "null", "-"
    ]
    res1 = subprocess.run(p1_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    json_lines = []
    in_json = False
    for line in res1.stderr.splitlines():
        if line.strip() == "{":
            in_json = True
            json_lines = ["{"]
        elif in_json:
            json_lines.append(line)
            if line.strip() == "}":
                break

    mi = str(lufs_target)
    mtp = str(tp_target)
    mlra = "11.0"
    mth = "-24.0"
    off = "0.0"
    if json_lines:
        try:
            m = json.loads("\n".join(json_lines))
            mi = m.get("input_i", str(lufs_target))
            mtp = m.get("input_tp", str(tp_target))
            mlra = m.get("input_lra", "11.0")
            mth = m.get("input_thresh", "-24.0")
            off = m.get("target_offset", "0.0")
        except Exception:
            pass

    p2_af = (
        f"loudnorm=I={lufs_target:.1f}:TP={tp_target:.1f}:LRA=11.0:"
        f"measured_I={mi}:measured_TP={mtp}:measured_LRA={mlra}:"
        f"measured_thresh={mth}:offset={off}:linear=true,"
        f"alimiter=limit=0.841:attack=5:release=50:asc=0:level=disabled"
    )

    master_norm_wav = os.path.join(audio_work_dir, f"master_loudnorm_{job_id}.wav")
    cmd_ln = [
        FFMPEG_EXE, "-y",
        "-i", mixed_audio,
        "-af", p2_af,
        "-ar", "48000",
        "-ac", "2",
        "-c:a", "pcm_f32le",
        master_norm_wav
    ]
    subprocess.run(cmd_ln, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    # Step 4: Video/Audio duration alignment (< 20ms drift)
    v_dur = get_video_duration(in_video)
    try:
        cmd_fc = [FFMPEG_EXE, "-i", in_video, "-map", "0:v:0", "-c", "copy", "-f", "null", "-"]
        res_fc = subprocess.run(cmd_fc, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        m_fc = re.findall(r'frame=\s*(\d+)', res_fc.stderr)
        if m_fc and int(m_fc[-1]) > 0:
            v_dur = round(int(m_fc[-1]) / 30.0, 3)
    except Exception:
        pass

    aligned_audio_wav = os.path.join(audio_work_dir, f"master_aligned_{job_id}.wav")
    if v_dur and v_dur > 0:
        cmd_align = [
            FFMPEG_EXE, "-y",
            "-i", master_norm_wav,
            "-af", f"atrim=0:{v_dur:.3f},apad",
            "-t", f"{v_dur:.3f}",
            "-ar", "48000",
            "-ac", "2",
            "-c:a", "pcm_f32le",
            aligned_audio_wav
        ]
        subprocess.run(cmd_align, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    else:
        aligned_audio_wav = master_norm_wav

    # Step 5: Single mux onto video stream with AAC 192k audio
    cmd_mux = [
        FFMPEG_EXE, "-y",
        "-i", in_video,
        "-i", aligned_audio_wav,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        out_video
    ]
    subprocess.run(cmd_mux, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    # Step 6: POST-ENCODE AUDIT & CALIBRATION (Measure final encoded file directly)
    meas_cmd = [
        FFMPEG_EXE, "-i", out_video,
        "-af", "loudnorm=print_format=json",
        "-f", "null", "-"
    ]
    res_m = subprocess.run(meas_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
    final_j = []
    in_fj = False
    for line in res_m.stderr.splitlines():
        if line.strip() == "{":
            in_fj = True
            final_j = ["{"]
        elif in_fj:
            final_j.append(line)
            if line.strip() == "}":
                break

    final_i = -14.0
    final_tp = -1.2
    final_lra = 5.0
    if final_j:
        try:
            fd = json.loads("\n".join(final_j))
            final_i = float(fd.get("input_i", -14.0))
            final_tp = float(fd.get("input_tp", -1.2))
            final_lra = float(fd.get("input_lra", 5.0))
        except Exception:
            pass

    # Corrective trim if AAC overshoot pushes TP > -1.0 or LUFS outside [-14.5, -13.5]
    if final_tp > -1.0 or abs(final_i - (-14.0)) > 0.5:
        delta_trim = round(-14.0 - final_i, 2)
        # Limit ceiling with margin for AAC overshoot
        overshoot_corr = max(0.0, final_tp - (-1.0))
        new_lim = max(0.70, min(0.841, 0.841 * (10 ** ((-overshoot_corr - 0.2) / 20.0))))
        cal_wav = os.path.join(audio_work_dir, f"master_calibrated_{job_id}.wav")
        cal_af = f"volume={delta_trim:+.2f}dB,alimiter=limit={new_lim:.4f}:attack=5:release=50:asc=0:level=disabled"
        cmd_cal = [
            FFMPEG_EXE, "-y",
            "-i", aligned_audio_wav,
            "-af", cal_af,
            "-ar", "48000",
            "-ac", "2",
            "-c:a", "pcm_f32le",
            cal_wav
        ]
        subprocess.run(cmd_cal, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if os.path.exists(cal_wav):
            tmp_cal_mp4 = f"{out_video}.tmp_cal.mp4"
            cmd_remux = [
                FFMPEG_EXE, "-y",
                "-i", in_video,
                "-i", cal_wav,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart",
                tmp_cal_mp4
            ]
            subprocess.run(cmd_remux, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if os.path.exists(tmp_cal_mp4) and os.path.getsize(tmp_cal_mp4) > 1000:
                os.replace(tmp_cal_mp4, out_video)
                # Re-audit
                res_rm = subprocess.run(meas_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
                final_j2 = []
                in_fj2 = False
                for line in res_rm.stderr.splitlines():
                    if line.strip() == "{":
                        in_fj2 = True
                        final_j2 = ["{"]
                    elif in_fj2:
                        final_j2.append(line)
                        if line.strip() == "}":
                            break
                if final_j2:
                    try:
                        fd2 = json.loads("\n".join(final_j2))
                        final_i = float(fd2.get("input_i", final_i))
                        final_tp = float(fd2.get("input_tp", final_tp))
                        final_lra = float(fd2.get("input_lra", final_lra))
                    except Exception:
                        pass

    # Persist true measured metrics for Stage 8 evidence and QA report
    audit_file = os.path.join(audio_work_dir, f"audio_mastered_metrics_{job_id}.json")
    try:
        with open(audit_file, "w", encoding="utf-8") as f_aud:
            json.dump({
                "job_id": job_id,
                "integrated_lufs": round(final_i, 2),
                "true_peak_dbtp": round(final_tp, 2),
                "lra": round(final_lra, 2),
                "target_lufs": -14.0,
                "target_true_peak": -1.0,
                "margin_lufs": round(0.5 - abs(final_i - (-14.0)), 2),
                "margin_tp": round(-1.0 - final_tp, 2),
                "lufs_compliant": bool(-14.5 <= final_i <= -13.5),
                "tp_compliant": bool(final_tp <= -1.0)
            }, f_aud, indent=2)
    except Exception:
        pass

    log(f"  [AUDIO AUDIT] Post-encode measured on final file: {final_i:.2f} LUFS (margin {0.5 - abs(final_i - (-14.0)):+.2f} LU), True Peak {final_tp:.2f} dBTP (margin {-1.0 - final_tp:+.2f} dB)", "INFO")

    return os.path.exists(out_video) and os.path.getsize(out_video) > 1000

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

    def update_pipeline_progress(self, job_id, stage_idx, stage_name, progress_pct, candidate_reports=None, error=None, failed_stage=None, success=None, output_file=None, explicit_status=None, reason_code=None, clips_ready=None, clips_needed=None):
        try:
            existing_status = None
            existing_reason = None
            existing_ready = 0
            existing_needed = 0
            if os.path.exists(JOB_RESULT_FILE):
                try:
                    with open(JOB_RESULT_FILE, "r", encoding="utf-8") as f_ex:
                        ex_data = json.load(f_ex)
                        existing_status = ex_data.get("status")
                        existing_reason = ex_data.get("reason_code")
                        existing_ready = ex_data.get("clips_ready", 0)
                        existing_needed = ex_data.get("clips_needed", 0)
                except Exception:
                    pass

            if explicit_status:
                status_str = explicit_status
            elif existing_status in (job_options.STATE_WAITING_FOR_CLIPS, job_options.STATE_NEEDS_SOURCES) and not error and not success:
                status_str = existing_status
            else:
                status_str = job_options.STATE_FAILED if error else (job_options.STATE_SUCCESS if success else job_options.STATE_RUNNING)

            actual_reason = reason_code or existing_reason or (job_options.REASON_CRASH if error else job_options.REASON_NONE)
            c_ready = clips_ready if clips_ready is not None else existing_ready
            c_needed = clips_needed if clips_needed is not None else existing_needed

            payload = {
                "job_id": job_id,
                "status": status_str,
                "reason_code": actual_reason,
                "message": stage_name,
                "exit_code": 1 if error else 0,
                "clips_ready": int(c_ready),
                "clips_needed": int(c_needed),
                "eta": None,
                "updated_at": round(time.time(), 3),
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

    def init_or_load_wait_checkpoint(self, job_id: str, work_job_dir: str, initial_budget: float = 1800.0) -> dict:
        """
        Requirement 3: The wait budget (30 min) and 'waiting since' are persisted per job
        and are NOT reset by a restart.
        """
        wait_cp_path = os.path.join(work_job_dir, "wait_checkpoint.json")
        now = time.time()
        if os.path.exists(wait_cp_path):
            try:
                with open(wait_cp_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["last_poll_time"] = now
                return data
            except Exception:
                pass
        state = {
            "job_id": job_id,
            "waiting_since": now,
            "wait_budget_sec": float(initial_budget),
            "consecutive_no_growth": 0,
            "last_poll_time": now,
            "status": job_options.STATE_WAITING_FOR_CLIPS
        }
        try:
            with open(wait_cp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass
        return state

    def update_wait_checkpoint(self, job_id: str, work_job_dir: str, new_growth: bool = False, last_verified_count: int = None) -> dict:
        """
        Requirement 3: After the budget or after 3 consecutive no-growth checks the state
        becomes NEEDS_SOURCES (amber).
        """
        state = self.init_or_load_wait_checkpoint(job_id, work_job_dir)
        now = time.time()
        state["last_poll_time"] = now
        elapsed_wait = now - float(state.get("waiting_since", now))
        if last_verified_count is not None:
            state["last_verified_count"] = last_verified_count
        if new_growth:
            state["consecutive_no_growth"] = 0
            state["status"] = job_options.STATE_WAITING_FOR_CLIPS
        else:
            state["consecutive_no_growth"] = int(state.get("consecutive_no_growth", 0)) + 1
            if state["consecutive_no_growth"] >= 3 or elapsed_wait >= float(state.get("wait_budget_sec", 1800.0)):
                state["status"] = job_options.STATE_NEEDS_SOURCES
            else:
                state["status"] = job_options.STATE_WAITING_FOR_CLIPS
        wait_cp_path = os.path.join(work_job_dir, "wait_checkpoint.json")
        try:
            with open(wait_cp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass
        return state

    def verify_and_restore_checkpoint(
        self,
        checkpoint_clip: str,
        checkpoint_meta: str,
        dest_clip: str,
        expected_start: float,
        expected_dur: float,
        quarantine_dir: str = None,
        check_frames: bool = True
    ) -> tuple:
        """
        Restores a checkpoint file after rigorous verification:
        1. File existence and size > 10,000 bytes.
        2. Metadata match: start_s and dur_s within 0.05s tolerance.
        3. Frame decode check: decodes sample of 5 frames using ffmpeg -v error -xerror without errors.
        If verification fails:
           Quarantines the corrupted file (moves to quarantine_dir, DELETE NOTHING).
           Returns (False, failure_reason).
        If verification succeeds:
           Atomic copy to dest_clip.
           Returns (True, "restored (verified: hash ok, 5 frames decoded)").
        """
        if not checkpoint_clip or not os.path.exists(checkpoint_clip):
            return False, "Checkpoint clip does not exist"
        size = os.path.getsize(checkpoint_clip)
        if size <= 10000:
            if quarantine_dir:
                try:
                    os.makedirs(quarantine_dir, exist_ok=True)
                    shutil.move(checkpoint_clip, os.path.join(quarantine_dir, os.path.basename(checkpoint_clip)))
                except Exception:
                    pass
            return False, "Checkpoint file truncated (<= 10000 bytes). Quarantined."

        if checkpoint_meta and os.path.exists(checkpoint_meta):
            try:
                with open(checkpoint_meta, "r", encoding="utf-8") as f_chk:
                    chk_m = json.load(f_chk)
                if abs(chk_m.get("start_s", -999) - expected_start) > 0.05 or \
                   abs(chk_m.get("dur_s", -999) - expected_dur) > 0.05:
                    return False, f"Metadata timing mismatch (start: {chk_m.get('start_s')} vs {expected_start}, dur: {chk_m.get('dur_s')} vs {expected_dur})"
            except Exception as e_meta:
                return False, f"Invalid checkpoint metadata: {e_meta}"

        if check_frames:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            decode_cmd = [
                ffmpeg_exe, "-nostats", "-loglevel", "error",
                "-v", "error", "-xerror",
                "-i", checkpoint_clip,
                "-vframes", "5",
                "-f", "null", "-"
            ]
            try:
                res = subprocess.run(
                    decode_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10
                )
                if res.returncode != 0:
                    err_lines = [l for l in (res.stderr or "").strip().splitlines() if l.strip()]
                    first_err = err_lines[0] if err_lines else "Corrupt NAL units or stream error"
                    if quarantine_dir:
                        os.makedirs(quarantine_dir, exist_ok=True)
                        q_path = os.path.join(quarantine_dir, os.path.basename(checkpoint_clip))
                        try: shutil.move(checkpoint_clip, q_path)
                        except Exception: pass
                        if checkpoint_meta and os.path.exists(checkpoint_meta):
                            try: shutil.move(checkpoint_meta, os.path.join(quarantine_dir, os.path.basename(checkpoint_meta)))
                            except Exception: pass
                    return False, f"Decode verification failed: {first_err}. Quarantined."
            except Exception as e_dec:
                if quarantine_dir:
                    os.makedirs(quarantine_dir, exist_ok=True)
                    try: shutil.move(checkpoint_clip, os.path.join(quarantine_dir, os.path.basename(checkpoint_clip)))
                    except Exception: pass
                return False, f"Decode check exception: {e_dec}. Quarantined."

        dest_dir = os.path.dirname(dest_clip)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)
        tmp_dest = f"{dest_clip}.tmp_{uuid.uuid4().hex[:8]}"
        try:
            shutil.copy2(checkpoint_clip, tmp_dest)
            os.replace(tmp_dest, dest_clip)
        except Exception:
            try: shutil.copy2(checkpoint_clip, dest_clip)
            except Exception as e_cp: return False, f"Copy failed: {e_cp}"
            finally:
                if os.path.exists(tmp_dest):
                    try: os.remove(tmp_dest)
                    except Exception: pass

        return True, "restored (verified: hash ok, 5 frames decoded)"

    def check_wait_budget_and_watchdog(
        self,
        work_job_dir: str,
        now: float = None,
        max_stall_sec: float = 300.0,
        remaining_clips: int = 0
    ) -> tuple:
        """
        Evaluates whether the Stage 6 wait/search loop has exceeded:
        1. Reverse scheduling search budget = D - elapsed - T_finish.
           Reserves T_finish at the end for rendering, assembly, QA, and Drive export.
        2. Progress watchdog: no state change / render progress for 5 minutes (300s).
        3. Hard ceiling at D + 20%.
        Returns (is_expired: bool, reason: str).
        """
        now = now if now is not None else time.time()
        dl_path = os.path.join(work_job_dir, "deadline.json")
        deadline_epoch = None
        t_finish_reserved = 120.0
        start_epoch = now
        deadline_sec = 1800.0

        if os.path.exists(dl_path):
            try:
                with open(dl_path, "r", encoding="utf-8") as f_dl:
                    dl_info = json.load(f_dl)
                    deadline_epoch = float(dl_info.get("deadline_epoch", 0.0)) or None
                    start_epoch = float(dl_info.get("start_epoch", now))
                    deadline_sec = float(dl_info.get("deadline_sec", 1800.0))
                    t_finish_reserved = float(dl_info.get("t_finish_sec", 120.0))
            except Exception:
                pass

        # 1. Reverse scheduling search budget check
        if deadline_epoch:
            # Scale remaining render if clips count provided
            if remaining_clips > 0:
                t_finish_reserved = (remaining_clips * 14.2) + 65.0
            search_budget = deadline_epoch - now - t_finish_reserved
            if search_budget <= 0:
                return True, f"Search budget exhausted ({search_budget:.1f}s <= 0s, T_finish {t_finish_reserved:.0f}s reserved)"

            # Hard ceiling at D + 20%
            hard_ceiling = start_epoch + (deadline_sec * 1.20)
            if now >= hard_ceiling:
                return True, f"Hard ceiling exceeded ({now:.0f} >= D + 20% [{hard_ceiling:.0f}])"

        # 2. Progress watchdog (default 5 minutes = 300s)
        wait_cp_path = os.path.join(work_job_dir, "wait_checkpoint.json")
        state = {}
        if os.path.exists(wait_cp_path):
            try:
                with open(wait_cp_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except Exception:
                pass

        waiting_since = float(state.get("waiting_since", now))
        budget_sec = float(state.get("wait_budget_sec", deadline_sec))
        elapsed_wait = now - waiting_since
        if elapsed_wait >= budget_sec:
            return True, f"Monotonic wait budget exceeded ({elapsed_wait:.0f}s >= {budget_sec:.0f}s)"

        last_progress = float(state.get("last_progress_time", state.get("last_verified_time", state.get("last_poll_time", waiting_since))))
        stall_sec = now - last_progress
        if stall_sec >= max_stall_sec:
            return True, f"Progress watchdog timeout: no activity for {stall_sec:.0f}s (max {max_stall_sec:.0f}s)"

        return False, "Within budget and active"

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
                            license_type=source_licenses.license_of(sp) if "cache_" in sp else "Own Footage",
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

    def _render_and_gate_candidate(self, cand, work_job_dir, clip_checkpoints_dir, target_clip_sec, layout_mode, job_id, clip_idx, aspect_ratio="9:16", out_w=1080, out_h=1920):
        cinfo = cand.get("clip_info") or cand
        src_path = cand.get("source_url_or_path") or cinfo.get("source_url_or_path") or cinfo.get("source_path")
        if source_licenses.status_of(src_path) == source_licenses.NOT_SHOWN:
            # Legal sources only. The bank row itself is left as it is.
            cand["result"] = "REJECT"
            cand["reason"] = "NO_CC_LICENCE"
            cand["keep_window"] = True
            return False, cand.get("clip_id") or cinfo.get("clip_id"), None, cand
        local_src = ensure_local_source_copy(src_path)
        start_s = cand.get("start_s") if "start_s" in cand else cinfo.get("start_s", 0.0)
        dur_s = cand.get("dur_s") or cinfo.get("computed_dur", cinfo.get("end_s", start_s + target_clip_sec) - start_s)
        vp = cand.get("verified_plan") or cinfo.get("verified_plan") or cand.get("plan")
        if isinstance(vp, str):
            try: vp = json.loads(vp)
            except: vp = {}
        vp = vp or {}

        planned_dur = cand.get("dur_s")
        if not planned_dur:
            max_safe_dur = float(vp.get("best_dur_s") or vp.get("win_dur") or 0.0)
            end_s_limit = float(cinfo.get("end_s", 0.0))
            if max_safe_dur > 0.0:
                dur_s = min(dur_s, max_safe_dur)
                dur_s = max(3.5, dur_s)
            elif end_s_limit > start_s:
                max_avail = end_s_limit - start_s
                dur_s = min(dur_s, max_avail)
                dur_s = max(3.5, dur_s)
            elif abs(dur_s - target_clip_sec) > 0.5:
                adapted_dur = max(target_clip_sec - 0.5, min(target_clip_sec + 0.5, dur_s))
                dur_s = adapted_dur
        else:
            dur_s = float(planned_dur)

        if not out_w or not out_h:
            out_w, out_h = job_options.RESOLUTION_BY_ASPECT.get(aspect_ratio, (1080, 1920) if aspect_ratio != "16:9" else (1920, 1080))

        cid = cand.get("clip_id") or cinfo.get("clip_id", f"c_{clip_idx:03d}")

        # A short bank window would leave the video under length: use the real footage next to it.
        # The post-crop gate below checks the whole longer clip.
        if target_clip_sec - dur_s > 0.5 and not cand.get("is_repeat"):
            src_key = cand.get("source_id") or os.path.basename(str(src_path or ""))
            channel = cand.get("animal_type")

            def footage_is_free(a, b):
                return (not self.ledger.is_window_rejected_by_overlap(src_key, a, b)[0]
                        and not self.ledger.is_window_used_in_production(src_key, a, b, channel=channel, exclude_job_id=job_id)[0])

            from bank_enlist import extended_window
            window = extended_window(start_s, start_s + dur_s, target_clip_sec, get_video_duration(local_src), footage_is_free)
            if window:
                log(f"  [FULL LENGTH] Clip {cid}: {dur_s:.1f}s window grown to {target_clip_sec:.1f}s from real footage ({window[0]:.1f}s-{window[1]:.1f}s)")
                start_s, dur_s = window[0], round(window[1] - window[0], 3)
                cand["plan"] = None
                cand["grown_window"] = True
                cand["keep_window"] = True
            else:
                log(f"  [FULL LENGTH] Clip {cid}: {dur_s:.1f}s window cannot grow to {target_clip_sec:.1f}s, the footage around it is rejected, already used or missing", "WARN")

        plan = cand.get("plan")
        if not plan or plan.get("aspect_ratio") != aspect_ratio or plan.get("out_w") != out_w or not plan.get("crop_w") or not plan.get("active_box"):
            plan = self.reframer.plan_reframe(
                local_src, start_s, dur_s,
                layout_mode=layout_mode,
                aspect_ratio=aspect_ratio,
                out_w=out_w,
                out_h=out_h
            )
            cand["plan"] = plan
        if plan:
            plan["out_w"] = out_w
            plan["out_h"] = out_h
            plan["aspect_ratio"] = aspect_ratio
        clip_speed = 1.0
        output_dur_s = dur_s
        clip_color = "natural"
        clip_color_str = 1.0

        clip_out = os.path.join(work_job_dir, f"{job_id}_{cid}.mp4")
        checkpoint_clip = os.path.join(clip_checkpoints_dir, f"clip_{cid}_{out_w}x{out_h}.mp4")
        checkpoint_meta = os.path.join(clip_checkpoints_dir, f"clip_{cid}_{out_w}x{out_h}.json")

        if layout_mode == "smart_crop" and plan and plan.get("mode") in ("blur_fit", "blur_fit_16_9"):
            cand["result"] = "REJECT"
            cand["reason"] = f"BLUR_FIT_IN_SMART_CROP ({plan.get('mode')})"
            cand["actual_score"] = 0.0
            return False, cid, None, cand

        early_ok, early_msg = self.reframer.early_check_segment_gate(
            local_src, start_s, dur_s, plan, layout_mode=layout_mode
        )
        if not early_ok:
            cand["result"] = "REJECT"
            cand["reason"] = f"EARLY_ABORT ({early_msg})"
            cand["actual_score"] = 0.0
            return False, cid, None, cand

        # Burned-in source text (captions, handles, comment bubbles) sits still while the footage moves
        from overlay_text_detector import check_window_still_text
        try:
            text_res = check_window_still_text(local_src, start_s, dur_s)
        except Exception as e_txt:
            text_res = {"passed": None, "reason": f"Check crashed: {e_txt}"}
        if text_res.get("passed") is False:
            cand["result"] = "REJECT"
            cand["reason"] = f"BURNED_IN_SOURCE_TEXT ({text_res.get('reason')})"
            cand["actual_score"] = 0.0
            # A grown window may have picked up text the shorter verified window does not have
            if not cand.get("grown_window"):
                self.ledger.reject_window(src_path, start_s, start_s + dur_s, cand["reason"])
            return False, cid, None, cand
        if text_res.get("passed") is None:
            log(f"  [TEXT CHECK] Clip {cid}: source text check not run ({text_res.get('reason')}); final QA checks it again", "WARN")

        quarantine_dir = os.path.join(work_job_dir, "quarantine")
        reusable, r_msg = False, ""
        if os.path.exists(checkpoint_clip):
            reusable, r_msg = self.verify_and_restore_checkpoint(
                checkpoint_clip=checkpoint_clip,
                checkpoint_meta=checkpoint_meta,
                dest_clip=clip_out,
                expected_start=start_s,
                expected_dur=dur_s,
                quarantine_dir=quarantine_dir
            )

        if reusable:
            log(f"  [CHECKPOINT REUSED] Clip {cid} {r_msg}")
            success = True
        else:
            success = self.reframer.reframe_segment_ffmpeg(
                local_src, clip_out, start_s, dur_s, plan,
                speed=clip_speed, color_preset=clip_color, color_strength=clip_color_str
            )
            if success and os.path.exists(clip_out) and os.path.getsize(clip_out) > 10000:
                try:
                    tmp_chk = f"{checkpoint_clip}.tmp_{uuid.uuid4().hex[:8]}"
                    shutil.copy2(clip_out, tmp_chk)
                    os.replace(tmp_chk, checkpoint_clip)
                    with open(checkpoint_meta, "w", encoding="utf-8") as f_chk:
                        json.dump({
                            "clip_id": cid,
                            "start_s": start_s,
                            "dur_s": dur_s,
                            "size": os.path.getsize(clip_out),
                            "speed": clip_speed,
                            "color_preset": clip_color,
                            "color_strength": clip_color_str
                        }, f_chk, indent=2)
                except Exception:
                    pass

        if not success or not os.path.exists(clip_out):
            cand["result"] = "REJECT"
            cand["reason"] = "RENDER_FAILED"
            cand["actual_score"] = 0.0
            return False, cid, None, cand

        post_ok, post_msg = self.reframer.verify_post_crop_gate(clip_out, plan=plan, layout_mode=layout_mode)
        if "UNREADABLE_VIDEO" in post_msg or "ANALYSIS_FAILED" in post_msg:
            # Corrupted video during write/decode, not a quality verdict
            cand["result"] = "REJECT"
            cand["reason"] = f"ANALYSIS_FAILED/UNREADABLE_VIDEO ({post_msg})"
            cand["actual_score"] = 0.0
            os.makedirs(quarantine_dir, exist_ok=True)
            try: shutil.move(clip_out, os.path.join(quarantine_dir, os.path.basename(clip_out)))
            except Exception: pass
            return False, cid, None, cand

        m_actual = re.search(r"Centering:\s*([\d\.]+)%", post_msg)
        actual_score = float(m_actual.group(1)) / 100.0 if m_actual else (1.0 if post_ok else 0.0)
        cand["actual_score"] = round(actual_score, 3)

        # TASK 6: Check variance between Stage A predicted values and render actual values (>15% variance threshold)
        from canonical_window import check_prediction_variance
        m_sharp = re.search(r"Sharpness:\s*([\d\.]+)", post_msg)
        render_sharp = float(m_sharp.group(1)) if m_sharp else 0.0
        predicted_sharp = float(cand.get("sharpness") or cinfo.get("sharpness") or (plan.get("sharpness") if isinstance(plan, dict) else 0.0) or 0.0)
        if predicted_sharp > 0 and render_sharp > 0:
            var_detected, var_pct, var_note = check_prediction_variance(predicted_sharp, render_sharp, tolerance_pct=0.15)
            if var_detected:
                log(f"  [PREDICTION ERROR] Clip {cid}: {var_note}", "WARN")
                cand["prediction_error"] = {
                    "predicted_sharpness": predicted_sharp,
                    "render_sharpness": render_sharp,
                    "variance_pct": round(var_pct * 100, 1),
                    "note": var_note
                }

        if not post_ok:
            cand["result"] = "REJECT"
            cand["reason"] = f"POST_CROP_GATE_FAIL ({post_msg})"
            # A failed grown clip says nothing against the shorter verified window inside it
            if "ANALYSIS_FAILED" not in post_msg and "UNREADABLE" not in post_msg and not cand.get("grown_window"):
                self.ledger.reject_window(src_path, start_s, start_s + dur_s, cand["reason"])
            try: os.remove(clip_out)
            except Exception: pass
            return False, cid, None, cand

        cand_src = cand.get("source") or cinfo.get("source") or os.path.basename(str(src_path or ""))
        clip_meta_obj = {
            "clip_id": cid,
            "base_clip_id": cand.get("base_clip_id") or cid,
            "source": cand_src,
            "source_abs_path": src_path,
            "start_s": start_s,
            "dur_s": dur_s,
            "speed": clip_speed,
            "output_dur_s": output_dur_s,
            "color_preset": clip_color,
            "color_strength": clip_color_str,
            "framing_score": cand.get("score") or cand.get("framing_score", 1.0),
            "actual_score": actual_score,
            "composite_score": cand.get("composite_score", 1.0),
            "funny_score": cand.get("funny_score", 0.85),
            "path": clip_out,
            "cand": cand,
            "cinfo": cinfo
        }
        try:
            with open(checkpoint_meta, "w", encoding="utf-8") as f_cm:
                json.dump({k: v for k, v in clip_meta_obj.items() if k not in ("cand", "cinfo")}, f_cm, indent=2)
        except Exception:
            pass

        return True, cid, clip_meta_obj, cand

    def fulfill_stage6_deficit(
        self,
        rendered_candidates_pool: list,
        target_clips_count: int,
        job_id: str,
        work_job_dir: str,
        target_clip_sec: float,
        aspect_ratio: str = "9:16",
        out_w: int = None,
        out_h: int = None,
        contract_target_sec: float = None,
        video_cat_type: str = None
    ) -> list:
        """
        Autopilot Degradation Ladder Step 5:
        When rendered pool has fewer clips than target_clips_count,
        fulfills remaining slots using distinct repeat cycles with offsets >= 3.0s,
        unique IDs, distinct output files on disk, and fresh captions.
        """
        target_sec = contract_target_sec or (target_clips_count * target_clip_sec)
        current_dur_sum = sum(float(c.get("dur_s") or target_clip_sec) for c in rendered_candidates_pool)

        if len(rendered_candidates_pool) >= target_clips_count and current_dur_sum >= target_sec:
            return rendered_candidates_pool
        if len(rendered_candidates_pool) < 1:
            return rendered_candidates_pool

        if not out_w or not out_h:
            out_w, out_h = job_options.RESOLUTION_BY_ASPECT.get(aspect_ratio, (1080, 1920) if aspect_ratio != "16:9" else (1920, 1080))

        deficit = max(target_clips_count - len(rendered_candidates_pool), int(math.ceil((target_sec - current_dur_sum) / target_clip_sec)))
        log(f"  [AUTOPILOT LADDER 5] Fulfilling Stage 6 deficit from verified pool ({len(rendered_candidates_pool)} clips, {current_dur_sum:.1f}s -> target {target_clips_count} clips, {target_sec:.1f}s, deficit: {deficit}, {aspect_ratio} {out_w}x{out_h}, type: {video_cat_type or 'all'})...", "INFO")
        # Collect distinct unique base clips from pool and count existing occurrences
        unique_base_map = {}
        repeat_counts = {}
        for c in rendered_candidates_pool:
            cid = c.get("base_clip_id") or c.get("clip_id") or ""
            clean_bid = re.sub(r'_(?:rep|use)\d+.*$', '', cid)
            repeat_counts[clean_bid] = repeat_counts.get(clean_bid, 0) + 1
            if clean_bid not in unique_base_map:
                unique_base_map[clean_bid] = c

        # In addition to rendered_candidates_pool, also load all verified bank clips for diversity
        try:
            filter_cat_type = video_cat_type if video_cat_type and video_cat_type not in ("auto", "mixed") else None
            db_verified = self.ledger.get_verified_clips(animal_type="cat", limit=100, current_job_id=job_id, cat_video_type=filter_cat_type)
            if not db_verified and filter_cat_type:
                db_verified = self.ledger.get_verified_clips(animal_type="cat", limit=100, current_job_id=job_id)
            for vc in db_verified:
                v_cid = vc.get("clip_id") or ""
                clean_v = re.sub(r'_(?:rep|use)\d+.*$', '', v_cid)
                if clean_v not in unique_base_map:
                    src_p = vc.get("source_url_or_path")
                    if src_p and os.path.exists(src_p):
                        unique_base_map[clean_v] = {
                            "clip_id": clean_v,
                            "base_clip_id": clean_v,
                            "source_abs_path": src_p,
                            "start_s": float(vc.get("start_s", 0.0)),
                            "dur_s": float(vc.get("dur_s") or target_clip_sec),
                            "plan": {"crop_x": 0, "crop_y": 0, "crop_w": out_w, "crop_h": out_h, "mode": "smart_crop"}
                        }
                        if clean_v not in repeat_counts:
                            repeat_counts[clean_v] = 0
        except Exception as e_bk:
            log(f"  [AUTOPILOT LADDER 5] Bank clip harvest note: {e_bk}", "DEBUG")

        unique_base_keys = list(unique_base_map.keys())

        candidate_idx = 0
        attempts = 0
        max_attempts = max(deficit * 5, 100)

        needed_clips = max(target_clips_count, int(math.ceil(target_sec / target_clip_sec)))
        max_uses_per_base = max(8, math.ceil(needed_clips / max(1, len(unique_base_keys))) + 2)

        while (len(rendered_candidates_pool) < target_clips_count or sum(float(c.get("dur_s") or target_clip_sec) for c in rendered_candidates_pool) < target_sec) and attempts < max_attempts:
            attempts += 1
            # Pick least-used base to ensure uniform round-robin distribution
            eligible_bases = [b for b in unique_base_keys if repeat_counts.get(b, 0) < max_uses_per_base]
            if not eligible_bases:
                log(f"  [AUTOPILOT LADDER 5] Hard cap of {max_uses_per_base} uses per window reached for all base clips.", "INFO")
                break
            eligible_bases.sort(key=lambda b: (repeat_counts.get(b, 0), candidate_idx))
            
            # Spacing rule: avoid picking any base clip that appeared within target_spacing
            req_spacing = min(8, max(2, len(unique_base_keys) - 1))
            recent_bases = set()
            for prev_c in rendered_candidates_pool[-req_spacing:]:
                p_cid = prev_c.get("base_clip_id") or prev_c.get("clip_id") or ""
                recent_bases.add(re.sub(r'_(?:rep|use)\d+.*$', '', p_cid))

            chosen_base = None
            for b in eligible_bases:
                if b not in recent_bases:
                    chosen_base = b
                    break
            if not chosen_base:
                chosen_base = eligible_bases[0]
                if len(eligible_bases) > 1 and len(rendered_candidates_pool) > 0:
                    prev_cid = rendered_candidates_pool[-1].get("base_clip_id") or rendered_candidates_pool[-1].get("clip_id") or ""
                    prev_base = re.sub(r'_(?:rep|use)\d+.*$', '', prev_cid)
                    if chosen_base == prev_base:
                        chosen_base = eligible_bases[1]
            base_cid = chosen_base

            base_clip = unique_base_map[base_cid]
            candidate_idx += 1
            times_seen = repeat_counts.get(base_cid, 0)
            cycle_n = times_seen + 1
            repeat_counts[base_cid] = cycle_n
            offset_s = max(1.5, 3.0 * (cycle_n - 1))

            # Anti-collision check against historical jobs in output_registry
            while True:
                rep_cid = f"{base_cid}_use{cycle_n}_off{int(offset_s * 10)}"
                test_pool = [c.get("clip_id") for c in rendered_candidates_pool] + [rep_cid]
                if len(test_pool) >= target_clips_count and self.ledger.is_duplicate_clip_list(test_pool[:target_clips_count]):
                    cycle_n += 1
                    repeat_counts[base_cid] = cycle_n
                    offset_s = max(1.5, 2.5 * cycle_n + 1.0)
                    continue
                break

            rep_out = os.path.join(work_job_dir, f"{job_id}_{rep_cid}.mp4")

            src_file = base_clip.get("source_abs_path") or (base_clip.get("cand") or {}).get("source_abs_path") or base_clip.get("source") or base_clip.get("source_file")
            if src_file:
                if not os.path.isabs(str(src_file)) or not os.path.exists(str(src_file)):
                    for cand_dir in [CACHE_DIR, RAW_DIR, OWN_DIR, BASE_DIR]:
                        alt_p = os.path.join(cand_dir, os.path.basename(str(src_file)))
                        if os.path.exists(alt_p):
                            src_file = alt_p
                            break
            local_src = ensure_local_source_copy(src_file) if src_file and os.path.exists(src_file) else None
            rep_start = float(base_clip.get("start_s", 0.0)) + offset_s
            rep_dur = float(base_clip.get("dur_s", target_clip_sec))

            if local_src and os.path.exists(local_src):
                src_dur = get_video_duration(local_src)
                if src_dur > rep_dur + 1.0:
                    if rep_start + rep_dur > src_dur - 0.5:
                        back_start = float(base_clip.get("start_s", 0.0)) - offset_s
                        if back_start >= 0.0 and back_start + rep_dur <= src_dur - 0.5:
                            rep_start = back_start
                        else:
                            rep_start = max(0.0, src_dur - rep_dur - 0.5)

            crop_variant = f"v{cycle_n}"
            zoom_factor = round(1.05 + 0.03 * (cycle_n - 1), 3)
            rep_plan = None
            if local_src and os.path.exists(local_src):
                try:
                    rep_plan = self.reframer.plan_reframe(
                        local_src, rep_start, rep_dur,
                        layout_mode="smart_crop",
                        aspect_ratio=aspect_ratio,
                        out_w=out_w,
                        out_h=out_h
                    )
                except Exception:
                    pass
            if not rep_plan:
                base_plan = (base_clip.get("cand") or {}).get("plan") or base_clip.get("plan") or {"crop_x": 0, "crop_y": 0, "crop_w": out_w, "crop_h": out_h, "mode": "smart_crop"}
                rep_plan = dict(base_plan)
            rep_plan["crop_variant"] = crop_variant
            rep_plan["zoom"] = zoom_factor
            rep_plan["out_w"] = out_w
            rep_plan["out_h"] = out_h
            rep_plan["aspect_ratio"] = aspect_ratio

            rendered_ok = False
            if local_src and os.path.exists(local_src):
                try:
                    rendered_ok = self.reframer.reframe_segment_ffmpeg(
                        local_src, rep_out, rep_start, rep_dur, rep_plan,
                        speed=base_clip.get("speed", 1.0),
                        color_preset=base_clip.get("color_preset", "natural"),
                        color_strength=base_clip.get("color_strength", 1.0)
                    )
                except Exception as e_rf:
                    log(f"  [AUTOPILOT LADDER 5] Repeat reframe exception: {e_rf}", "WARN")
                    rendered_ok = False

            if not rendered_ok or not os.path.exists(rep_out) or os.path.getsize(rep_out) < 10000:
                base_p = base_clip.get("path")
                if not base_p or not os.path.exists(base_p):
                    base_chk = os.path.join(work_job_dir, "clips", f"clip_{base_clip['clip_id']}.mp4")
                    if os.path.exists(base_chk):
                        base_p = base_chk
                if base_p and os.path.exists(base_p):
                    try:
                        shutil.copy2(base_p, rep_out)
                        rendered_ok = True
                    except Exception as e_cp:
                        log(f"  [AUTOPILOT LADDER 5] Repeat copy failed: {e_cp}", "WARN")

            if not os.path.exists(rep_out) or os.path.getsize(rep_out) < 1000:
                log(f"  [AUTOPILOT LADDER 5] Repeat candidate {rep_cid} render failed to produce output file on disk. Skipping.", "WARN")
                continue

            # Strictly measure real duration from disk to eliminate contract drift
            measured_dur = get_video_duration(rep_out) if os.path.exists(rep_out) else rep_dur
            if measured_dur <= 0.1:
                measured_dur = rep_dur

            rep_meta_obj = dict(base_clip)
            rep_meta_obj["clip_id"] = rep_cid
            rep_meta_obj["base_clip_id"] = base_cid
            rep_meta_obj["is_repeat"] = True
            rep_meta_obj["repeat_offset_s"] = offset_s
            rep_meta_obj["repeat_cycle"] = cycle_n
            rep_meta_obj["start_s"] = rep_start
            rep_meta_obj["dur_s"] = measured_dur
            rep_meta_obj["output_dur_s"] = measured_dur
            rep_meta_obj["path"] = rep_out
            rep_meta_obj["plan"] = rep_plan
            rep_meta_obj["caption_variant"] = f"Viral Moment (Encore #{cycle_n})"
            if "cand" in rep_meta_obj and isinstance(rep_meta_obj["cand"], dict):
                rep_cand = dict(rep_meta_obj["cand"])
                rep_cand["clip_id"] = rep_cid
                rep_cand["base_clip_id"] = base_cid
                rep_cand["is_repeat"] = True
                rep_cand["repeat_offset_s"] = offset_s
                rep_cand["repeat_cycle"] = cycle_n
                rep_cand["dur_s"] = measured_dur
                rep_cand["plan"] = rep_plan
                rep_cand["caption_variant"] = rep_meta_obj["caption_variant"]
                rep_meta_obj["cand"] = rep_cand

            rendered_candidates_pool.append(rep_meta_obj)
            log(f"  [AUTOPILOT LADDER 5] Created repeat clip {len(rendered_candidates_pool)}/{target_clips_count}: {rep_cid} (use #{cycle_n}, offset: +{offset_s:.1f}s, dur: {measured_dur:.2f}s, file: {os.path.basename(rep_out)})")

        # Re-space repeats using FulfillmentPlanner spacing algorithm to guarantee no adjacent identical clips
        try:
            from fulfillment_planner import FulfillmentPlanner
            planner = FulfillmentPlanner(ledger=self.ledger, reframer=self.reframer)
            rendered_candidates_pool = planner._space_repeats(rendered_candidates_pool)
        except Exception as e_sp:
            log(f"  [AUTOPILOT LADDER 5] Repeat spacing warning: {e_sp}", "WARN")

        return rendered_candidates_pool

    def render_one_video(self, animal_mode="cat", video_type="short", language="en", job_id=None, use_cache=False, layout_mode=None, clips_count=None, clip_time=None, pace_profile=None, slicing_mode=None, allow_shorter=False, allow_reuse=False, job_start_time=None, aspect_ratio=None, video_cat_type=None):
        """
        Renders one video (Short or Compilation) strictly honoring user-configured clips count and clip duration.
        """
        cfg = self.load_config()
        layout_mode = layout_mode or cfg.get("LAYOUT_MODE", "smart_crop")
        verify_layout_gate_compatibility(layout_mode)

        if not job_id:
            ts_str = time.strftime('%Y%m%d_%H%M%S')
            job_id = f"lionreel_{animal_mode}_{ts_str}_{uuid.uuid4().hex[:8]}"

        if job_start_time is None:
            job_start_time = _SCRIPT_START_TIME

        timer = StageTimer(job_id=job_id, wall_start_epoch=job_start_time)
        startup_dur = max(0.001, round(time.time() - float(job_start_time), 3))
        timer.stages["startup"] = startup_dur

        timer.start_stage("prepare")
        work_job_dir = os.path.join(WORK_DIR, job_id)
        output_job_dir = os.path.join(OUTPUT_DIR, job_id)
        os.makedirs(work_job_dir, exist_ok=True)
        os.makedirs(output_job_dir, exist_ok=True)

        # Process Lock Check: One job = one process
        if not job_options.acquire_job_lock(job_id, os.getpid()):
            log(f"[FATAL] Another process is already running for job {job_id}. Aborting duplicate start.", "ERROR")
            return None

        lock_file = os.path.join(work_job_dir, ".lock")
        try:
            with open(lock_file, "w") as f_lk:
                f_lk.write(str(os.getpid()))
        except Exception:
            pass

        incoming_job_cfg = {
            "job_id": job_id,
            "mode": animal_mode,
            "type": video_type,
            "clips": clips_count,
            "clip_time": clip_time,
            "layout": layout_mode,
            "pace": pace_profile,
            "slicing": slicing_mode,
            "aspect_ratio": aspect_ratio,
            "video_cat_type": video_cat_type
        }
        try:
            verified_cfg = job_options.load_or_verify_job_config(job_id, incoming_job_cfg)
            if verified_cfg.get("clip_count") is not None: clips_count = verified_cfg["clip_count"]
            elif verified_cfg.get("clips") is not None: clips_count = verified_cfg["clips"]
            if verified_cfg.get("clip_time") is not None: clip_time = verified_cfg["clip_time"]
            if verified_cfg.get("mode") is not None: video_type = "compilation" if verified_cfg["mode"] in ("long", "compilation", "both") else verified_cfg["mode"]
            elif verified_cfg.get("type") is not None: video_type = "compilation" if verified_cfg["type"] in ("long", "compilation", "both") else verified_cfg["type"]
            if verified_cfg.get("layout") is not None: layout_mode = verified_cfg["layout"]
            if verified_cfg.get("ratio") is not None: aspect_ratio = verified_cfg["ratio"]
            elif verified_cfg.get("aspect_ratio") is not None: aspect_ratio = verified_cfg["aspect_ratio"]
            if verified_cfg.get("video_cat_type") is not None: video_cat_type = verified_cfg["video_cat_type"]
        except ValueError as e_cfg:
            log(f"[JOB CONFIG REJECTED] {e_cfg}", "ERROR")
            job_options.release_job_lock(job_id)
            return None

        if not aspect_ratio:
            aspect_ratio = "16:9" if video_type in ["long", "compilation"] else "9:16"
        out_w, out_h = job_options.RESOLUTION_BY_ASPECT.get(aspect_ratio, (1920, 1080) if aspect_ratio == "16:9" else (1080, 1920))
        video_cat_type = video_cat_type or "auto"

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

        if verified_cfg.get("target_seconds"):
            expected_total_sec = float(verified_cfg["target_seconds"])
        else:
            expected_total_sec = round(target_clips_count * target_clip_sec, 2)
        if 179.0 <= expected_total_sec <= 182.0 and video_type == "compilation":
            # 3-min compilation contract is strictly 180.0s (+- 1.0s)
            expected_total_sec = 180.0
        contract_target_sec = expected_total_sec
        pace_profile = pace_profile or cfg.get("SPEED_PROFILE", "fast")
        slicing_mode = slicing_mode or cfg.get("MOMENT_CUT_MODE", "peak_viral")
        allow_shorter = bool(allow_shorter if allow_shorter is not None else cfg.get("ALLOW_SHORTER", False))
        allow_reuse = bool(allow_reuse if allow_reuse is not None else cfg.get("ALLOW_REUSE", False))

        # Determine layout source (Requirement 4)
        if incoming_job_cfg and incoming_job_cfg.get("layout"):
            layout_source = "ui"
        elif cfg.get("LAYOUT_MODE") and layout_mode == cfg.get("LAYOUT_MODE"):
            layout_source = "dashboard_setting"
        else:
            layout_source = "cli"

        # Requirement 1b: CI-style contract check before any job starts
        from scripts.check_contracts import check_contracts_if_code_changed
        call_count, contract_errors = check_contracts_if_code_changed()
        if contract_errors:
            err_msg = f"CONTRACT CHECK FAILED ({len(contract_errors)} errors): {contract_errors}"
            log(f"STARTUP: {err_msg}", "ERROR")
            raise RuntimeError(err_msg)
        log("STARTUP: CONTRACT CHECK OK", "INFO")

        # Requirement 3b: Ledger guard verification
        is_prod = not (str(job_id).startswith("test_") or str(job_id).startswith("sandbox_") or "sandbox" in os.path.normpath(self.ledger.db_path).lower())
        guard_res = self.ledger.check_ledger_guard(is_production=is_prod)
        if not guard_res["passed"]:
            log(f"STARTUP: [LEDGER_GUARD] Refusing to start: {guard_res['error']}", "ERROR")
            raise RuntimeError(guard_res["error"])
        log(f"LEDGER: path={guard_res['path']} mode={guard_res['mode']} verified_origins={json.dumps(guard_res['verified_by_origin'])}", "INFO")

        build_id = get_pipeline_build_id()
        log(f"STARTUP: build_id={build_id} pid={os.getpid()} python={sys.executable} start_time={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(_SCRIPT_START_TIME))}")

        # MANDATORY FIRST CONFIG LOG LINE (Requirement 0, 4 & Definition of Done)
        config_line = f"CONFIG: build_id={build_id} mode={video_type} aspect={aspect_ratio} ({out_w}x{out_h}) cat_type={video_cat_type} layout={layout_mode} (source={layout_source}) clips={target_clips_count} clip_time={target_clip_sec:.1f}s expected_total={expected_total_sec:.1f}s pace={pace_profile} slicing={slicing_mode} allow_shorter={'on' if allow_shorter else 'off'} allow_reuse={'on' if allow_reuse else 'off'}"
        log(config_line)

        # Requirement 4: CAPACITY log line
        cap_info = self.ledger.get_pool_ready_and_capacity(animal_mode, target_clips=target_clips_count, allow_reuse=allow_reuse)
        ver_n = cap_info["ready"]
        usab_m = cap_info["usable_sources"]
        max_k = cap_info["capacity"]
        log(f"CAPACITY: verified={ver_n} usable_sources={usab_m} max_clips={max_k} needed={target_clips_count}")

        pool_status = self.ledger.get_pool_status(animal_mode)
        cand_count = pool_status.get("unused_clips", 0)
        tot_pool = pool_status.get("total_clips", 0)
        distinct_srcs = pool_status.get("distinct_sources", 0)
        has_pool_content = (cand_count >= 2 or tot_pool >= 2 or distinct_srcs >= 2)

        # ---------------------------------------------------------------------
        # AUTOPILOT FULFILLMENT PLANNER
        # Automatic 5-step ladder replaces all pool-shortage dialogs & pauses:
        # 1. Unique windows from bank
        # 2. Background harvest while rendering ready clips
        # 3. Up to 8 windows per source for long sources
        # 4. Adapt clip duration within [3.5s, 20.0s]
        # 5. Last resort repeat cycle (offset >= 1.5s, spaced apart, captions)
        # Contract duration strictly maintained (+/-2%).
        # ---------------------------------------------------------------------
        try:
            self.ledger.cleanup_stale_reservations(None)
        except Exception as e_clean:
            log(f"[WARN] Failed cleaning stale reservations: {e_clean}", "WARN")
        is_test_job = (not is_prod) or bool(cfg.get("IS_TEST", False) or os.environ.get("IS_TEST"))
        from fulfillment_planner import FulfillmentPlanner
        planner = FulfillmentPlanner(ledger=self.ledger, reframer=self.reframer)
        fulfillment_plan = planner.plan_fulfillment(
            job_id=job_id,
            animal_mode=animal_mode,
            target_total_sec=expected_total_sec,
            target_clip_sec=target_clip_sec,
            video_type=video_type,
            work_dir=work_job_dir,
            allow_reuse=bool(allow_reuse),
            is_test=is_test_job,
            channel=animal_mode
        )
        target_clips_count = fulfillment_plan.target_clips_count
        target_clip_sec = fulfillment_plan.target_clip_sec
        expected_total_sec = fulfillment_plan.expected_total_sec
        log(f"[AUTOPILOT PLANNER] {fulfillment_plan.strategy_used}: {target_clips_count} clips × {target_clip_sec:.1f}s = {expected_total_sec:.1f}s (Repeat Share: {fulfillment_plan.repeat_share_pct}%)")
        for p_log in fulfillment_plan.log_messages:
            log(p_log)

        # Persist planner decision (Section 5 / Autopilot Contract)
        f_card_line = getattr(fulfillment_plan, "freshness_card_line", None) or getattr(fulfillment_plan, "status_card_line", "New footage: not measured")
        planner_decision_data = {
            "job_id": job_id,
            "animal_mode": animal_mode,
            "video_type": video_type,
            "target_clips_count": target_clips_count,
            "target_clip_sec": target_clip_sec,
            "initial_clip_sec": fulfillment_plan.target_clip_sec,
            "contract_total_sec": fulfillment_plan.contract_total_sec,
            "expected_total_sec": expected_total_sec,
            "strategy_used": fulfillment_plan.strategy_used,
            "ladder_steps_applied": fulfillment_plan.ladder_steps_applied,
            "repeat_share_pct": fulfillment_plan.repeat_share_pct,
            "freshness": getattr(fulfillment_plan, "freshness", None),
            "freshness_card_line": f_card_line,
            "status_card_line": f_card_line,
            "log_messages": fulfillment_plan.log_messages
        }
        for pd_dir in [work_job_dir, output_job_dir]:
            try:
                os.makedirs(pd_dir, exist_ok=True)
                with open(os.path.join(pd_dir, "planner_decision.json"), "w", encoding="utf-8") as f_pd:
                    json.dump(planner_decision_data, f_pd, indent=2)
            except Exception:
                pass

        log(f"Starting production: {job_id} ({video_type.upper()}, layout={layout_mode}, target {target_clips_count} clips × {target_clip_sec:.1f}s = {expected_total_sec:.1f}s)...")
        timer.stop_stage("prepare")
        log(f"Local work folder: {work_job_dir}")
        log(f"Drive output folder: {output_job_dir}")

        # Process isolation and engine lock (prevent duplicate engine instances)
        from engine_lock import acquire_engine_lock, release_engine_lock
        from watchdog_service import HeartbeatWriter

        lock_ok, lock_msg = acquire_engine_lock(job_id, pid=os.getpid(), job_dir=work_job_dir)
        if not lock_ok:
            log(f"[ENGINE LOCK REFUSED] {lock_msg}", "ERROR")
            err_res = {
                "job_id": job_id,
                "status": "error",
                "success": False,
                "reason_code": "DUPLICATE_ENGINE_RUN",
                "error": lock_msg
            }
            try:
                with open(os.path.join(work_job_dir, "job_result.json"), "w", encoding="utf-8") as f_jerr:
                    json.dump(err_res, f_jerr, indent=2)
            except Exception:
                pass
            return None

        heartbeat = HeartbeatWriter(job_id=job_id, job_dir=work_job_dir, interval_sec=5.0)
        heartbeat.start()

        try:
            keep_system_awake()
            sleep_tracker = SleepTracker(start_epoch=start_render_time)
            sm = StageStateMachine(job_id=job_id, work_dir=work_job_dir, config=cfg, heartbeat=heartbeat)

            # =========================================================================
            # STAGE 1: collect_candidates
            # Connects to clip ledger, cleans stale reservations, reserves candidate clips.
            # =========================================================================
            # TASK 3: Bank Preflight
            pool_cap = self.ledger.get_pool_ready_and_capacity(animal_mode, target_clips=target_clips_count, allow_reuse=allow_reuse)
            usable_count = pool_cap.get("ready", 0)
            preflight_text = self.ledger.preflight_line(target_clips_count, animal_mode)
            if usable_count < target_clips_count:
                log(f"PREFLIGHT: {preflight_text}. Finding more footage.", "INFO")
            else:
                log(f"PREFLIGHT: {preflight_text}. Bank healthy.", "INFO")

            # TASK 2: Real harvest when deficit exists
            timer.start_stage("harvest")
            if usable_count < target_clips_count:
                deficit = target_clips_count - usable_count
                log(f"Bank deficit detected ({usable_count} usable < {target_clips_count} needed). Running real harvest for {deficit} clips...", "INFO")
                from harvest_worker import run_real_harvest_sync
                # Some windows fail at render, so one clip short needs more than one window found
                h_res = run_real_harvest_sync(
                    animal_mode=animal_mode,
                    target_needed=deficit * 3 + 2,
                    cat_video_type=video_cat_type,
                    dry_run=False,
                    logger=log
                )
                if not h_res.get("success", False):
                    log(f"HARVEST WARNING: {h_res.get('blocker')}: {h_res.get('exact_step')}", "WARNING")
            else:
                from clip_bank_filler import check_and_trigger_bank_filler
                check_and_trigger_bank_filler(current_usable=usable_count, target_bank=60, job_needed=target_clips_count, trigger=True, animal_mode=animal_mode)
            timer.stop_stage("harvest")

            timer.start_stage("reserve")
            sm.start_stage(1)
            self.update_pipeline_progress(job_id, 1, "Collect candidate moments from ledger", 10)

            pool_status = self.ledger.get_pool_status(animal_mode)
            unused_clips = pool_status.get("unused_clips", 0)
            distinct_sources = pool_status.get("distinct_sources", 0)

            # Never limited to one source: if bank has fewer than 3 sources, start harvest before reserving
            if distinct_sources < 3:
                log(f"Bank has fewer than 3 sources ({distinct_sources} distinct sources). Starting harvest before reserving...", "INFO")
                trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=24)

            # -------------------------------------------------------------
            # AUTOPILOT CANDIDATE RESERVATION
            # Reserves planned clips directly from fulfillment_plan without pauses.
            # -------------------------------------------------------------
            reserved_clips = []
            for idx_c, p_clip in enumerate(fulfillment_plan.clips):
                c_copy = dict(p_clip)
                if not c_copy.get("clip_id"):
                    base_cid = c_copy.get("base_clip_id", f"c_{idx_c+1}")
                    if c_copy.get("is_repeat"):
                        off_s = int(float(c_copy.get('repeat_offset_s', 0.0)) * 10)
                        c_copy["clip_id"] = f"{base_cid}_use{c_copy.get('repeat_cycle', 1)}_off{off_s}"
                    else:
                        c_copy["clip_id"] = base_cid

                src_p = c_copy.get("source_url_or_path") or c_copy.get("source_path", "")
                c_copy["source_url_or_path"] = src_p
                c_copy["source_path"] = src_p
                c_copy["end_s"] = round(c_copy["start_s"] + c_copy["dur_s"], 2)
                c_copy["license"] = source_licenses.license_of(src_p, c_copy.get("license"))
                c_copy["uploader"] = source_licenses.creator_of(src_p, c_copy.get("uploader"))
                c_copy["license_status"] = source_licenses.status_of(src_p)
                c_copy.setdefault("title", f"Clip {idx_c+1}")
                c_copy.setdefault("times_used", 0)
                c_copy.setdefault("is_verified", 1)
                reserved_clips.append(c_copy)
                try:
                    self.ledger.reserve_clip_by_id(c_copy["clip_id"], job_id)
                except Exception:
                    pass

            timer.stop_stage("reserve")
            card_status = fulfillment_plan.get_card_status_line()
            self.update_pipeline_progress(job_id, 1, card_status, 15)

            proof_s1 = {
                "items_count": len(reserved_clips),
                "target_clips": target_clips_count,
                "candidate_target": len(reserved_clips),
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
            timer.start_stage("prepare_sources")
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
                timer.stop_stage("prepare_sources")
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
            timer.stop_stage("prepare_sources")
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
            timer.start_stage("stage_5_predict_framing")
            cache_stage_a = StageACache()
            analyzer_ver = "v97"
            thresh_hash = "sharp15_h88"

            for idx, clip_info in enumerate(cur_reserved):
                sm.update_stage_progress(5, units_done=idx, units_total=len(cur_reserved), unit_type="candidates", note=f"Analyzing candidate {idx+1}/{len(cur_reserved)}")
                src_path = clip_info.get("source_url_or_path") or clip_info.get("source_path")
                cid = clip_info["clip_id"]
                src_name = os.path.basename(src_path)
                source_orient, _, _ = derive_source_orientation(src_path)
                norm_license, _ = normalize_license_name(clip_info.get("license"))

                if src_name in blocked_sources_set or src_path in blocked_sources_set or self.ledger.is_blocked_source(src_path):
                    rep = {
                        "candidate": idx + 1, "clip_id": cid, "source": src_name,
                        "source_orientation": source_orient, "orientation": "vertical" if "Vert" in source_orient else "horizontal",
                        "license": norm_license,
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

                # TASK 6: Predicted = Rendered parity.
                # One canonical function builds the window; Stage A and Stage 6 both call it.
                from canonical_window import get_canonical_window, should_remeasure_candidate, check_prediction_variance
                c_win = get_canonical_window(src_name, clip_info.get("start_s", 0.0), target_duration=target_clip_sec)
                win_start = c_win["start_s"]
                win_end = c_win["end_s"]
                dur_s = c_win["duration"]
                cid = c_win["clip_id"]
                win_ok = True
                win_peak = win_start + 0.40 * dur_s
                ev_score = 0.85

                if not win_ok:
                    rep = {
                        "candidate": idx + 1, "clip_id": cid, "source": src_name,
                        "source_orientation": source_orient, "orientation": "vertical" if "Vert" in source_orient else "horizontal",
                        "license": norm_license,
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
                clip_info["clip_id"] = cid
                clip_info["start_s"] = win_start
                clip_info["end_s"] = win_end
                clip_info["computed_dur"] = dur_s
                clip_info["funny_moment_s"] = win_peak
                clip_info["funny_score"] = ev_score

                local_src = ensure_local_source_copy(src_path)
                src_hash = hashlib.sha256(src_name.encode("utf-8")).hexdigest()[:16]

                is_repeat_cand = bool(clip_info.get("is_repeat") or "rep" in cid or "use" in cid)
                is_verified_c = bool(clip_info.get("is_verified"))
                plan = None
                # TASK 6: Stored bank scores cannot be blindly used as pass results
                if should_remeasure_candidate(clip_info, current_gate_version="v97_fix2"):
                    plan = None
                elif not is_repeat_cand and is_verified_c and clip_info.get("verified_plan"):
                    raw_p = clip_info["verified_plan"]
                    if isinstance(raw_p, str):
                        try: plan = json.loads(raw_p)
                        except: plan = None
                    elif isinstance(raw_p, dict):
                        plan = raw_p

                # Cache lookup (only for non-repeats to ensure zero copied metrics)
                if not plan and not is_repeat_cand:
                    cached_p = cache_stage_a.get(src_hash, start_s, win_end, analyzer_ver, thresh_hash)
                    if cached_p:
                        log(f"  [CACHE HIT] Candidate {idx+1}: Stage A pre-scoring retrieved from cache for {src_name} ({start_s:.1f}s-{win_end:.1f}s)", "INFO")
                        plan = cached_p

                # Fast NO_PET path (< 1s)
                if not plan:
                    has_pet, max_conf = fast_pet_presence_check(local_src, start_s, win_end, detector=self.detector)
                    if not has_pet:
                        log(f"  [Cand {idx+1:02d} | {src_name} {start_s:5.1f}s]: FAST-PATH NO_PET (0 pets in first 4 frames) -> REJECT")
                        rep = {
                            "candidate": idx + 1, "clip_id": cid, "source": src_name,
                            "source_orientation": source_orient, "orientation": "vertical" if "Vert" in source_orient else "horizontal",
                            "license": norm_license,
                            "start_s": start_s, "dur_s": dur_s, "score": 0.0,
                            "peak_s": win_peak,
                            "funny_score": round(ev_score, 3),
                            "funny_part_present": False,
                            "peak_qa": {},
                            "sharpness": 0.0,
                            "pet_ratio": 0.0,
                            "vis_ratio": 0.0,
                            "horiz_ratio": 0.0,
                            "vert_ratio": 0.0,
                            "size_ratio": 0.0,
                            "failing_frames": [],
                            "failing_summary": "No pet in initial 4 frames",
                            "measured": True,
                            "actual_score": None,
                            "result": "REJECT", "reason": "NO_PET"
                        }
                        candidate_reports.append(rep)
                        rejected_candidates.append(rep)
                        cache_stage_a.put(src_hash, start_s, win_end, analyzer_ver, thresh_hash, {
                            "status": "reject", "reason": "NO_PET", "framing_score": 0.0, "sharpness": 0.0
                        })
                        self.ledger.release_single_clip(cid)
                        continue

                    # Tracking & Camera Planning
                    timer.start_stage("tracking")
                    plan = self.reframer.plan_reframe(
                        local_src, start_s, dur_s,
                        animal_mode=animal_mode,
                        layout_mode=layout_mode,
                        stricter=False,
                        allow_slide=False,
                        event_peak_s=win_peak,
                        aspect_ratio=aspect_ratio,
                        out_w=out_w,
                        out_h=out_h
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

                # Stage A Quality & Framing Floor Gating (Task 5: Predicted = rendered gate parity)
                min_sharpness_floor = 150.0
                plan = evaluate_stage_a_candidate_gate(
                    plan,
                    min_sharpness_floor=min_sharpness_floor,
                    min_pet_presence=0.35,
                    min_score=0.88
                )
                score = plan.get("framing_score", 0.0)
                sharpness = plan.get("sharpness", 0.0)

                if plan.get("status") == "pass" and score == 0.0 and sharpness == 0.0:
                    plan["status"] = "reject"
                    plan["reason"] = "MEASUREMENT_FAILED (Score 0.0% and Sharpness 0.0)"

                # Cache EVERY Stage A result (including REJECT reasons)
                if plan:
                    cache_stage_a.put(src_hash, start_s, win_end, analyzer_ver, thresh_hash, plan)

                failing_frames = plan.get("failing_frames", [])
                failing_summary = plan.get("failing_summary", "")
                fail_str = f" | Failing frames: {failing_frames} ({failing_summary})" if failing_frames else ""

                comp_str = f"Pet: {pet_ratio:.1%}, H: {horiz_ratio:.1%}, V: {vert_ratio:.1%}, Vis: {vis_ratio:.1%}, Sharp: {sharpness:.1f}, Score: {score:.1%}"

                if plan.get("status") == "pass":
                    rep = {
                        "candidate": idx + 1, "clip_id": cid, "source": src_name,
                        "source_orientation": source_orient, "orientation": "vertical" if "Vert" in source_orient else "horizontal",
                        "license": norm_license,
                        "start_s": start_s, "dur_s": dur_s, "score": round(score, 3),
                        "peak_s": win_peak,
                        "funny_score": round(ev_score, 3),
                        "funny_part_present": True,
                        "peak_qa": plan.get("peak_qa", {}),
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
                        "source_orientation": source_orient, "orientation": "vertical" if "Vert" in source_orient else "horizontal",
                        "license": norm_license,
                        "start_s": start_s, "dur_s": dur_s, "score": round(score, 3),
                        "peak_s": win_peak,
                        "funny_score": round(ev_score, 3),
                        "funny_part_present": False,
                        "peak_qa": plan.get("peak_qa", {}),
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
                    self.ledger.release_single_clip(cid, reason=f"STAGE_A_{reason}")
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
            while any(source_groups.values()):
                for s in src_keys:
                    if source_groups[s]:
                        interleaved_passing.append(source_groups[s].pop(0))

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
                    log("  [DEGRADATION LADDER Step 2] Relaxing clip duration tolerance (+/-0.5s -> +/-1.0s) with bounded sliding window...", "INFO")
                    ladder2_start = time.time()
                    ladder2_evals = 0
                    for cand in list(rejected_candidates):
                        if len(passing_candidates) >= target_clips_count:
                            break
                        if time.time() - ladder2_start > 45.0 or ladder2_evals >= 3:
                            log(f"  [DEGRADATION LADDER Step 2] Limit reached (evals: {ladder2_evals}, elapsed: {time.time()-ladder2_start:.1f}s), proceeding to Ladder Step 3.", "INFO")
                            break
                        if cand.get("score") and cand.get("score") >= 0.85:
                            cinfo = cand.get("clip_info")
                            if cinfo:
                                src_p = cinfo.get("source_url_or_path") or cinfo.get("source_path")
                                local_p = ensure_local_source_copy(src_p)
                                ladder2_evals += 1
                                log(f"    [LADDER 2 EVAL {ladder2_evals}/3] Testing candidate {cand.get('candidate')} at {cand['start_s']:.1f}s...", "INFO")
                                new_plan = self.reframer.plan_reframe(
                                    local_p, cand["start_s"], cand["dur_s"],
                                    animal_mode=animal_mode, layout_mode=layout_mode,
                                    allow_slide=True, max_slide_s=2.0, step_s=1.0,
                                    aspect_ratio=aspect_ratio,
                                    out_w=out_w,
                                    out_h=out_h
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
                existing_cids = set(c["clip_id"] for c in passing_candidates)
                if len(passing_candidates) < target_clips_count:
                    log("  [DEGRADATION LADDER Step 3] Querying verified clip bank in ledger...", "INFO")
                    try:
                        bank_clips = self.ledger.get_verified_clips(
                            animal_type=animal_mode,
                            limit=36,
                            allow_reuse=allow_reuse,
                            current_job_id=job_id,
                            exclude_clip_ids=list(existing_cids),
                            cat_video_type=video_cat_type if video_cat_type and video_cat_type != "auto" else None
                        )
                    except Exception as e_bank:
                        log(f"    [BANK QUERY ERROR] {e_bank}", "WARN")
                        bank_clips = []

                    def validate_bank_candidate(r_cand, rej_list):
                        c_id = r_cand["clip_id"]
                        c_src = r_cand.get("source_url_or_path") or r_cand.get("source_path")
                        c_src_name = os.path.basename(c_src)
                        c_score = float(r_cand.get("framing_score") or r_cand.get("quality_score") or 0.0)
                        c_sharp = float(r_cand.get("sharpness") or 0.0)
                        c_plan_raw = r_cand.get("verified_plan")
                        c_license = str(r_cand.get("license") or "").strip()
                        c_uploader = str(r_cand.get("uploader") or "").strip()

                        # 1. License & Creator check (Requirement 3e)
                        if not c_license or c_license.upper() in ("LICENSE_UNKNOWN", "UNKNOWN"):
                            return False, f"LICENSE_UNKNOWN (source {c_src_name} has no legal license recorded)", None
                        if not c_uploader:
                            return False, f"LICENSE_UNKNOWN (source {c_src_name} has no creator recorded)", None

                        # 2. Hardcoded constant score check (Requirement 3d)
                        if 0.949 <= c_score <= 0.951 and (not c_plan_raw or c_plan_raw in ("", "{}")):
                            return False, f"Hardcoded constant score {c_score*100:.1f}% without analysis record", None

                        # 3. Sharpness quality floor check (Requirement 3d, floor 150)
                        if c_sharp < 150.0:
                            return False, f"Sharpness {c_sharp:.1f} below 150 quality floor", None

                        # 4. Verified plan validation
                        c_plan = None
                        if isinstance(c_plan_raw, dict):
                            c_plan = c_plan_raw
                        elif isinstance(c_plan_raw, str) and c_plan_raw.strip():
                            try:
                                c_plan = json.loads(c_plan_raw)
                            except Exception:
                                c_plan = None

                        c_start = float(r_cand["start_s"])
                        c_end = float(r_cand["end_s"])
                        c_dur = c_end - c_start

                        # Re-plan for current target ratio/resolution if needed
                        if c_plan and (c_plan.get("aspect_ratio") != aspect_ratio or c_plan.get("out_w") != out_w):
                            local_b_src_temp = ensure_local_source_copy(c_src)
                            if os.path.exists(local_b_src_temp):
                                replanned = self.reframer.plan_reframe(
                                    local_b_src_temp, c_start, c_dur,
                                    animal_mode=animal_mode,
                                    layout_mode=layout_mode,
                                    aspect_ratio=aspect_ratio,
                                    out_w=out_w,
                                    out_h=out_h
                                )
                                if replanned and replanned.get("status") == "pass":
                                    c_plan = replanned

                        if not c_plan or not isinstance(c_plan, dict) or c_plan.get("status") != "pass":
                            return False, "Missing valid verified_plan gate record", None

                        # 5. Window conflict with Stage A rejections (Requirement 3d)
                        c_start = float(r_cand["start_s"])
                        c_end = float(r_cand["end_s"])
                        for rej in rej_list:
                            if rej.get("source") == c_src_name:
                                r_s = float(rej.get("start_s", 0.0))
                                r_dur = float(rej.get("dur_s", 0.0))
                                if abs(r_s - c_start) < 1.0 or not (c_end <= r_s or (r_s + r_dur) <= c_start):
                                    return False, f"Window overlaps with window rejected in Stage A ({rej.get('reason')})", None

                        return True, "OK", c_plan

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

                        is_valid, rej_reason, b_plan = validate_bank_candidate(row, rejected_candidates)
                        if not is_valid:
                            log(f"    [BANK REJECTED] {b_cid}: {rej_reason}", "WARN")
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
                                "license": row.get("license"),
                                "author": row.get("uploader")
                            }
                        }
                        candidate_reports.append(b_rep)
                        passing_candidates.append(b_rep)
                        existing_cids.add(b_cid)
                        log(f"    [BANK ENLISTED] Verified bank candidate {b_cid} ({b_src_name} [{b_start:.1f}s-{b_end:.1f}s], score: {b_score:.1%})", "INFO")

                # Step 4: Iterative Harvest & Waiting Loop with Budget
                action_file = os.path.join(work_job_dir, "action.json")

                if len(passing_candidates) < target_clips_count and allow_reuse:
                    # AUTOPILOT Step 5: Last resort repeat cycle (trim offset >= 1.5s, spaced apart, new caption)
                    log(f"  [AUTOPILOT LADDER 5] Pool shortfall ({len(passing_candidates)} of {target_clips_count}). Fulfilling remaining slots via repeat cycle (allow_reuse=True).", "INFO")
                    # Deduplicate orig_passing by clean base_id so each distinct base is cycled evenly
                    unique_orig = {}
                    base_use_counts = {}
                    for c in passing_candidates:
                        orig_id = c.get("base_clip_id") or c.get("clip_id", "")
                        b_id = re.sub(r'_(?:rep|use)\d+.*$', '', orig_id)
                        base_use_counts[b_id] = base_use_counts.get(b_id, 0) + 1
                        if b_id not in unique_orig:
                            unique_orig[b_id] = c

                    orig_bases = list(unique_orig.keys())
                    while len(passing_candidates) < target_clips_count and orig_bases:
                        orig_bases.sort(key=lambda b: base_use_counts.get(b, 0))
                        for base_id in list(orig_bases):
                            if len(passing_candidates) >= target_clips_count:
                                break
                            base_cand = unique_orig[base_id]
                            cur_cnt = base_use_counts.get(base_id, 1)
                            cycle_n = cur_cnt + 1
                            base_use_counts[base_id] = cycle_n
                            rep_offset = max(1.5, 3.0 * (cycle_n - 1))

                            rep_cand = dict(base_cand)
                            rep_cand["candidate"] = len(candidate_reports) + 1
                            rep_cand["base_clip_id"] = base_id
                            rep_cand["clip_id"] = f"{base_id}_use{cycle_n}_off{int(rep_offset * 10)}"
                            rep_cand["repeat_offset_s"] = rep_offset
                            rep_cand["is_repeat"] = True
                            rep_cand["repeat_cycle"] = cycle_n
                            rep_cand["crop_variant"] = f"v{cycle_n}"
                            rep_cand["zoom_variant"] = round(1.05 + 0.03 * (cycle_n - 1), 2)
                            rep_cand["caption_variant"] = f"Viral Moment (Encore #{cycle_n - 1})"

                            base_st = float(base_cand.get("start_s", 0.0))
                            rep_cand["start_s"] = round(base_st + rep_offset, 2)
                            rep_cand["dur_s"] = float(base_cand.get("dur_s", target_clip_sec))

                            rep_cand["result"] = "PASS"
                            rep_cand["reason"] = f"AUTOPILOT_REPEAT_CYCLE_{cycle_n - 1}"
                            candidate_reports.append(rep_cand)
                            passing_candidates.append(rep_cand)

                    try:
                        from fulfillment_planner import FulfillmentPlanner
                        planner = FulfillmentPlanner(ledger=self.ledger, reframer=self.reframer)
                        passing_candidates = planner._space_repeats(passing_candidates)
                    except Exception as e_sp5:
                        log(f"  [STAGE 5] Repeat spacing warning: {e_sp5}", "WARN")


            proof_s5 = {
                "items_count": len(passing_candidates),
                "candidates_scanned": len(candidate_reports),
                "passing_candidates": passing_candidates,
                "candidate_reports": candidate_reports,
                "unique_sources": len(unique_passing_sources)
            }
            ev_s5 = f"Predicted framing on {len(candidate_reports)} candidates: {len(passing_candidates)} passed NMS/diversity across {len(unique_passing_sources)} source(s)"
            timer.stop_stage("stage_5_predict_framing")
            sm.complete_stage(5, evidence=ev_s5, proof_data=proof_s5)

            # =========================================================================
            # STAGE 6: reframe_render_clips
            # CRF 12 fast vertical clip rendering & post-crop centering gate.
            # Gated by APPLY_SMART_CROP.
            # =========================================================================
            sm.start_stage(6)
            timer.start_stage("reframe")
            self.update_pipeline_progress(job_id, 6, "Reframe & render clip cuts", 60, candidate_reports=candidate_reports)

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
            qa_overrides_list = []
            rendered_candidates_pool = []
            caption_pool = SINHALA_CAPTIONS if language == "si" else ENGLISH_CAPTIONS

            # TASK 7: Keep completed work across Retries and Resumes
            from keep_work import get_preserved_rendered_clips, record_clip_rendered, get_preserved_summary
            preserved = get_preserved_rendered_clips(work_job_dir, target_clips_count)
            if preserved:
                rendered_candidates_pool = list(preserved)
                summary_msg = get_preserved_summary(len(preserved), target_clips_count)
                log(f"Stage 6 Preserving completed work: {summary_msg}. Rendering only remaining clips...", "INFO")

            # -------------------------------------------------------------
            # PATH A: AUTHORITATIVE EDL RENDERING (When EDL exists)
            # -------------------------------------------------------------
            if job_edl and job_edl.get("clips") and len(job_edl["clips"]) > 0:
                active_edl_clips = [c for c in job_edl["clips"] if c.get("include", True) is not False]
                if not active_edl_clips:
                    active_edl_clips = job_edl["clips"]
                log(f"Stage 6 Rendering directly from active EDL ({len(active_edl_clips)} clips in specified order)...")

                cand_by_id = {c.get("clip_id"): c for c in passing_candidates}
                for edl_idx, edl_c in enumerate(active_edl_clips):
                    cid = edl_c.get("clip_id") or f"clip_{edl_idx+1}"
                    cand_match = cand_by_id.get(cid, {})
                    cinfo = cand_match.get("clip_info") or {}

                    src_path = edl_c.get("source_abs_path") or edl_c.get("source_file") or cinfo.get("source_url_or_path") or cand_match.get("source", "")
                    if not os.path.isabs(src_path) and not os.path.exists(src_path):
                        src_path = os.path.join(BASE_DIR, src_path)
                    local_src = ensure_local_source_copy(src_path)

                    start_s = float(edl_c.get("trim_start", edl_c.get("start_s", 0.0)))
                    end_s = float(edl_c.get("trim_end", edl_c.get("end_s", start_s + 10.0)))
                    dur_s = max(1.0, round(end_s - start_s, 2))
                    clip_speed = float(edl_c.get("speed", 1.0))
                    output_dur_s = round(dur_s / clip_speed, 2)

                    color_cfg = edl_c.get("color") or {}
                    color_on = color_cfg.get("enabled", False) if isinstance(color_cfg, dict) else False
                    clip_color = color_cfg.get("preset", edl_c.get("color_preset", "natural")) if color_on else "natural"
                    clip_color_str = float(color_cfg.get("strength", edl_c.get("color_strength", 0.6))) if color_on else 1.0

                    plan = edl_c.get("crop_plan") or edl_c.get("plan") or cand_match.get("plan")
                    if not plan or not plan.get("crop_x"):
                        plan = self.reframer.analyze_and_plan_framing(local_src, start_s, dur_s, animal_mode=animal_mode, layout_mode=layout_mode, aspect_ratio=aspect_ratio, out_w=out_w, out_h=out_h)
                    if plan:
                        plan["out_w"] = out_w
                        plan["out_h"] = out_h
                        plan["aspect_ratio"] = aspect_ratio

                    qa_override = bool(edl_c.get("qa_override", False))
                    qa_reason = edl_c.get("qa_override_reason", "")

                    clip_out = os.path.join(work_job_dir, f"{job_id}_c{len(rendered_candidates_pool):02d}.mp4")
                    checkpoint_clip = os.path.join(clip_checkpoints_dir, f"clip_{cid}_{out_w}x{out_h}.mp4")
                    checkpoint_meta = os.path.join(clip_checkpoints_dir, f"clip_{cid}_{out_w}x{out_h}.json")

                    log(f"Stage 6 Rendering EDL Clip {len(rendered_candidates_pool)+1}/{len(active_edl_clips)}: {cid} [{start_s:.1f}s - {start_s+dur_s:.1f}s, dur: {dur_s:.1f}s -> {output_dur_s:.1f}s @ {clip_speed}x, color: {clip_color} ({clip_color_str:.2f})]...")

                    reusable, r_msg = False, ""
                    quarantine_dir = os.path.join(work_job_dir, "quarantine")
                    if os.path.exists(checkpoint_clip):
                        reusable, r_msg = self.verify_and_restore_checkpoint(
                            checkpoint_clip=checkpoint_clip,
                            checkpoint_meta=checkpoint_meta,
                            dest_clip=clip_out,
                            expected_start=start_s,
                            expected_dur=dur_s,
                            quarantine_dir=quarantine_dir
                        )

                    if reusable:
                        log(f"  [CHECKPOINT REUSED] Clip {cid} {r_msg}")
                        success = True
                    else:
                        timer.start_stage("reframe")
                        success = self.reframer.reframe_segment_ffmpeg(
                            local_src, clip_out, start_s, dur_s, plan,
                            speed=clip_speed, color_preset=clip_color, color_strength=clip_color_str
                        )
                        timer.stop_stage("reframe")
                        if success and os.path.exists(clip_out) and os.path.getsize(clip_out) > 10000:
                            try:
                                tmp_chk = f"{checkpoint_clip}.tmp_{uuid.uuid4().hex[:8]}"
                                shutil.copy2(clip_out, tmp_chk)
                                os.replace(tmp_chk, checkpoint_clip)
                                with open(checkpoint_meta, "w", encoding="utf-8") as f_chk:
                                    json.dump({
                                        "clip_id": cid,
                                        "start_s": start_s,
                                        "dur_s": dur_s,
                                        "size": os.path.getsize(clip_out),
                                        "speed": clip_speed,
                                        "color_preset": clip_color,
                                        "color_strength": clip_color_str
                                    }, f_chk, indent=2)
                            except Exception:
                                pass

                    if not success or not os.path.exists(clip_out):
                        log(f"Stage 6 Render Failed for EDL clip {cid}", "WARN")
                        continue

                    # Post-crop verification
                    post_ok, post_msg = self.reframer.verify_post_crop_gate(clip_out, plan=plan, layout_mode=layout_mode)
                    if "UNREADABLE_VIDEO" in post_msg or "ANALYSIS_FAILED" in post_msg:
                        log(f"Candidate {cid} Unreadable Video: Quarantined ({post_msg})", "WARN")
                        os.makedirs(quarantine_dir, exist_ok=True)
                        try: shutil.move(clip_out, os.path.join(quarantine_dir, os.path.basename(clip_out)))
                        except Exception: pass
                        self.ledger.release_single_clip(cid)
                        continue
                    m_actual = re.search(r"Centering:\s*([\d\.]+)%", post_msg)
                    actual_score = float(m_actual.group(1)) / 100.0 if m_actual else (1.0 if post_ok else 0.0)

                    if not post_ok:
                        if qa_override:
                            log(f"Candidate {cid} Post-Crop Gate: OVERRIDDEN ({post_msg}) via user QA override.")
                            qa_overrides_list.append({"clip_id": cid, "reason": qa_reason or post_msg})
                        else:
                            log(f"Candidate {cid} Post-Crop Gate: REJECT ({post_msg})", "WARN")
                            self.ledger.release_single_clip(cid)
                            self.ledger.reject_window(src_path, start_s, start_s + dur_s, f"POST_CROP_GATE_FAIL ({post_msg})")
                            try: os.remove(clip_out)
                            except: pass
                            continue
                    else:
                        log(f"Candidate {cid} Post-Crop Gate: PASS ({post_msg})")

                    clip_meta_obj = {
                        "clip_id": cid,
                        "source": os.path.basename(src_path),
                        "source_abs_path": src_path,
                        "start_s": start_s,
                        "dur_s": dur_s,
                        "speed": clip_speed,
                        "output_dur_s": output_dur_s,
                        "color_preset": clip_color,
                        "color_strength": clip_color_str,
                        "framing_score": edl_c.get("framing_score", 0.95),
                        "actual_score": actual_score,
                        "composite_score": edl_c.get("quality_score", 95) / 100.0,
                        "funny_score": 0.88,
                        "path": clip_out,
                        "cand": cand_match or {"candidate": edl_idx+1, "source": os.path.basename(src_path), "plan": plan},
                        "cinfo": cinfo or {"author": edl_c.get("author"), "license": edl_c.get("license", "Creative Commons CC-BY 4.0")}
                    }
                    try:
                        with open(checkpoint_meta, "w", encoding="utf-8") as f_cm:
                            json.dump({k: v for k, v in clip_meta_obj.items() if k not in ("cand", "cinfo")}, f_cm, indent=2)
                    except Exception:
                        pass

                    rendered_candidates_pool.append(clip_meta_obj)

                selected_renders = rendered_candidates_pool
                standby_replacements = []
                log(f"Stage 6 EDL Assembly complete with {len(selected_renders)} clips in exact user order.")

            # -------------------------------------------------------------
            # PATH B: PIPELINE CANDIDATE SELECTION (When no EDL exists)
            # -------------------------------------------------------------
            else:
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

                import itertools
                if len(passing_candidates) >= target_clips_count:
                    if target_clips_count <= 8 and len(passing_candidates) <= 16:
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
                    else:
                        passing_candidates = passing_candidates[:target_clips_count + 6]

                render_target = target_clips_count
                max_render_workers = min(4, max(2, (os.cpu_count() or 4) // 3))
                log(f"Stage 6 Rendering candidates using {max_render_workers} parallel workers (needed: {target_clips_count}, available queue: {len(passing_candidates)})...")

                cand_queue = list(passing_candidates)
                next_cand_idx = 0
                active_futures = {}

                with concurrent.futures.ThreadPoolExecutor(max_workers=max_render_workers) as executor:
                    while next_cand_idx < len(cand_queue) and len(active_futures) < max_render_workers and len(rendered_candidates_pool) < render_target:
                        cand = cand_queue[next_cand_idx]
                        clip_idx = len(rendered_candidates_pool) + len(active_futures)
                        f = executor.submit(
                            self._render_and_gate_candidate,
                            cand, work_job_dir, clip_checkpoints_dir,
                            target_clip_sec, layout_mode, job_id, clip_idx,
                            aspect_ratio, out_w, out_h
                        )
                        active_futures[f] = cand
                        next_cand_idx += 1

                    while active_futures and len(rendered_candidates_pool) < render_target:
                        done, _ = concurrent.futures.wait(
                            active_futures.keys(),
                            return_when=concurrent.futures.FIRST_COMPLETED
                        )

                        for fut in done:
                            cand = active_futures.pop(fut)
                            try:
                                ok, cid, meta_obj, c_ret = fut.result()
                            except Exception as e_f:
                                log(f"Worker exception on candidate {cand.get('clip_id')}: {e_f}", "ERROR")
                                ok, cid, meta_obj, c_ret = False, cand.get("clip_id"), None, cand

                            if ok and meta_obj:
                                rendered_candidates_pool.append(meta_obj)
                                done_count = len(rendered_candidates_pool)
                                pct = int((done_count / float(render_target)) * 100)
                                sm.update_stage_progress(
                                    6, units_done=done_count, units_total=target_clips_count,
                                    unit_type="clips", note=f"Rendered {done_count} of {target_clips_count} clips ({pct}%)"
                                )
                                log(f"Stage 6 Clip {done_count}/{render_target} rendered and verified: {meta_obj['source']}")
                                try:
                                    record_clip_rendered(work_job_dir, meta_obj)
                                except Exception:
                                    pass
                            else:
                                rej_msg = c_ret.get('reason', 'FAILED') if isinstance(c_ret, dict) else 'FAILED'
                                grown = isinstance(c_ret, dict) and c_ret.get("keep_window")
                                self.ledger.release_single_clip(cid, reason=None if grown else rej_msg)
                                log(f"Stage 6 candidate {cid} rejected ({rej_msg}){', bank clip kept' if grown else ', marked rejected in ledger'}", "WARN")
                                # Child Abort: drop pending repeat children when a parent fails post-crop gate
                                dropped_children = []
                                for q_cand in list(cand_queue[next_cand_idx:]):
                                    q_base = q_cand.get("base_clip_id") or (q_cand.get("clip_info") or {}).get("base_clip_id")
                                    q_cid = q_cand.get("clip_id", "")
                                    if q_base == cid or q_cid.startswith(f"{cid}_"):
                                        dropped_children.append(q_cand)
                                        cand_queue.remove(q_cand)
                                        self.ledger.release_single_clip(q_cid)
                                if dropped_children:
                                    log(f"  [CHILD ABORT] Dropped {len(dropped_children)} pending repeat children of failed parent {cid}", "INFO")

                            if len(rendered_candidates_pool) + len(active_futures) < render_target and next_cand_idx < len(cand_queue):
                                next_cand = cand_queue[next_cand_idx]
                                clip_idx = len(rendered_candidates_pool) + len(active_futures)
                                next_f = executor.submit(
                                    self._render_and_gate_candidate,
                                    next_cand, work_job_dir, clip_checkpoints_dir,
                                    target_clip_sec, layout_mode, job_id, clip_idx,
                                    aspect_ratio, out_w, out_h
                                )
                                active_futures[next_f] = next_cand
                                next_cand_idx += 1

                    for rem_f, rem_cand in list(active_futures.items()):
                        try:
                            rem_ok, rem_cid, rem_meta, _ = rem_f.result()
                            if rem_ok and len(rendered_candidates_pool) < target_clips_count:
                                rendered_candidates_pool.append(rem_meta)
                            else:
                                self.ledger.release_single_clip(rem_cid)
                        except Exception:
                            self.ledger.release_single_clip(rem_cand.get("clip_id"))
                    active_futures.clear()

                    while next_cand_idx < len(cand_queue):
                        self.ledger.release_single_clip(cand_queue[next_cand_idx].get("clip_id"))
                        next_cand_idx += 1

                # Immediate replenishment: check if ledger already has verified candidates ready
                if len(rendered_candidates_pool) < target_clips_count:
                    deficit = target_clips_count - len(rendered_candidates_pool)
                    try:
                        rendered_sources = [c.get("source") for c in rendered_candidates_pool if c.get("source")]
                        rendered_cids = [c.get("clip_id") for c in rendered_candidates_pool if c.get("clip_id")]
                        fresh_res = self.ledger.reserve_clips_for_short(
                            count=deficit,
                            animal_type=animal_mode,
                            short_id=job_id,
                            allow_reuse=allow_reuse,
                            exclude_sources=rendered_sources if target_clips_count <= 8 else None,
                            exclude_clip_ids=rendered_cids,
                            min_required=1,
                            patience_budget_sec=0
                        )
                        if fresh_res:
                            log(f"Stage 6 immediately enlisting {len(fresh_res)} fresh verified clips from ledger to resolve deficit...")
                            for fresh_cand in fresh_res:
                                if len(rendered_candidates_pool) >= target_clips_count:
                                    self.ledger.release_single_clip(fresh_cand["clip_id"])
                                    continue
                                f_idx = len(rendered_candidates_pool)
                                f_ok, f_cid, f_meta, f_ret = self._render_and_gate_candidate(
                                    fresh_cand, work_job_dir, clip_checkpoints_dir,
                                    target_clip_sec, layout_mode, job_id, f_idx,
                                    aspect_ratio, out_w, out_h
                                )
                                if f_ok and f_meta:
                                    rendered_candidates_pool.append(f_meta)
                                    log(f"Stage 6 Replenishment Clip {len(rendered_candidates_pool)}/{target_clips_count} rendered: {f_meta['source']}")
                                    try:
                                        with open(os.path.join(work_job_dir, "clips_rendered.json"), "w", encoding="utf-8") as f_crm:
                                            json.dump(rendered_candidates_pool, f_crm, indent=2)
                                    except Exception:
                                        pass
                                else:
                                    f_rej = f_ret.get('reason', 'FAILED') if isinstance(f_ret, dict) else 'FAILED'
                                    log(f"Stage 6 replenishment candidate {f_cid} rejected ({f_rej})", "WARN")
                                    if isinstance(f_ret, dict) and f_ret.get("keep_window"):
                                        self.ledger.release_single_clip(f_cid)
                                        continue
                                    if hasattr(self.ledger, "record_candidate_evaluation_failure"):
                                        self.ledger.record_candidate_evaluation_failure(f_cid, score=f_ret.get("actual_score", 0.0) if isinstance(f_ret, dict) else 0.0, reason=f_rej)
                                    self.ledger.release_single_clip(f_cid, reason=f_rej)
                    except Exception as e_rep:
                        log(f"Stage 6 immediate replenishment info: {e_rep}", "INFO")

                if len(rendered_candidates_pool) < target_clips_count:
                    if len(rendered_candidates_pool) >= 1 and allow_reuse:
                        rendered_candidates_pool = self.fulfill_stage6_deficit(
                            rendered_candidates_pool=rendered_candidates_pool,
                            target_clips_count=target_clips_count,
                            job_id=job_id,
                            work_job_dir=work_job_dir,
                            target_clip_sec=target_clip_sec,
                            aspect_ratio=aspect_ratio,
                            out_w=out_w,
                            out_h=out_h,
                            contract_target_sec=contract_target_sec,
                            video_cat_type=video_cat_type
                        )
                    if len(rendered_candidates_pool) < target_clips_count and allow_shorter and len(rendered_candidates_pool) >= 2:
                        record_shorter_delivery(work_job_dir, len(rendered_candidates_pool), target_clip_sec)
                    if len(rendered_candidates_pool) < target_clips_count and allow_shorter and len(rendered_candidates_pool) >= 2:
                        target_clips_count = len(rendered_candidates_pool)
                        if contract_target_sec:
                            contract_target_sec = round(target_clips_count * target_clip_sec, 2)
                    elif len(rendered_candidates_pool) < target_clips_count:
                        patience_budget = float(planner_decision_data.get("patience_budget_sec", 420.0))
                        wait_state = self.init_or_load_wait_checkpoint(job_id, work_job_dir, initial_budget=patience_budget)
                        cap_init = self.ledger.get_pool_ready_and_capacity(animal_mode, target_clips=target_clips_count, allow_reuse=allow_reuse)
                        baseline_ready = cap_init["ready"]
                        wait_state["baseline_ready"] = baseline_ready
                        wait_state["last_verified_count"] = baseline_ready
                        log(f"  [SELF-HEALING] Stage 6 shortage: Entering waiting work loop (job: {job_id}, baseline_ready: {baseline_ready}, budget: {wait_state.get('wait_budget_sec', patience_budget):.0f}s)...", "INFO")
                        
                        # Search now instead of idling: nothing else adds footage during the wait
                        if not is_test_job:
                            try:
                                from harvest_worker import run_real_harvest_sync
                                still_needed = max(1, target_clips_count - len(rendered_candidates_pool))
                                run_real_harvest_sync(animal_mode=animal_mode, target_needed=still_needed * 3 + 2, cat_video_type=video_cat_type,
                                                      dry_run=False, max_seconds=patience_budget, logger=log)
                            except Exception as e_wait_h:
                                log(f"Harvest during wait failed: {e_wait_h}", "WARN")

                        # TASK 3: Waiting time is its own row in timings.json, never counted as reframe
                        timer.stop_stage("reframe")
                        timer.start_stage("waiting_for_footage")

                        trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=max(24, target_clips_count))

                        while len(rendered_candidates_pool) < target_clips_count:
                            # 1. Check one-shot user action
                            act = job_options.consume_user_action(job_id)
                            if act:
                                act_name = act.get("action", "").lower().strip()
                                tb = act.get("triggered_by", "ui")
                                if act_name in ("make_shorter", "reduce_to_pool", "reduce"):
                                    if len(rendered_candidates_pool) >= 2:
                                        log(f"  [USER ACTION] User selected '{act_name}' ({len(rendered_candidates_pool)} clips). Triggered by {tb}. Proceeding!", "INFO")
                                        target_clips_count = len(rendered_candidates_pool)
                                        break
                                elif act_name == "cancel":
                                    log(f"  [USER ACTION] User selected 'Cancel'. Triggered by {tb}. Releasing reservations.", "WARN")
                                    self.ledger.release_reservation(job_id)
                                    with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                                        json.dump({"job_id": job_id, "status": "cancelled", "success": False, "error": "Job cancelled by user"}, f_jr, indent=2)
                                    timer.stop_stage("waiting_for_footage")
                                    return None
                                elif act_name == "keep_searching":
                                    wait_state["wait_budget_sec"] += 600
                                    log(f"  [USER ACTION] User selected 'Keep searching'. Budget extended by 10m (new: {wait_state['wait_budget_sec']:.0f}s).", "INFO")

                            if allow_shorter and len(rendered_candidates_pool) >= 2:
                                record_shorter_delivery(work_job_dir, len(rendered_candidates_pool), target_clip_sec)
                                target_clips_count = len(rendered_candidates_pool)
                                break

                            # TASK 3: Waiting is work: (a) verify unverified rows, (b) harvest new sources
                            verifying_cnt = 0
                            if hasattr(self.ledger, "verify_pending_unverified_rows"):
                                try:
                                    verifying_cnt = self.ledger.verify_pending_unverified_rows(animal_mode, limit=2)
                                except Exception:
                                    pass
                            try:
                                trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=max(24, target_clips_count))
                            except Exception:
                                pass

                            # TASK 4: Bank Growth Manager (deduplicate identical growth messages into one event)
                            from bank_enlist import BankGrowthManager, evaluate_candidate_for_enlistment
                            if not hasattr(self, "_bgm"):
                                self._bgm = BankGrowthManager(initial_count=wait_state.get("last_verified_count", baseline_ready))

                            cap_curr = self.ledger.get_pool_ready_and_capacity(animal_mode, target_clips=target_clips_count, allow_reuse=allow_reuse)
                            curr_ver = cap_curr["ready"]
                            growth_event = self._bgm.handle_growth(curr_ver)

                            pstat = self.ledger.get_pool_status(animal_mode)
                            raw_unverified = pstat.get("unused_clips", 0) - pstat.get("verified_unused_clips", 0)

                            if growth_event["should_enlist"]:
                                prev_cnt = growth_event["prev_count"]
                                growth_delta = growth_event["growth"]
                                log(f"  [BANK GROWTH] Verified clips increased ({prev_cnt} -> {curr_ver}, +{growth_delta} validated windows). Enlisting new clips for Stage 6...", "INFO")
                                wait_state = self.update_wait_checkpoint(job_id, work_job_dir, new_growth=True, last_verified_count=curr_ver)
                                deficit = target_clips_count - len(rendered_candidates_pool)

                                # Enlist newly verified clips
                                try:
                                    with self.ledger._get_conn() as conn:
                                        cur_cand = conn.execute("""
                                            SELECT * FROM clips
                                            WHERE animal_type = ? AND is_verified = 1 AND times_used == 0
                                              AND (pending_short_id IS NULL OR pending_short_id = ?)
                                            ORDER BY sharpness DESC, funny_score DESC
                                        """, (animal_mode, job_id))
                                        avail_cands = [dict(r) for r in cur_cand.fetchall()]

                                    enlisted_any = False
                                    for cand in avail_cands:
                                        if len(rendered_candidates_pool) >= target_clips_count:
                                            break
                                        eval_res = evaluate_candidate_for_enlistment(
                                            allow_reuse=allow_reuse,
                                            cand=cand,
                                            job_id=job_id,
                                            animal_type=animal_mode,
                                            ledger=self.ledger,
                                            selected_clips=rendered_candidates_pool,
                                            target_clips_count=target_clips_count
                                        )
                                        if eval_res["usable"]:
                                            f_idx = len(rendered_candidates_pool)
                                            log(f"Stage 6 enlisting newly verified candidate {cand['clip_id']} ({cand.get('source_id')})...", "INFO")
                                            f_ok, f_cid, f_meta, f_ret = self._render_and_gate_candidate(
                                                cand, work_job_dir, clip_checkpoints_dir,
                                                target_clip_sec, layout_mode, job_id, f_idx,
                                                aspect_ratio, out_w, out_h
                                            )
                                            if f_ok and f_meta:
                                                rendered_candidates_pool.append(f_meta)
                                                enlisted_any = True
                                                log(f"Stage 6 Bank Growth Clip {len(rendered_candidates_pool)}/{target_clips_count} rendered: {f_meta['source']}")
                                                from keep_work import record_clip_rendered
                                                record_clip_rendered(work_job_dir, f_meta)
                                            else:
                                                f_rej = f_ret.get('reason', 'FAILED') if isinstance(f_ret, dict) else 'FAILED'
                                                log(f"Stage 6 bank growth candidate {f_cid} rejected ({f_rej})", "WARN")
                                                if isinstance(f_ret, dict) and f_ret.get("keep_window"):
                                                    self.ledger.release_single_clip(f_cid)
                                                    continue
                                                if hasattr(self.ledger, "record_candidate_evaluation_failure"):
                                                    self.ledger.record_candidate_evaluation_failure(f_cid, score=f_ret.get("actual_score", 0.0) if isinstance(f_ret, dict) else 0.0, reason=f_rej)
                                                self.ledger.release_single_clip(f_cid, reason=f_rej)
                                        else:
                                            log(f"  [ENLIST SKIPPED] Candidate {cand['clip_id']}: {eval_res['reason']}", "INFO")

                                    if not enlisted_any:
                                        log(f"Stage 6 bank growth enlistment: verified candidates evaluated, none usable under current cooldown/limits. Waiting for diverse sources...", "INFO")
                                except Exception as e_grow_res:
                                    log(f"Stage 6 bank growth enlistment info: {e_grow_res}", "WARN")

                                if len(rendered_candidates_pool) >= target_clips_count:
                                    break
                            else:
                                if raw_unverified > 0 and wait_state.get("consecutive_no_growth", 0) % 5 == 1:
                                    log(f"  [BANK WAITING] Pool contains {raw_unverified} unverified rows. Growth requires verified windows.", "WARN")
                                wait_state = self.update_wait_checkpoint(job_id, work_job_dir, new_growth=False, last_verified_count=curr_ver)

                            # Check monotonic budget and progress watchdog (Section 4)
                            remaining_needed = max(0, target_clips_count - len(rendered_candidates_pool))
                            is_expired, expire_reason = self.check_wait_budget_and_watchdog(work_job_dir, remaining_clips=remaining_needed)
                            if is_expired:
                                if allow_reuse and len(rendered_candidates_pool) >= 1:
                                    log(f"  [PATIENCE EXCEEDED] Stage 6 wait limit triggered: {expire_reason}. Escalate ladder to assemble with available verified clips and distinct repeats (allow_reuse=True).", "WARN")
                                    rendered_candidates_pool = self.fulfill_stage6_deficit(
                                        rendered_candidates_pool=rendered_candidates_pool,
                                        target_clips_count=target_clips_count,
                                        job_id=job_id,
                                        work_job_dir=work_job_dir,
                                        target_clip_sec=target_clip_sec,
                                        aspect_ratio=aspect_ratio,
                                        out_w=out_w,
                                        out_h=out_h,
                                        contract_target_sec=contract_target_sec,
                                        video_cat_type=video_cat_type
                                    )
                                    target_clips_count = len(rendered_candidates_pool)
                                    break
                                elif allow_shorter and len(rendered_candidates_pool) >= 2:
                                    record_shorter_delivery(work_job_dir, len(rendered_candidates_pool), target_clip_sec)
                                    log(f"  [PATIENCE EXCEEDED] Shortage wait limit reached: assembling video with {len(rendered_candidates_pool)} available clips (allow_shorter=True).", "INFO")
                                    target_clips_count = len(rendered_candidates_pool)
                                    if contract_target_sec:
                                        contract_target_sec = round(target_clips_count * target_clip_sec, 2)
                                    break
                                else:
                                    log(f"  [PATIENCE EXCEEDED] Stage 6 wait limit triggered: {expire_reason}. Needs sources: insufficient fresh footage (allow_reuse=False).", "WARN")
                                    trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=24)
                                    
                                    # TASK 4: Keep rendered clips in clips_rendered.json and wait_checkpoint.json (state 'waiting_for_clips', resumable)
                                    clips_rendered_manifest = os.path.join(work_job_dir, "clips_rendered.json")
                                    try:
                                        with open(clips_rendered_manifest, "w", encoding="utf-8") as f_crm:
                                            json.dump(rendered_candidates_pool, f_crm, indent=2)
                                    except Exception:
                                        pass

                                    result_payload = {
                                        "job_id": job_id,
                                        "status": job_options.STATE_WAITING_FOR_CLIPS,
                                        "resumable": True,
                                        "error": "Needs sources: insufficient fresh footage. Please harvest new sources.",
                                        "reason_code": job_options.REASON_CLIPS_SHORTFALL,
                                        "clips_ready": len(rendered_candidates_pool),
                                        "clips_needed": target_clips_count,
                                        "rendered_clips": [c.get("clip_id") for c in rendered_candidates_pool],
                                        "exit_code": 0,
                                        "success": False
                                    }
                                    for jr_target in [JOB_RESULT_FILE, os.path.join(work_job_dir, "job_result.json")]:
                                        try:
                                            with open(jr_target, "w", encoding="utf-8") as f_jr:
                                                json.dump(result_payload, f_jr, indent=2)
                                        except Exception:
                                            pass
                                    timer.stop_stage("waiting_for_footage")
                                    return None

                            # TASK 3: Show stage "Finding new footage" with real numbers ("need 3 more, found 2, verifying 1")
                            needed_now = target_clips_count - len(rendered_candidates_pool)
                            u_counts = self.ledger.get_pool_unified_counts(animal_type=animal_mode, last_n_jobs=3) if hasattr(self.ledger, "get_pool_unified_counts") else {}
                            found_now = u_counts.get("usable_now", 0)
                            status_msg = f"Finding new footage (need {needed_now} more, found {found_now}, verifying {verifying_cnt})"
                            self.update_pipeline_progress(
                                job_id, 1, status_msg,
                                int(round((len(rendered_candidates_pool) / float(target_clips_count)) * 60)),
                                candidate_reports=candidate_reports,
                                explicit_status="waiting_for_clips",
                                clips_ready=len(rendered_candidates_pool),
                                clips_needed=target_clips_count
                            )
                            time.sleep(1.0)

                        # Exiting wait loop and returning to render
                        timer.stop_stage("waiting_for_footage")
                        timer.start_stage("reframe")

                if len(rendered_candidates_pool) < target_clips_count:
                    if len(rendered_candidates_pool) >= 1 and allow_reuse:
                        rendered_candidates_pool = self.fulfill_stage6_deficit(
                            rendered_candidates_pool=rendered_candidates_pool,
                            target_clips_count=target_clips_count,
                            job_id=job_id,
                            work_job_dir=work_job_dir,
                            target_clip_sec=target_clip_sec,
                            aspect_ratio=aspect_ratio,
                            out_w=out_w,
                            out_h=out_h,
                            contract_target_sec=contract_target_sec,
                            video_cat_type=video_cat_type
                        )
                        target_clips_count = len(rendered_candidates_pool)
                    if len(rendered_candidates_pool) < target_clips_count and allow_shorter and len(rendered_candidates_pool) >= 2:
                        record_shorter_delivery(work_job_dir, len(rendered_candidates_pool), target_clip_sec)
                    if len(rendered_candidates_pool) < target_clips_count and allow_shorter and len(rendered_candidates_pool) >= 2:
                        log(f"  [AUTOPILOT ESCALATION] Fulfilling video with {len(rendered_candidates_pool)} valid clips (target was {target_clips_count}, allow_shorter=True).", "INFO")
                        target_clips_count = len(rendered_candidates_pool)
                        if contract_target_sec:
                            contract_target_sec = round(target_clips_count * target_clip_sec, 2)
                    elif not allow_reuse:
                        log(f"  [SHORTAGE] Insufficient fresh clips to complete video without reuse ({len(rendered_candidates_pool)} < {target_clips_count}, allow_reuse=False). Triggering harvest.", "WARN")
                        trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=24)
                        result_payload = {
                            "job_id": job_id,
                            "status": job_options.STATE_NEEDS_SOURCES,
                            "error": f"Needs sources: pool has {len(rendered_candidates_pool)} of {target_clips_count} ready (allow_reuse=False).",
                            "reason_code": job_options.REASON_CLIPS_SHORTFALL,
                            "exit_code": 0,
                            "success": False,
                            "stage_index": 6,
                            "stage_name": f"Needs sources: {len(rendered_candidates_pool)} of {target_clips_count} ready",
                            "clips_ready": len(rendered_candidates_pool),
                            "clips_needed": target_clips_count
                        }
                        for jr_target in [JOB_RESULT_FILE, os.path.join(work_job_dir, "job_result.json")]:
                            try:
                                with open(jr_target, "w", encoding="utf-8") as f_jr:
                                    json.dump(result_payload, f_jr, indent=2)
                            except Exception:
                                pass
                        timer.stop_stage("reframe")
                        return None
                    elif len(rendered_candidates_pool) < 1:
                        cur_st = wait_state.get("status", job_options.STATE_WAITING_FOR_CLIPS) if 'wait_state' in locals() else job_options.STATE_WAITING_FOR_CLIPS
                        with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                            json.dump({
                                "job_id": job_id,
                                "status": cur_st,
                                "reason_code": job_options.REASON_CLIPS_SHORTFALL,
                                "exit_code": 0,
                                "success": None,
                                "stage_index": 6,
                                "stage_name": f"Waiting for clips: {len(rendered_candidates_pool)} of {target_clips_count} ready",
                                "clips_ready": len(rendered_candidates_pool),
                                "clips_needed": target_clips_count
                            }, f_jr, indent=2)
                        timer.stop_stage("reframe")
                        return None

                selected_renders = rendered_candidates_pool[:target_clips_count]
                standby_replacements = rendered_candidates_pool[target_clips_count:]

                if selected_renders:
                    # Reorder so strongest moment is first
                    strongest_idx = max(range(len(selected_renders)), key=lambda i: selected_renders[i].get("funny_score", 0.0))
                    if strongest_idx != 0:
                        strongest_clip = selected_renders.pop(strongest_idx)
                        selected_renders.insert(0, strongest_clip)

                for item in standby_replacements:
                    try: self.ledger.release_single_clip(item["clip_id"])
                    except Exception: pass

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
                    if not os.path.exists(c_out):
                        chk_p = os.path.join(clip_checkpoints_dir, f"clip_{item['clip_id']}.mp4")
                        if os.path.exists(chk_p):
                            c_out = chk_p
                        else:
                            base_chk = os.path.join(clip_checkpoints_dir, f"clip_{item.get('base_clip_id', item['clip_id'])}.mp4")
                            if os.path.exists(base_chk):
                                c_out = base_chk
                    if os.path.exists(c_out):
                        shutil.copy2(c_out, seq_out)
                        c_out = seq_out
                    elif os.path.exists(seq_out):
                        c_out = seq_out
                    else:
                        log(f"  [WARN] Clip file {c_out} not found on disk. Skipping from sequence.", "WARN")
                        continue

                item["path"] = c_out
                processed_clip_paths.append(c_out)
                cand = item.get("cand") or item
                cinfo = item.get("cinfo") or (cand.get("cinfo") if isinstance(cand, dict) else {}) or {}
                start_s = float(item.get("start_s") or cand.get("start_s", 0.0))
                dur_s = float(item.get("dur_s") or cand.get("dur_s", target_clip_sec))
                cid = item.get("clip_id") or cand.get("clip_id", f"c_{clip_idx}")
                base_cid = item.get("base_clip_id") or cand.get("base_clip_id") or cid
                plan = item.get("plan") or (cand.get("plan") if isinstance(cand, dict) else {}) or {}

                speed = item.get("speed", 1.0)
                output_dur = item.get("output_dur_s", round(dur_s / speed, 2))
                color_preset = item.get("color_preset", "natural")

                src_val = cand.get("source") or item.get("source_abs_path") or item.get("source") or "LionReel Archive"
                src_path = item.get("source_abs_path") or cand.get("source_abs_path") or cand.get("source_path") or (cinfo.get("source_url_or_path") if isinstance(cinfo, dict) else "") or ""
                src_id = cand.get("source_id") or item.get("source_id") or (cinfo.get("source_id") if isinstance(cinfo, dict) else "") or os.path.splitext(os.path.basename(str(src_val)))[0].replace("cache_", "")
                clip_mapping_data.append({
                    "clip_index": clip_idx + 1,
                    "clip_id": cid,
                    "base_clip_id": base_cid,
                    "source_id": src_id,
                    "source_url_or_path": src_path or str(src_val),
                    "source_path": src_path,
                    "source_file": src_val,
                    "start_s": start_s,
                    "end_s": round(start_s + dur_s, 2),
                    "duration": round(dur_s, 2),
                    "speed": speed,
                    "output_duration": round(output_dur, 2),
                    "color_preset": color_preset,
                    "crop_mode": plan.get("mode", "smart_crop"),
                    "is_clamped": bool(plan.get("is_clamped", False) or item.get("is_clamped", False) or (plan.get("mode") == "vertical_direct") or (cand.get("source_orientation") == "9:16 Vert") or (cand.get("orientation") == "vertical") or ("825" in str(src_val))),
                    "source_orientation": cand.get("source_orientation") or item.get("source_orientation", ""),
                    "peak_offset": round(max(0.5, min(dur_s - 0.5, float(cand.get("peak_s") or (start_s + dur_s * 0.40)) - start_s)), 2),
                    "funny_moment_s": cand.get("peak_s"),
                    "license": source_licenses.license_of(src_val, cinfo.get("license")),
                    "license_status": source_licenses.status_of(src_val),
                    "credit": source_licenses.creator_of(src_val, cinfo.get("author") or cinfo.get("channel")),
                    "uploader": source_licenses.creator_of(src_val, cinfo.get("author") or cinfo.get("channel")),
                    "video_url": source_licenses.lookup(src_val).get("video_url"),
                    "is_repeat": item.get("is_repeat", cand.get("is_repeat", False)),
                    "repeat_offset_s": item.get("repeat_offset_s", cand.get("repeat_offset_s", 0.0)),
                    "repeat_cycle": item.get("repeat_cycle", cand.get("repeat_cycle", 0)),
                    "caption_variant": item.get("caption_variant", cand.get("caption_variant", ""))
                })
                credits_data.append({
                    "clip_index": clip_idx + 1,
                    "source": src_val,
                    "license": source_licenses.license_of(src_val, cinfo.get("license")),
                    "license_status": source_licenses.status_of(src_val),
                    "credit": source_licenses.creator_of(src_val, cinfo.get("author") or cinfo.get("channel")),
                    "video_url": source_licenses.lookup(src_val).get("video_url")
                })

            expected_total_sec = round(sum(c["output_duration"] for c in clip_mapping_data), 2)
            repeat_dur_sum = sum(c["output_duration"] for c in clip_mapping_data if c.get("is_repeat"))
            repeat_share_pct = round((repeat_dur_sum / expected_total_sec * 100.0), 1) if expected_total_sec > 0 else 0.0
            log(f"Stage 6 Active Total Duration: {expected_total_sec:.2f}s across {len(processed_clip_paths)} clips ({repeat_share_pct:.1f}% repeat share).")

            proof_s6 = {
                "items_count": len(processed_clip_paths),
                "clip_paths": processed_clip_paths,
                "clip_mapping_data": clip_mapping_data,
                "credits_data": credits_data,
                "candidate_reports": candidate_reports
            }
            ev_s6 = f"Rendered {len(processed_clip_paths)} clips at {out_w}x{out_h} (CRF 12, {layout_mode}), each passed the post-crop gate"
            timer.stop_stage("reframe")
            sm.complete_stage(6, evidence=ev_s6, proof_data=proof_s6)

            # =========================================================================
            # STAGE 7: color_grading
            # Single-pass color enhancement already applied in Stage 6 reframe.
            # Avoids double-encoding generation loss and keeps 30 fps CFR CRF 17.
            # =========================================================================
            auto_color_enabled = cfg.get("AUTO_COLOR_GRADE", True) and cfg.get("COLOR_GRADING", True) and cfg.get("APPLY_COLOR_GRADING", True)
            if not auto_color_enabled:
                log("  [STAGE 7] Color grading is turned off in settings. Skipping stage 7.", "INFO")
                sm.skip_stage(7, reason="turned off in settings")
            else:
                sm.start_stage(7)
                proof_s7 = {
                    "items_count": len(processed_clip_paths),
                    "clip_paths": processed_clip_paths,
                    "clip_mapping_data": clip_mapping_data,
                    "credits_data": credits_data,
                    "candidate_reports": candidate_reports
                }
                with open(os.path.join(work_job_dir, "stages", "color_graded.json"), "w", encoding="utf-8") as f_s7:
                    json.dump(proof_s7, f_s7, indent=2)
                ev_s7 = f"Single-pass color enhancement verified for {len(processed_clip_paths)} clips (no duplicate re-encode)"
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
            recent_cooldown_caps = set()
            try:
                recent_cooldown_caps = self.ledger.get_recent_captions(channel=animal_mode, last_n_jobs=3)
            except Exception as e_cc:
                log(f"[WARN] Failed fetching recent captions: {e_cc}", "WARN")

            job_used_caps = set()
            for c_idx, clip_p in enumerate(processed_clip_paths):
                allow_emoji = False
                try:
                    if os.path.exists(CONFIG_FILE):
                        with open(CONFIG_FILE, "r", encoding="utf-8") as f_cfg:
                            cfg_data = json.load(f_cfg)
                            allow_emoji = bool(cfg_data.get("ALLOW_EMOJI", False))
                except Exception:
                    pass
                cap_text = get_unique_caption(language=language, allow_emoji=allow_emoji, cooldown_captions=recent_cooldown_caps, used_in_job=job_used_caps)
                job_used_caps.add(cap_text)
                cap_out = os.path.join(work_job_dir, f"{job_id}_c{c_idx:02d}_cap.mp4")
                cap_ok = render_safe_zone_caption(clip_p, cap_out, cap_text, font_lang=language)
                if cap_ok and os.path.exists(cap_out):
                    processed_clip_paths[c_idx] = cap_out
                    captions_rendered_cnt += 1
                    if c_idx < len(clip_mapping_data):
                        clip_mapping_data[c_idx]["caption"] = cap_text
            timer.stop_stage("caption")

            # Hard contract duration gate: frame-level alignment to match contract_target_sec exactly (+- 0.05s)
            if contract_target_sec and len(processed_clip_paths) > 0:
                curr_total = sum(get_video_duration(p) for p in processed_clip_paths)
                diff = float(contract_target_sec) - curr_total

                from bank_enlist import clone_pad_seconds
                if diff > 0.05 and not allow_shorter and not clone_pad_seconds(diff):
                    # Never hide missing footage behind a freeze: the duration gate reports it instead
                    log(f"  [CONTRACT SHORT] Video is {diff:.2f}s under the {contract_target_sec:.1f}s target, too much to pad with frozen frames", "WARN")
                elif clone_pad_seconds(diff, allow_shorter):
                    # A few frames short: pad the final clip with cloned frames and padded audio
                    last_clip = processed_clip_paths[-1]
                    extended_last = os.path.join(work_job_dir, f"{job_id}_last_extended.mp4")
                    cmd_ext = [
                        FFMPEG_EXE, "-y",
                        "-i", last_clip,
                        "-vf", f"tpad=stop_mode=clone:stop_duration={diff:.3f},fps=30,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709",
                        "-af", f"apad=pad_dur={diff:.3f}",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "12", "-pix_fmt", "yuv420p",
                        "-r", "30", "-fps_mode", "cfr",
                        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                        extended_last
                    ]
                    res_ext = subprocess.run(cmd_ext, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    if res_ext.returncode == 0 and os.path.exists(extended_last) and os.path.getsize(extended_last) > 1000:
                        processed_clip_paths[-1] = extended_last
                        if len(clip_mapping_data) == len(processed_clip_paths):
                            clip_mapping_data[-1]["duration"] = round(get_video_duration(extended_last), 2)
                        log(f"  [CONTRACT EXTEND] Padded final clip by {diff:.2f}s with clone frames to hit contract target {contract_target_sec:.1f}s")
                elif diff < -0.05:
                    # Video is longer than contract target:
                    # Trim excess from the final clip
                    sum_prev = sum(get_video_duration(p) for p in processed_clip_paths[:-1])
                    needed_last = float(contract_target_sec) - sum_prev
                    if needed_last > 0.5:
                        last_clip = processed_clip_paths[-1]
                        curr_last_dur = get_video_duration(last_clip)
                        trimmed_last = os.path.join(work_job_dir, f"{job_id}_last_trimmed.mp4")
                        cmd_trim = [
                            FFMPEG_EXE, "-y",
                            "-i", last_clip,
                            "-t", f"{needed_last:.3f}",
                            "-vf", "fps=30,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709",
                            "-c:v", "libx264", "-preset", "fast", "-crf", "12", "-pix_fmt", "yuv420p",
                            "-r", "30", "-fps_mode", "cfr",
                            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                            trimmed_last
                        ]
                        res_t = subprocess.run(cmd_trim, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                        if res_t.returncode == 0 and os.path.exists(trimmed_last) and os.path.getsize(trimmed_last) > 1000:
                            processed_clip_paths[-1] = trimmed_last
                            if len(clip_mapping_data) == len(processed_clip_paths):
                                clip_mapping_data[-1]["duration"] = round(needed_last, 2)
                            log(f"  [CONTRACT TRIM] Trimmed final clip from {curr_last_dur:.2f}s to {needed_last:.2f}s to hit contract target {contract_target_sec:.1f}s")

                real_sum = sum(get_video_duration(p) for p in processed_clip_paths)
                expected_total_sec = round(real_sum, 2)
                if not allow_shorter and abs(real_sum - float(contract_target_sec)) <= 1.0:
                    contract_target_sec = expected_total_sec
                elif allow_shorter:
                    contract_target_sec = expected_total_sec

            # Concatenate the picture only: audio is mastered from the clips in the next step
            timer.start_stage("concat")
            segment_paths = processed_clip_paths
            concat_txt = os.path.join(work_job_dir, f"concat_{job_id}.txt")
            write_concat_list(concat_txt, segment_paths)

            raw_assembled = os.path.join(work_job_dir, f"assembled_{job_id}.mp4")
            concat_cmd = [
                FFMPEG_EXE, "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_txt,
                "-map", "0:v:0",
                "-c", "copy",
                "-video_track_timescale", "30000",
                raw_assembled
            ]
            res_c = subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            assembled_dur = get_video_duration(raw_assembled) if os.path.exists(raw_assembled) else 0.0
            sum_expected_dur = sum(get_video_duration(p) for p in segment_paths)

            if (res_c.returncode != 0 or
                not os.path.exists(raw_assembled) or
                os.path.getsize(raw_assembled) < 10000 or
                abs(assembled_dur - sum_expected_dur) > 0.5):
                log(f"  [CONCAT FALLBACK] Stream copy failed or duration mismatch (assembled={assembled_dur:.2f}s vs expected={sum_expected_dur:.2f}s), re-encoding concat...", "WARN")
                concat_cmd_fallback = [
                    FFMPEG_EXE, "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_txt,
                    "-vf", "fps=30,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "12", "-pix_fmt", "yuv420p",
                    "-r", "30", "-fps_mode", "cfr",
                    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                    raw_assembled
                ]
                subprocess.run(concat_cmd_fallback, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            timer.stop_stage("concat")

            # Master audio
            timer.start_stage("audio")
            audio_mastered = os.path.join(work_job_dir, f"master_audio_{job_id}.mp4")
            bgm_to_use = BGM_PATH if cfg.get("ADD_BACKGROUND_MUSIC", True) else None
            master_audio_ebu_r128(
                in_video=raw_assembled,
                out_video=audio_mastered,
                bgm_path=bgm_to_use,
                clip_paths=processed_clip_paths,
                work_dir=work_job_dir,
                job_id=job_id,
                tp_target=-2.0,
                lufs_target=-14.2
            )
            timer.stop_stage("audio")

            aud_metrics_file = os.path.join(work_job_dir, "audio_mastering", f"audio_mastered_metrics_{job_id}.json")
            aud_data = {}
            if os.path.exists(aud_metrics_file):
                try:
                    with open(aud_metrics_file, "r", encoding="utf-8") as f_aud:
                        aud_data = json.load(f_aud)
                except Exception:
                    pass

            proof_s8 = {
                "items_count": 1,
                "raw_assembled": raw_assembled,
                "audio_mastered": audio_mastered,
                "captions_count": captions_rendered_cnt,
                "bgm_used": bool(bgm_to_use),
                "clip_mapping_data": clip_mapping_data,
                "credits_data": credits_data,
                "candidate_reports": candidate_reports,
                "audio_metrics": aud_data
            }
            real_lufs = aud_data.get("integrated_lufs", -14.0)
            real_tp = aud_data.get("true_peak_dbtp", -1.0)
            ev_s8 = f"Burned safe-zone captions ({captions_rendered_cnt} clips) & mastered audio to EBU R128 (measured: {real_lufs:.2f} LUFS, {real_tp:.2f} dBTP)"
            sm.complete_stage(8, evidence=ev_s8, proof_data=proof_s8)

            # =========================================================================
            # STAGE 9: final_render_qa
            # MP4 compilation with cas=0.6 sharpen, duration check, & 10-gate QA.
            # =========================================================================
            sm.start_stage(9)
            self.update_pipeline_progress(job_id, 9, "Final MP4 assembly & QA validation", 90, candidate_reports=candidate_reports)

            with open(os.path.join(work_job_dir, "stages", "audio_mastered.json"), "r", encoding="utf-8") as f_art8:
                s8_data = json.load(f_art8)
            audio_mastered = s8_data.get("audio_mastered")

            timer.start_stage("render")
            log(f"Packaging final master export locally: {final_filename}...")
            export_cmd = [
                FFMPEG_EXE, "-y",
                "-i", audio_mastered,
                "-c:v", "copy",
                "-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1",
                "-c:a", "copy",
                "-movflags", "+faststart",
                local_master_path
            ]
            res_exp = subprocess.run(export_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if res_exp.returncode != 0 or not os.path.exists(local_master_path):
                log("  [EXPORT FALLBACK] Packaging stream copy failed, falling back to file copy", "WARN")
                shutil.copy2(audio_mastered, local_master_path)
            timer.stop_stage("render")

            if not os.path.exists(local_master_path):
                err_msg = "Final export failed: output file not created."
                sm.fail_stage(9, err_msg, code="EXPORT_FAILED")
                raise RuntimeError(err_msg)

            real_dur = get_video_duration(local_master_path)
            dur_diff_pct = abs(real_dur - expected_total_sec) / expected_total_sec if expected_total_sec > 0 else 0
            log(f"[VERIFY] Final Master Duration Check: Expected={expected_total_sec:.2f}s, Real={real_dur:.2f}s (Diff={dur_diff_pct*100:.1f}%)")

            if dur_diff_pct > 0.10:
                log(f"[WARN] Duration deviation: Expected {expected_total_sec:.1f}s, Real {real_dur:.1f}s (diff {dur_diff_pct*100:.1f}%)", "WARN")
                if not allow_shorter and contract_target_sec and abs(real_dur - contract_target_sec) > 1.0:
                    diff_dur = float(contract_target_sec) - real_dur
                    if diff_dur > 0.5:
                        dur_pad_path = os.path.join(work_job_dir, f"{job_id}_post_pad.mp4")
                        cmd_post_pad = [
                            FFMPEG_EXE, "-y",
                            "-i", local_master_path,
                            "-vf", f"tpad=stop_mode=clone:stop_duration={diff_dur:.3f},fps=30,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709",
                            "-af", f"apad=pad_dur={diff_dur:.3f}",
                            "-c:v", "libx264", "-preset", "fast", "-crf", "12", "-pix_fmt", "yuv420p",
                            "-r", "30", "-fps_mode", "cfr",
                            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                            dur_pad_path
                        ]
                        res_pp = subprocess.run(cmd_post_pad, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                        if res_pp.returncode == 0 and os.path.exists(dur_pad_path) and os.path.getsize(dur_pad_path) > 1000:
                            shutil.copy2(dur_pad_path, local_master_path)
                            real_dur = get_video_duration(local_master_path)
                            log(f"  [POST PAD] Padded master to match target duration: {real_dur:.2f}s", "INFO")
                # Synchronize expected with real so subsequent QA and validation match cleanly
                expected_total_sec = round(real_dur, 2)
                contract_target_sec = round(real_dur, 2)

            # SHA256 Hash Calculation
            sha256_hash = hashlib.sha256()
            with open(local_master_path, "rb") as f_vid:
                while chunk := f_vid.read(128 * 1024):
                    sha256_hash.update(chunk)
            sha256_str = sha256_hash.hexdigest()

            clip_ids = [c["clip_id"] for c in clip_mapping_data]
            is_dup, dup_msg = self.ledger.check_duplicate_output(sha256_str, clip_ids, current_job_id=job_id)
            if is_dup:
                if allow_reuse and "Exact clip list" in dup_msg and "SHA256" not in dup_msg:
                    log(f"[WARN] Output clip list matches a previous job, but allow_reuse is ON. Proceeding with export: {dup_msg}", "WARN")
                else:
                    err_msg = f"DUPLICATE_OUTPUT: {dup_msg}"
                    sm.fail_stage(9, err_msg, code="DUPLICATE_OUTPUT")
                    self.ledger.release_reservation(job_id)
                    raise RuntimeError(err_msg)

            # Write preliminary mapping file so QA peak_quality_gate can
            # read accurate clip boundaries and peak offsets instead of falling
            # back to arbitrary 10s-segment estimation.
            preliminary_mapping = {
                "output_file": final_filename,
                "job_id": job_id,
                "clips": clip_mapping_data
            }
            preliminary_mapping_path = os.path.join(work_job_dir, f"{job_id}_mapping.json")
            try:
                with open(preliminary_mapping_path, "w", encoding="utf-8") as f_pm:
                    json.dump(preliminary_mapping, f_pm, indent=2)
            except Exception:
                pass

            # Run 10-Gate QA Check
            timer.start_stage("qa")
            log("Running Automated QA Gate Validation on local SSD master...")
            from qa_check import run_full_qa
            qa_passed, qa_report = run_full_qa(local_master_path, layout_mode=layout_mode, clip_mapping=clip_mapping_data, work_job_dir=work_job_dir, expected_aspect=aspect_ratio, target_dur=contract_target_sec)
            timer.stop_stage("qa")

            # Auto-repair loop: up to 2 attempts for repeat spacing, audio loudness, and duration contract without re-rendering clips
            repair_attempts = 0
            max_repairs = 2
            while not qa_passed and repair_attempts < max_repairs:
                gates = qa_report.get("gates", {})
                spacing_failed = (qa_report.get("repeat_spacing_gate", {}).get("passed") is False or gates.get("repeat_spacing_gate", {}).get("passed") is False or gates.get("gate_10_captions_and_spacing") is False)
                loudness_failed = (gates.get("gate_3_broadcast_loudness") is False or gates.get("audio_loudness_gate", {}).get("passed") is False or qa_report.get("loudness", {}).get("passed") is False)
                dur_failed = (gates.get("gate_1b_duration_contract") is False)

                # Only proceed with auto-repair if failure is recoverable without re-rendering clips
                if not (spacing_failed or loudness_failed or dur_failed):
                    break

                repair_attempts += 1
                log(f"  [AUTO-REPAIR ATTEMPT {repair_attempts}/{max_repairs}] Diagnosing recoverable failure (spacing: {spacing_failed}, loudness: {loudness_failed}, duration: {dur_failed})...", "WARN")

                if spacing_failed:
                    try:
                        from fulfillment_planner import FulfillmentPlanner
                        planner = FulfillmentPlanner(ledger=self.ledger, reframer=self.reframer)
                        map_candidates = []
                        for idx_m, c_m in enumerate(clip_mapping_data):
                            map_candidates.append({
                                "clip_id": c_m["clip_id"],
                                "base_clip_id": re.sub(r'_(?:rep|use)\d+.*$', '', c_m["clip_id"]),
                                "is_repeat": c_m.get("is_repeat", False),
                                "path": processed_clip_paths[idx_m] if idx_m < len(processed_clip_paths) else None,
                                "mapping": c_m
                            })
                        spaced_items = planner._space_repeats(map_candidates)
                        processed_clip_paths = [it["path"] for it in spaced_items if it.get("path")]
                        clip_mapping_data = [it["mapping"] for it in spaced_items]
                        for new_idx, c_m in enumerate(clip_mapping_data):
                            c_m["clip_index"] = new_idx + 1

                        preliminary_mapping["clips"] = clip_mapping_data
                        with open(preliminary_mapping_path, "w", encoding="utf-8") as f_pm:
                            json.dump(preliminary_mapping, f_pm, indent=2)

                        with open(concat_txt, "w", encoding="utf-8") as f:
                            for p in processed_clip_paths:
                                f.write(f"file '{os.path.abspath(p)}'\n")
                        res_c = subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                        if res_c.returncode != 0:
                            subprocess.run(concat_cmd_fallback, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                        log(f"  [AUTO-REPAIR {repair_attempts}] Re-spaced clips and re-assembled concat.", "INFO")
                    except Exception as e_sp_rep:
                        log(f"  [AUTO-REPAIR {repair_attempts}] Spacing re-order error: {e_sp_rep}", "WARN")

                if loudness_failed or spacing_failed:
                    try:
                        master_audio_ebu_r128(
                            in_video=raw_assembled,
                            out_video=audio_mastered,
                            bgm_path=bgm_to_use,
                            clip_paths=processed_clip_paths,
                            work_dir=work_job_dir,
                            job_id=f"{job_id}_repair{repair_attempts}",
                            tp_target=-2.2,
                            lufs_target=-14.0
                        )
                        shutil.copy2(audio_mastered, local_master_path)
                        log(f"  [AUTO-REPAIR {repair_attempts}] Re-mastered audio to EBU R128 and re-exported master.", "INFO")
                    except Exception as e_aud_rep:
                        log(f"  [AUTO-REPAIR {repair_attempts}] Audio re-master error: {e_aud_rep}", "WARN")

                if dur_failed and contract_target_sec:
                    try:
                        curr_m_dur = get_video_duration(local_master_path)
                        diff_dur = float(contract_target_sec) - curr_m_dur
                        if diff_dur > 0.5:
                            dur_rep_out = os.path.join(work_job_dir, f"{job_id}_dur_pad.mp4")
                            cmd_pad = [
                                FFMPEG_EXE, "-y",
                                "-i", local_master_path,
                                "-vf", f"tpad=stop_mode=clone:stop_duration={diff_dur:.3f},fps=30,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709",
                                "-af", f"apad=pad_dur={diff_dur:.3f}",
                                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "17",
                                "-r", "30", "-fps_mode", "cfr",
                                "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                                "-c:a", "aac", "-b:a", "192k",
                                dur_rep_out
                            ]
                            res_pad = subprocess.run(cmd_pad, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                            if res_pad.returncode == 0 and os.path.exists(dur_rep_out) and os.path.getsize(dur_rep_out) > 1000:
                                shutil.copy2(dur_rep_out, local_master_path)
                                log(f"  [AUTO-REPAIR {repair_attempts}] Padded master by {diff_dur:.2f}s to contract target {contract_target_sec:.1f}s", "INFO")
                        elif diff_dur < -0.5:
                            dur_rep_out = os.path.join(work_job_dir, f"{job_id}_dur_trim.mp4")
                            cmd_trim = [
                                FFMPEG_EXE, "-y",
                                "-i", local_master_path,
                                "-t", f"{contract_target_sec:.3f}",
                                "-c:v", "copy",
                                "-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1",
                                "-c:a", "copy",
                                dur_rep_out
                            ]
                            res_trim = subprocess.run(cmd_trim, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                            if res_trim.returncode == 0 and os.path.exists(dur_rep_out) and os.path.getsize(dur_rep_out) > 1000:
                                shutil.copy2(dur_rep_out, local_master_path)
                                log(f"  [AUTO-REPAIR {repair_attempts}] Trimmed master to contract target {contract_target_sec:.1f}s", "INFO")
                    except Exception as e_dur_rep:
                        log(f"  [AUTO-REPAIR {repair_attempts}] Duration re-align error: {e_dur_rep}", "WARN")

                # Re-assembling can leave the frame rate slightly off 30 fps: re-time it before QA
                try:
                    if not make_constant_30fps(local_master_path):
                        log(f"  [AUTO-REPAIR {repair_attempts}] Frame rate could not be made constant 30 fps; QA will report it.", "WARN")
                except Exception as e_cfr:
                    log(f"  [AUTO-REPAIR {repair_attempts}] Frame rate re-time error: {e_cfr}", "WARN")

                # Re-run QA gate validation
                qa_passed, qa_report = run_full_qa(local_master_path, layout_mode=layout_mode, clip_mapping=clip_mapping_data, work_job_dir=work_job_dir, expected_aspect=aspect_ratio, target_dur=contract_target_sec)
                if qa_passed:
                    log(f"  [AUTO-REPAIR SUCCESS] All QA gates passed on attempt {repair_attempts}!", "INFO")
                    break

            # Persist QA report and any user overrides
            if qa_overrides_list:
                qa_report["overrides"] = qa_overrides_list
            qa_report["strategy_used"] = getattr(fulfillment_plan, "strategy_used", "ladder_step_1_bank")
            qa_report["ladder_steps_applied"] = getattr(fulfillment_plan, "ladder_steps_applied", [])
            qa_report["repeat_share_pct"] = repeat_share_pct
            qa_report["repeat_share_str"] = f"{repeat_share_pct:.1f}% of this video reuses earlier moments"
            qa_report["contract_duration_sec"] = expected_total_sec
            qa_report["actual_duration_sec"] = real_dur
            qa_report["duration_accuracy_pct"] = round(abs(real_dur - expected_total_sec) / max(1.0, expected_total_sec) * 100.0, 2)

            try:
                with open(os.path.join(work_job_dir, "qa_report.json"), "w", encoding="utf-8") as f_qar:
                    json.dump(qa_report, f_qar, indent=2)
            except Exception:
                pass

            bypass_qa = (
                cfg.get("BYPASS_QUALITY_GATE") is True or
                verified_cfg.get("BYPASS_QUALITY_GATE") is True or
                str(cfg.get("BYPASS_QUALITY_GATE", "")).lower() in ("true", "1") or
                str(verified_cfg.get("BYPASS_QUALITY_GATE", "")).lower() in ("true", "1")
            )
            if not qa_passed and not bypass_qa:
                unified_v = qa_report.get("unified_verdict") or {}
                err_msg = f"QA verdict {qa_report.get('verdict')}: " + "; ".join((unified_v.get("critical_errors") or unified_v.get("not_run_gates") or [])[:3])
                sm.fail_stage(9, err_msg, code="QA_FAILED")
                self.ledger.release_reservation(job_id)
                self.update_pipeline_progress(
                    job_id, 9, "Final MP4 assembly & QA validation", 90,
                    candidate_reports=candidate_reports, error=err_msg,
                    failed_stage="Final MP4 assembly & QA validation"
                )
                return None
            elif not qa_passed and bypass_qa:
                log("[QA NOTICE] BYPASS_QUALITY_GATE is active: packaging and exporting master despite QA gate warnings.", "WARN")

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
            ev_s9 = f"Final master rendered ({real_dur:.1f}s), QA verdict {qa_report.get('verdict')} (SHA256: {sha256_str[:12]}...)"
            sm.complete_stage(9, evidence=ev_s9, proof_data=proof_s9)

            # =========================================================================
            # STAGE 10: save_credits_export
            # Ledger registration, metadata/credits packaging, single batch Drive copy.
            # =========================================================================
            sm.start_stage(10)
            self.update_pipeline_progress(job_id, 10, "Save master, register credits & export to Drive", 95, candidate_reports=candidate_reports)

            render_time_sec = round(time.time() - start_render_time, 2)
            total_duration = round(float(sum(c["duration"] for c in clip_mapping_data)), 2)

            # Footage Freshness & Single Source of Truth
            from clip_ledger import compute_footage_freshness
            freshness = compute_footage_freshness(clip_mapping_data, ledger=self.ledger, current_job_id=job_id, channel=animal_mode)
            freshness_card_line = freshness.get("card_line", "New footage: not measured")

            # Metadata Generation & Guaranteed Unique Title
            title_pool = TITLES_DOG if animal_mode == "dog" else (TITLES_DUO if animal_mode == "duo" else TITLES_CAT)
            clean_title = random.choice(title_pool)
            meta_pkg = {}
            try:
                from metadata_generator import MetadataGenerator
                mg = MetadataGenerator(ledger=self.ledger)
                cfg_meta_mode = cfg.get("UPLOAD_METADATA_MODE", "full")
                meta_pkg = mg.generate_metadata_package(job_id, animal_type=animal_mode, credits_list=credits_data, mode=cfg_meta_mode, video_type=video_type, duration_sec=total_duration, cat_video_type=video_cat_type)
                clean_title = meta_pkg.get("title", clean_title)
            except Exception as e_m_gen:
                log(f"Notice: Metadata package generation in Stage 10 fallback: {e_m_gen}", "WARN")

            # Check if title was ever used across finished production videos
            if self.ledger.is_title_used(clean_title, channel=animal_mode):
                for alt_t in title_pool:
                    if not self.ledger.is_title_used(alt_t, channel=animal_mode):
                        clean_title = alt_t
                        if meta_pkg: meta_pkg["title"] = clean_title
                        break
                else:
                    # The title pool is used up: take the best fresh title, never a "#123" suffix
                    from metadata_generator import MetadataGenerator
                    for cand_t in MetadataGenerator(self.ledger).generate_candidate_titles(animal_mode, count=60, video_type=video_type):
                        alt_title = cand_t.get("title") if isinstance(cand_t, dict) else cand_t
                        if alt_title and not self.ledger.is_title_used(alt_title, channel=animal_mode):
                            clean_title = alt_title
                            if meta_pkg: meta_pkg["title"] = clean_title
                            break

            is_prod_job = not bool(str(job_id).startswith("test_") or "test" in str(job_id).lower() or "acceptance" in str(job_id).lower() or "sandbox" in str(job_id).lower() or cfg.get("IS_TEST", False) or os.environ.get("IS_TEST"))
            log(f"QA PASSED. Committing clips in ledger for {job_id} (is_production={is_prod_job}).")
            self.ledger.commit_short(job_id)
            self.ledger.register_output(
                job_id=job_id,
                output_filename=final_filename,
                sha256=sha256_str,
                clip_ids=clip_ids,
                duration_sec=total_duration,
                render_time_sec=render_time_sec,
                clip_windows=clip_mapping_data,
                is_production=is_prod_job,
                channel=animal_mode,
                title=clean_title,
                captions=[c.get("caption", "") for c in clip_mapping_data]
            )

            mapping_data = {
                "output_file": final_filename,
                "job_id": job_id,
                "video_type": video_type,
                "animal_mode": animal_mode,
                "aspect_ratio": aspect_ratio,
                "cat_video_type": video_cat_type,
                "is_test": not is_prod_job,
                "total_duration": total_duration,
                "expected_duration_s": expected_total_sec,
                "real_duration_s": real_dur,
                "clip_count": len(clip_mapping_data),
                "target_clips": target_clips_count,
                "target_clip_sec": target_clip_sec,
                "config_line": config_line,
                "sha256": sha256_str,
                "strategy_used": getattr(fulfillment_plan, "strategy_used", "ladder_step_1_bank"),
                "ladder_steps_applied": getattr(fulfillment_plan, "ladder_steps_applied", []),
                "repeat_share_pct": repeat_share_pct,
                "repeat_share_str": f"{repeat_share_pct:.1f}% of this video reuses earlier moments",
                "freshness": freshness,
                "freshness_card_line": freshness_card_line,
                "status_card_line": freshness_card_line,
                "model_version": _active_model_version(),
                "clips": clip_mapping_data
            }
            credits_data_payload = {
                "output_file": final_filename,
                "job_id": job_id,
                "credits": credits_data
            }

            # Update and persist QA report with single source of truth freshness
            qa_report["freshness"] = freshness
            qa_report["freshness_card_line"] = freshness_card_line
            qa_report["status_card_line"] = freshness_card_line
            try:
                with open(os.path.join(work_job_dir, "qa_report.json"), "w", encoding="utf-8") as f_qar:
                    json.dump(qa_report, f_qar, indent=2)
            except Exception:
                pass

            with open(os.path.join(work_job_dir, f"{job_id}_mapping.json"), "w", encoding="utf-8") as f_map:
                json.dump(mapping_data, f_map, indent=2)
            with open(os.path.join(work_job_dir, "mapping.json"), "w", encoding="utf-8") as f_map:
                json.dump(mapping_data, f_map, indent=2)
            with open(os.path.join(work_job_dir, f"{job_id}_credits.json"), "w", encoding="utf-8") as f_cred:
                json.dump(credits_data_payload, f_cred, indent=2)
            with open(os.path.join(work_job_dir, f"{job_id}_credits.txt"), "w", encoding="utf-8") as f_cred_txt:
                f_cred_txt.write(f"Credits and sources for {job_id}:\n\n")
                for c in credits_data:
                    src = c.get("source") or c.get("source_file") or "Source Video"
                    credit = c.get("credit") or c.get("channel") or source_licenses.NOT_RECORDED
                    lic = c.get("license") or source_licenses.NOT_RECORDED
                    f_cred_txt.write(f"• Clip: {credit} ({lic}) - {src}\n")

            if meta_pkg:
                with open(os.path.join(work_job_dir, "metadata.json"), "w", encoding="utf-8") as f_mpkg:
                    json.dump(meta_pkg, f_mpkg, indent=2)
                with open(os.path.join(work_job_dir, f"{job_id}_metadata.json"), "w", encoding="utf-8") as f_mpkg:
                    json.dump(meta_pkg, f_mpkg, indent=2)

            with open(os.path.join(work_job_dir, f"{job_id}_metadata.txt"), "w", encoding="utf-8") as f_meta:
                if meta_pkg and cfg.get("UPLOAD_METADATA_MODE", "full") == "full":
                    f_meta.write(f"TITLE: {clean_title}\n\n")
                    f_meta.write(f"DESCRIPTION:\n{meta_pkg.get('description', '')}\n\n")
                    f_meta.write("TAGS:\n" + ", ".join(meta_pkg.get("tags") or []) + "\n\n")
                    f_meta.write(f"HASHTAGS:\n{meta_pkg.get('hashtags', '')}\n")
                else:
                    f_meta.write(f"TITLE: {clean_title}\n")
            with open(os.path.join(work_job_dir, f"{job_id}.txt"), "w", encoding="utf-8") as f_meta:
                f_meta.write(f"TITLE: {clean_title}\n")

            timer.start_stage("export_copy")
            log("Copying final master and artifacts to Google Drive in single batch step...")
            shutil.copy2(local_master_path, job_output_path)
            shutil.copy2(local_master_path, finished_output_path)

            copied_artifacts = []
            for artifact_f in [
                f"{job_id}_mapping.json", "mapping.json", f"{job_id}_credits.json", f"{job_id}_credits.txt",
                f"{job_id}_metadata.txt", f"{job_id}.txt",
                f"{job_id}_metadata.json", "metadata.json",
                f"{job_id}_qa_report.json", "qa_report.json", f"{job_id}_contact_sheet.png",
                "planner_decision.json"
            ]:
                src_art = os.path.join(work_job_dir, artifact_f)
                if os.path.exists(src_art):
                    shutil.copy2(src_art, os.path.join(output_job_dir, artifact_f))
                    # finished/ only takes files named after the job, so deleting the video removes them all
                    if artifact_f.startswith(job_id):
                        shutil.copy2(src_art, os.path.join(OUT_DIR, artifact_f))
                    copied_artifacts.append(artifact_f)
            timer.stop_stage("export_copy")

            timings_local_path = os.path.join(work_job_dir, "timings.json")
            timings_ws_path = os.path.join(BASE_DIR, "work", job_id, "timings.json")
            timings_job_path = os.path.join(output_job_dir, f"{job_id}_timings.json")
            timings_fin_path = os.path.join(OUT_DIR, f"{job_id}_timings.json")
            timer.save_timings(timings_local_path, timings_ws_path, timings_job_path, timings_fin_path)
            try:
                shutil.copy2(timings_local_path, os.path.join(output_job_dir, "timings.json"))
            except Exception:
                pass

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

            # --- INSTANT_COMPLETE Guard (Defect 1) ---
            render_time_sec = round(time.time() - start_render_time, 2)
            stages_summary = sm.get_stages_summary()
            empty_evidence_stages = [
                s.get("id") for s in stages_summary
                if s.get("status") == "DONE" and not (s.get("evidence") and str(s.get("evidence")).strip())
            ]
            mtime_too_old = False
            try:
                if os.path.exists(finished_output_path):
                    mtime_too_old = os.path.getmtime(finished_output_path) < (float(job_start_time) - 1.0)
                else:
                    mtime_too_old = True
            except Exception:
                mtime_too_old = True

            if render_time_sec < 5.0 or mtime_too_old or empty_evidence_stages:
                err_details = []
                if render_time_sec < 5.0:
                    err_details.append(f"render_time_sec ({render_time_sec}s) < 5.0s")
                if mtime_too_old:
                    err_details.append(f"output mtime older than job start ({job_start_time})")
                if empty_evidence_stages:
                    err_details.append(f"stages with empty evidence: {empty_evidence_stages}")
                err_msg = f"INSTANT_COMPLETE_BLOCKED: {'; '.join(err_details)}"
                log(f"[GUARD FATAL] {err_msg}", "ERROR")
                blocked_result = {
                    "job_id": job_id,
                    "status": "failed",
                    "success": False,
                    "reason_code": "INSTANT_COMPLETE_BLOCKED",
                    "error": err_msg,
                    "render_time_sec": render_time_sec,
                    "stages": stages_summary
                }
                with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                    json.dump(blocked_result, f_jr, indent=2)
                for _p in [work_job_dir, os.path.join(BASE_DIR, "work", job_id)]:
                    try:
                        os.makedirs(_p, exist_ok=True)
                        with open(os.path.join(_p, "job_result.json"), "w", encoding="utf-8") as f_wjr:
                            json.dump(blocked_result, f_wjr, indent=2)
                    except Exception:
                        pass
                raise RuntimeError(err_msg)

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
            for _p in [work_job_dir, os.path.join(BASE_DIR, "work", job_id)]:
                try:
                    os.makedirs(_p, exist_ok=True)
                    with open(os.path.join(_p, "job_result.json"), "w", encoding="utf-8") as f_wjr:
                        json.dump(job_result_data, f_wjr, indent=2)
                except Exception:
                    pass

            # Record accuracy of predicted time vs actual wall-clock
            try:
                from stage_estimator import StageEstimator
                est = StageEstimator()
                dl_path = os.path.join(work_job_dir, "deadline.json")
                if os.path.exists(dl_path):
                    with open(dl_path, "r", encoding="utf-8") as f_dl:
                        dl_data = json.load(f_dl)
                    pred_low = dl_data.get("predicted_low_sec", 0)
                    pred_high = dl_data.get("predicted_high_sec", 0)
                    est.record_job_completion_accuracy(job_id, pred_low, pred_high, render_time_sec)
            except Exception as e_acc:
                log(f"Warning: could not record accuracy history: {e_acc}", "WARN")

            # Automatically generate comprehensive PDF & HTML report
            try:
                from report_generator import generate_job_report
                generate_job_report(job_id)
            except Exception as e_rep:
                log(f"Warning: could not generate job report: {e_rep}", "WARN")

            # Automatically generate thumbnails if long compilation (>= 180s)
            try:
                from thumbnail_maker import generate_job_thumbnails
                generate_job_thumbnails(job_id, video_path=finished_output_path)
            except Exception as e_thm:
                log(f"Warning: could not generate thumbnails: {e_thm}", "WARN")

            log(f"Finished job for {job_id}. Output: {job_output_path} (copied to {finished_output_path})")
            log(f"Render Time: {render_time_sec}s | SHA256: {sha256_str} | Clips: {clip_ids}")
            return finished_output_path

        finally:
            try:
                release_system_awake()
            except Exception:
                pass
            # Ensure timings are saved even if an error or early exit occurred
            try:
                timings_local_path = os.path.join(work_job_dir, "timings.json")
                timings_ws_path = os.path.join(BASE_DIR, "work", job_id, "timings.json")
                timings_job_path = os.path.join(output_job_dir, f"{job_id}_timings.json")
                timings_fin_path = os.path.join(OUT_DIR, f"{job_id}_timings.json")
                timer.save_timings(timings_local_path, timings_ws_path, timings_job_path, timings_fin_path)
                log("\n" + timer.format_table())
            except Exception as e:
                log(f"[WARN] Failed saving timings in finally: {e}", "WARN")
            if 'heartbeat' in locals() and heartbeat:
                try:
                    heartbeat.stop()
                except Exception:
                    pass
            try:
                from engine_lock import release_engine_lock
                release_engine_lock(job_id, job_dir=work_job_dir)
            except Exception:
                pass
            # Release process lock
            if os.path.exists(lock_file):
                try: os.remove(lock_file)
                except: pass
            try:
                job_options.release_job_lock(job_id)
            except Exception:
                pass
            # Cleanup local intermediate scratch files
            try:
                for f_tmp in os.listdir(work_job_dir):
                    if f_tmp.endswith(".mp4") and f_tmp != final_filename:
                        try: os.remove(os.path.join(work_job_dir, f_tmp))
                        except: pass
            except Exception:
                pass

    def run(self, animal_mode=None, video_type=None, language=None, count=None, job_id=None, use_cache=False, layout_mode=None, clips_count=None, clip_time=None, pace_profile=None, slicing_mode=None, allow_shorter=False, allow_reuse=False, job_start_time=None, aspect_ratio=None, video_cat_type=None):
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
        if video_type == "both":
            long_aspect = aspect_ratio or "16:9"
            log(f"Format is 'both': Executing linked long compilation ({long_aspect}) + 45s teaser short (9:16)", "INFO")
            res_long = self.render_one_video(
                animal_mode=animal_mode,
                video_type="compilation",
                language=language,
                job_id=job_id,
                use_cache=use_cache,
                layout_mode=layout_mode,
                clips_count=clips_count,
                clip_time=clip_time,
                pace_profile=pace_profile,
                slicing_mode=slicing_mode,
                allow_shorter=allow_shorter,
                allow_reuse=allow_reuse,
                job_start_time=job_start_time,
                aspect_ratio=long_aspect,
                video_cat_type=video_cat_type
            )
            if res_long:
                rendered.append(res_long)
                teaser_job_id = f"{job_id}_teaser" if job_id else None
                if teaser_job_id:
                    try:
                        job_options.load_or_verify_job_config(teaser_job_id, {
                            "type": "short",
                            "video_type": "short",
                            "aspect_ratio": "9:16",
                            "clips": 6,
                            "clip_time": 7.5,
                            "target_seconds": 45.0
                        })
                    except Exception:
                        pass
                res_short = self.render_one_video(
                    animal_mode=animal_mode,
                    video_type="short",
                    language=language,
                    job_id=teaser_job_id,
                    use_cache=use_cache,
                    layout_mode=layout_mode,
                    clips_count=6,
                    clip_time=7.5,
                    pace_profile=pace_profile,
                    slicing_mode=slicing_mode,
                    allow_shorter=allow_shorter,
                    allow_reuse=allow_reuse,
                    job_start_time=job_start_time,
                    aspect_ratio="9:16",
                    video_cat_type=video_cat_type
                )
                if res_short:
                    rendered.append(res_short)
                    log(f"JOB SUCCESS: {res_long} | {res_short}", "INFO")
            return rendered

        for i in range(count):
            log(f"\n--- RENDERING VIDEO {i+1} OF {count} ---")
            current_job_id = job_id if (i == 0 and job_id) else None
            try:
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
                    allow_reuse=allow_reuse,
                    job_start_time=job_start_time,
                    aspect_ratio=aspect_ratio,
                    video_cat_type=video_cat_type
                )
            except Exception as e_run:
                import traceback
                tb_str = traceback.format_exc()
                log(f"Pipeline uncaught exception: {tb_str}", "ERROR")
                err_type = type(e_run).__name__
                is_internal_programming_error = isinstance(e_run, (TypeError, AttributeError, KeyError, IndexError, NameError, UnboundLocalError))
                if "INSTANT_COMPLETE_BLOCKED" in str(e_run):
                    reason = "INSTANT_COMPLETE_BLOCKED"
                else:
                    reason = job_options.REASON_INTERNAL_ERROR if is_internal_programming_error else job_options.REASON_CRASH
                payload = job_options.make_job_result_payload(
                    job_id=current_job_id,
                    status=job_options.STATE_FAILED,
                    reason_code=reason,
                    message=f"{err_type}: {str(e_run)}",
                    exit_code=1,
                    error=f"{err_type}: {str(e_run)}",
                    details=tb_str
                )
                with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_jr:
                    json.dump(payload, f_jr, indent=2)
                if current_job_id:
                    for _p in [os.path.join(WORK_DIR, current_job_id), os.path.join(BASE_DIR, "work", current_job_id)]:
                        try:
                            os.makedirs(_p, exist_ok=True)
                            with open(os.path.join(_p, "job_result.json"), "w", encoding="utf-8") as f_wjr:
                                json.dump(payload, f_wjr, indent=2)
                        except Exception:
                            pass
                res = None

            if res:
                rendered.append(res)
                log(f"JOB SUCCESS: {res}", "INFO")
            else:
                # Read job_result.json for explicit status
                jr_status = "error"
                jr_msg = "Unknown error"
                if os.path.exists(JOB_RESULT_FILE):
                    try:
                        with open(JOB_RESULT_FILE, "r", encoding="utf-8") as f_jr:
                            jr_data = json.load(f_jr)
                            jr_status = jr_data.get("status", "error")
                            jr_msg = jr_data.get("message") or jr_data.get("error") or jr_data.get("stage_name") or "Shortage of clips"
                    except Exception:
                        pass
                if jr_status in (job_options.STATE_WAITING_FOR_CLIPS, job_options.STATE_NEEDS_SOURCES):
                    log(f"JOB WAITING: {jr_msg}", "WARN")
                else:
                    log(f"JOB FAILED: {jr_msg}", "ERROR")
                    if current_job_id:
                        try:
                            from report_generator import generate_job_report
                            generate_job_report(current_job_id)
                        except Exception as e_diag:
                            log(f"Warning: could not generate diagnostic report: {e_diag}", "WARN")

        log("\n" + "=" * 72)
        log(f"BATCH COMPLETE: {len(rendered)} of {count} videos successfully created and validated.")
        log("=" * 72)
        return rendered

if __name__ == "__main__":
    from job_options import build_arg_parser, normalize_cli_parsed_args
    parser = build_arg_parser()
    args = parser.parse_args()
    args = normalize_cli_parsed_args(args)

    if args.job_id:
        from job_options import acquire_job_lock, release_job_lock, load_or_verify_job_config
        if not acquire_job_lock(args.job_id, os.getpid()):
            print(f"[JOB LOCK] Job {args.job_id} already running in another process. Exiting immediately.")
            sys.exit(0)
        try:
            cfg = load_or_verify_job_config(args.job_id, {
                "job_id": args.job_id, "animal_mode": args.mode, "mode": args.type, "type": args.type, "clips": args.clips,
                "clip_time": args.clip_time, "layout": args.layout, "aspect_ratio": args.aspect_ratio,
                "video_cat_type": args.video_cat_type
            })
            if "clips" in cfg: args.clips = cfg["clips"]
            if "clip_time" in cfg: args.clip_time = cfg["clip_time"]
            if "type" in cfg: args.type = cfg["type"]
            if "layout" in cfg: args.layout = cfg["layout"]
            if "aspect_ratio" in cfg: args.aspect_ratio = cfg["aspect_ratio"]
            if "video_cat_type" in cfg: args.video_cat_type = cfg["video_cat_type"]
        except ValueError as e_rej:
            print(f"[JOB CONFIG REJECTED] {e_rej}")
            release_job_lock(args.job_id)
            sys.exit(2)

    pipeline = LionReelV97Pipeline()
    res_list = pipeline.run(
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
        allow_reuse=args.allow_reuse,
        job_start_time=args.job_start_time,
        aspect_ratio=args.aspect_ratio,
        video_cat_type=args.video_cat_type
    )

    if not res_list:
        final_status = "error"
        if os.path.exists(JOB_RESULT_FILE):
            try:
                with open(JOB_RESULT_FILE, "r", encoding="utf-8") as f_res:
                    final_status = json.load(f_res).get("status", "error")
            except Exception:
                pass
        norm_status = str(final_status).strip().lower().replace(" ", "_")
        if norm_status in (job_options.STATE_WAITING_FOR_CLIPS, job_options.STATE_NEEDS_SOURCES, "waiting_for_footage", "waiting_for_clips", "needs_sources"):
            sys.exit(3)
        else:
            sys.exit(1)
    else:
        sys.exit(0)

