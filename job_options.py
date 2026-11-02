"""
job_options.py
==============
Unified Contract Definition between Dashboard (Web UI / Server) and
LionReel Automation Engine (lion_automate_v97.py).

Defines:
- Allowed format, animal, layout, language, pace, slicing options and aliases.
- Server-side pre-spawn validation and normalization.
- CLI argument generation and shared argparse builder.
- Automatic normalization of safety-net aliases ("long" -> "compilation", "mixed" -> "duo").
"""

import sys
import argparse
from typing import Dict, Any, Tuple, Optional, List

# Canonical Job States
STATE_RUNNING = "running"
STATE_SUCCESS = "completed"
STATE_WAITING_FOR_CLIPS = "waiting_for_clips"
STATE_NEEDS_SOURCES = "needs_sources"
STATE_FAILED = "error"

# Canonical Reason Codes
REASON_NONE = "NONE"
REASON_CLIPS_SHORTFALL = "CLIPS_SHORTFALL"
REASON_NEEDS_SOURCES = "NEEDS_SOURCES"
REASON_INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
REASON_CRASH = "CRASH"
REASON_TIMEOUT = "TIMEOUT"
REASON_DISK_FULL = "DISK_FULL"
REASON_FFMPEG_ERROR = "FFMPEG_ERROR"
REASON_LICENSE_BLOCKED = "LICENSE_BLOCKED"
REASON_INTERNAL_ERROR = "INTERNAL_ERROR"

def make_job_result_payload(
    job_id: str,
    status: str,
    reason_code: str,
    message: str,
    exit_code: int = 0,
    clips_ready: int = 0,
    clips_needed: int = 0,
    eta: Optional[float] = None,
    stage_index: int = 1,
    stage_name: str = "",
    progress_pct: int = 0,
    output_file: Optional[str] = None,
    error: Optional[str] = None,
    details: Optional[str] = None
) -> Dict[str, Any]:
    """
    Construct standardized job_result.json payload conforming to Section 1 specification:
    {status, reason_code, message, exit_code, clips_ready, clips_needed, eta, updated_at, details, ...}
    """
    import time
    success_val = True if status == STATE_SUCCESS else (False if status == STATE_FAILED else None)
    err_msg = error if error is not None else (message if status == STATE_FAILED else None)
    res = {
        "job_id": job_id,
        "status": status,
        "reason_code": reason_code,
        "message": message,
        "exit_code": int(exit_code),
        "clips_ready": int(clips_ready),
        "clips_needed": int(clips_needed),
        "eta": eta,
        "updated_at": round(time.time(), 3),
        "success": success_val,
        "error": err_msg,
        "stage_index": int(stage_index),
        "stage_name": stage_name or message,
        "progress_pct": int(progress_pct),
        "output_file": output_file
    }
    if details is not None:
        res["details"] = str(details)
    return res

# Allowed values and aliases
FORMAT_MAP = {
    "short": "short",
    "long": "compilation",
    "compilation": "compilation",
    "both": "both"
}

ASPECT_RATIO_MAP = {
    "16:9": "16:9",
    "16-9": "16:9",
    "landscape": "16:9",
    "horizontal": "16:9",
    "widescreen": "16:9",
    "9:16": "9:16",
    "9-16": "9:16",
    "vertical": "9:16",
    "shorts": "9:16",
    "reel": "9:16",
    "1:1": "1:1",
    "square": "1:1"
}

RESOLUTION_BY_ASPECT = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080)
}

ANIMAL_MAP = {
    "cat": "cat",
    "feline": "cat",
    "dog": "dog",
    "canine": "dog",
    "duo": "duo",
    "mixed": "duo",
    "mix": "duo"
}

LAYOUT_MAP = {
    "smart_crop": "smart_crop",
    "smart crop": "smart_crop",
    "blur_fit": "blur_fit",
    "blur-fit": "blur_fit",
    "blur fit": "blur_fit",
    "auto": "auto"
}

LANG_MAP = {
    "en": "en",
    "si": "si"
}

PACE_MAP = {
    "fast": "fast",
    "balanced": "balanced",
    "cinematic": "cinematic"
}

SLICING_MAP = {
    "peak_viral": "peak_viral",
    "fast_action": "fast_action",
    "funny_moments": "funny_moments",
    "balanced": "balanced"
}

def normalize_job_options(cfg: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    """
    Validate and normalize input configuration dictionary from Web UI into canonical CLI parameters.
    Returns (is_valid, normalized_dict, error_message).
    """
    if not isinstance(cfg, dict):
        return False, {}, "Job configuration must be a JSON object"

    # 1. Format / Video Type (Honor compilation/long intent or explicit short/both)
    explicit_type = cfg.get("VIDEO_TYPE") or cfg.get("type") or cfg.get("video_type") or cfg.get("FORMAT")
    if explicit_type is not None and str(explicit_type).strip() != "":
        raw_format = str(explicit_type).strip().lower()
        if raw_format not in FORMAT_MAP:
            return False, {}, f"Unknown format '{raw_format}'. Allowed: short, long, both"
    else:
        req_dur_s = float(cfg.get("target_duration_s") or 0)
        req_dur_min = float(cfg.get("TARGET_DURATION_MIN") or 0)
        if req_dur_s >= 60.0 or req_dur_min >= 1.0:
            raw_format = "compilation"
        else:
            raw_format = "short"

    if raw_format not in FORMAT_MAP:
        return False, {}, f"Unknown format '{raw_format}'. Allowed: short, long, both"
    canonical_type = FORMAT_MAP[raw_format]

    # Aspect Ratio resolution (Long Video follows 16:9 widescreen 1920x1080, Short = 9:16 1080x1920, 1:1 = 1080x1080)
    raw_aspect = str(cfg.get("ASPECT_RATIO") or cfg.get("aspect_ratio") or cfg.get("ratio") or "").strip().lower()
    if raw_aspect and raw_aspect in ASPECT_RATIO_MAP:
        canonical_aspect = ASPECT_RATIO_MAP[raw_aspect]
    else:
        canonical_aspect = "16:9" if canonical_type in ["long", "compilation", "both"] else "9:16"
    out_w, out_h = RESOLUTION_BY_ASPECT.get(canonical_aspect, (1080, 1920))

    # Cat Video Type (Auto, double_cats, dubbed_talking, etc.)
    raw_cat_type = str(cfg.get("VIDEO_CAT_TYPE") or cfg.get("video_cat_type") or cfg.get("cat_type") or "auto").strip().lower()

    # 2. Animal Mode
    # Defensively filter out format values from animal keys if a previous bug poisoned config.json
    candidates = [
        cfg.get("animal_mode"),
        cfg.get("ANIMAL_MODE"),
        cfg.get("VIDEO_MODE"),
        cfg.get("mode")
    ]
    raw_animal = None
    for cand in candidates:
        if cand is not None:
            c_str = str(cand).strip().lower()
            if c_str and c_str not in FORMAT_MAP and c_str not in ("short", "compilation", "long", "both"):
                raw_animal = c_str
                break

    if not raw_animal:
        raw_animal = "cat"

    if raw_animal not in ANIMAL_MAP:
        return False, {}, f"Unknown animal mode '{raw_animal}'. Allowed: cat (feline), dog (canine), duo (mixed)"
    canonical_mode = ANIMAL_MAP[raw_animal]

    # 3. Layout Mode
    raw_layout = str(cfg.get("LAYOUT_MODE") or cfg.get("layout") or "smart_crop").strip().lower()
    if raw_layout not in LAYOUT_MAP:
        return False, {}, f"Unknown layout mode '{raw_layout}'. Allowed: smart_crop, blur_fit, auto"
    canonical_layout = LAYOUT_MAP[raw_layout]

    # 4. Language
    raw_lang = str(cfg.get("LANG") or cfg.get("LANGUAGE") or cfg.get("lang") or "en").strip().lower()
    if raw_lang not in LANG_MAP:
        return False, {}, f"Unknown language '{raw_lang}'. Allowed: en, si"
    canonical_lang = LANG_MAP[raw_lang]

    # 5. Pace Profile
    raw_pace = str(cfg.get("SPEED_PROFILE") or cfg.get("PACE") or cfg.get("pace") or "fast").strip().lower()
    if raw_pace not in PACE_MAP:
        return False, {}, f"Unknown pace profile '{raw_pace}'. Allowed: fast, balanced, cinematic"
    canonical_pace = PACE_MAP[raw_pace]

    # 6. Slicing / Moment Cut Mode
    raw_slicing = str(cfg.get("MOMENT_CUT_MODE") or cfg.get("SLICING") or cfg.get("slicing") or "peak_viral").strip().lower()
    if raw_slicing not in SLICING_MAP:
        return False, {}, f"Unknown moment slicing mode '{raw_slicing}'. Allowed: peak_viral, fast_action, funny_moments, balanced"
    canonical_slicing = SLICING_MAP[raw_slicing]

    # 7. Mode Contracts: Short (30-60s clamped), Long (target duration contract, derived clips), Both (Long + 45s teaser)
    default_time = 7.5
    try:
        time_val = cfg.get("SHORT_CLIP_SEC") if cfg.get("SHORT_CLIP_SEC") is not None else cfg.get("clip_time", default_time)
        clip_time = float(time_val)
        if clip_time < 1.0 or clip_time > 60.0:
            return False, {}, f"Clip duration must be between 1.0s and 60.0s (got {clip_time})"
    except (ValueError, TypeError):
        return False, {}, f"Invalid clip duration: {cfg.get('SHORT_CLIP_SEC')}"

    teaser_info = None

    if canonical_type == "short":
        # Short Video: 30-60s total. User edits clips and clip_time. Total = clips * clip_time.
        clips_val = cfg.get("TARGET_CLIPS") if cfg.get("TARGET_CLIPS") is not None else cfg.get("clips", 4)
        clips = int(clips_val)
        total_sec = clips * clip_time
        if total_sec > 60.0:
            clips = max(2, int(60.0 / clip_time))
            if clips * clip_time > 60.0:
                clip_time = round(60.0 / clips, 1)
        elif total_sec < 30.0:
            clips = max(2, int(round(30.0 / clip_time)))
            if clips * clip_time < 30.0:
                clip_time = round(30.0 / clips, 1)
        target_seconds = round(clips * clip_time, 2)

    elif canonical_type in ["compilation", "long"]:
        # Long Video: duration slider / presets (1m to 20m+) are the contract (+/-1s)
        req_dur_min = float(cfg.get("TARGET_DURATION_MIN") or 0)
        req_dur_s = float(cfg.get("target_duration_s") or 0)
        if req_dur_min > 0:
            target_seconds = round(req_dur_min * 60.0, 2)
        elif req_dur_s > 0:
            target_seconds = round(req_dur_s, 2)
        else:
            target_seconds = 300.0
        clips = max(2, int(round(target_seconds / clip_time)))

    elif canonical_type == "both":
        # Both Formats: Long part + 45s 9:16 teaser
        req_dur_min = float(cfg.get("TARGET_DURATION_MIN") or 0)
        req_dur_s = float(cfg.get("target_duration_s") or 0)
        if req_dur_min > 0:
            target_seconds = round(req_dur_min * 60.0, 2)
        elif req_dur_s > 0:
            target_seconds = round(req_dur_s, 2)
        else:
            target_seconds = 300.0
        clips = max(2, int(round(target_seconds / clip_time)))
        teaser_info = {
            "seconds": 45.0,
            "ratio": "9:16",
            "resolution": "1080x1920"
        }

    allow_shorter = bool(cfg.get("ALLOW_SHORTER", False))
    allow_reuse = bool(cfg.get("ALLOW_REUSE", False))
    use_cache = bool(cfg.get("USE_CACHE", False))

    normalized = {
        "raw_format": raw_format,
        "type": canonical_type,
        "mode": canonical_mode,
        "animal_mode": canonical_mode,
        "layout": canonical_layout,
        "lang": canonical_lang,
        "pace": canonical_pace,
        "slicing": canonical_slicing,
        "aspect_ratio": canonical_aspect,
        "ratio": canonical_aspect,
        "width": out_w,
        "height": out_h,
        "resolution": f"{out_w}x{out_h}",
        "video_cat_type": raw_cat_type,
        "clips": clips,
        "clip_count": clips,
        "clip_time": clip_time,
        "target_seconds": target_seconds,
        "teaser": teaser_info,
        "allow_shorter": allow_shorter,
        "allow_reuse": allow_reuse,
        "use_cache": use_cache
    }

    return True, normalized, None

def build_cli_args(normalized: Dict[str, Any], job_id: str, job_start_time: Optional[float] = None) -> List[str]:
    """
    Build CLI arguments list for lion_automate_v97.py from normalized parameters.
    """
    animal = normalized.get("animal_mode")
    if not animal or str(animal).lower() in ("short", "compilation", "long", "both"):
        animal = normalized.get("mode")
    if not animal or str(animal).lower() in ("short", "compilation", "long", "both"):
        animal = "cat"

    v_type = normalized.get("type") or "compilation"
    if str(v_type).lower() == "long":
        v_type = "compilation"

    clips = normalized.get("clips") if normalized.get("clips") is not None else normalized.get("clip_count", 4)
    clip_time = normalized.get("clip_time") if normalized.get("clip_time") is not None else 7.5
    pace = normalized.get("pace") or "fast"
    slicing = normalized.get("slicing") or "peak_viral"
    layout = normalized.get("layout") or "smart_crop"
    lang = normalized.get("lang") or "en"

    args = [
        "--job-id", job_id,
        "--mode", str(animal),
        "--type", str(v_type),
        "--clips", str(clips),
        "--clip-time", str(clip_time),
        "--pace", str(pace),
        "--slicing", str(slicing),
        "--layout", str(layout),
        "--lang", str(lang)
    ]
    if normalized.get("aspect_ratio"):
        args.extend(["--aspect-ratio", str(normalized["aspect_ratio"])])
    if normalized.get("video_cat_type"):
        args.extend(["--video-cat-type", str(normalized["video_cat_type"])])
    if normalized.get("allow_shorter"):
        args.append("--allow-shorter")
    if normalized.get("allow_reuse"):
        args.append("--allow-reuse")
    if normalized.get("use_cache"):
        args.append("--use-cache")
    if job_start_time is not None:
        args.extend(["--job-start-time", str(job_start_time)])
    return args

def build_arg_parser() -> argparse.ArgumentParser:
    """
    Construct the shared CLI ArgumentParser for lion_automate_v97.py,
    supporting both canonical values and safety-net aliases.
    """
    parser = argparse.ArgumentParser(description="LionReel V97 Master Pet Video Pipeline")
    parser.add_argument(
        "--mode",
        choices=["cat", "dog", "duo", "feline", "canine", "mixed", "short", "compilation", "long", "both"],
        default="cat",
        help="Animal mode (cat, dog, duo; aliases feline, canine, mixed accepted)"
    )
    parser.add_argument(
        "--type",
        choices=["short", "compilation", "long", "both"],
        default="short",
        help="Video type (short, compilation; aliases long, both accepted)"
    )
    parser.add_argument(
        "--lang",
        choices=["en", "si"],
        default="en",
        help="Language (en, si)"
    )
    parser.add_argument(
        "--layout",
        choices=["smart_crop", "blur_fit", "auto"],
        default="smart_crop",
        help="Layout framing mode (smart_crop, blur_fit, auto)"
    )
    parser.add_argument(
        "--aspect", "--aspect-ratio",
        dest="aspect_ratio",
        choices=["16:9", "9:16", "1:1", "16-9", "9-16", "landscape", "vertical", "square"],
        default=None,
        help="Output aspect ratio (16:9, 9:16, 1:1)"
    )
    parser.add_argument(
        "--cat-type", "--video-cat-type",
        dest="video_cat_type",
        default="auto",
        help="Video cat type (auto, dubbed_talking, double_cats, fails_clumsy, startled_reactions, cats_vs_objects, derp_silly, kitten_cute, cat_human_moments, cat_dog)"
    )
    parser.add_argument("--count", type=int, default=1, help="Number of videos to render")
    parser.add_argument("--job-id", default=None, help="Unique job ID for this run")
    parser.add_argument("--use-cache", action="store_true", default=False, help="Use cached result if available")
    parser.add_argument("--clips", type=int, default=None, help="Target number of clips")
    parser.add_argument("--clip-time", type=float, default=None, help="Target clip duration in seconds")
    parser.add_argument("--pace", default=None, help="Compilation pace profile (fast, balanced, cinematic)")
    parser.add_argument("--slicing", default=None, help="Moment cut mode (peak_viral, fast_action, etc.)")
    parser.add_argument("--allow-shorter", action="store_true", default=False, help="Allow shorter video if clips run out")
    parser.add_argument("--allow-reuse", action="store_true", default=False, help="Allow reusing clips across test runs")
    parser.add_argument("--job-start-time", type=float, default=None, help="Wall-clock epoch time when the job was requested")
    parser.add_argument("--group-id", default=None, help="Linked job group ID for linked runs (e.g., both format)")
    return parser

def normalize_cli_parsed_args(args: argparse.Namespace) -> argparse.Namespace:
    """
    Normalizes aliases if passed directly to the CLI and prints a one-line notice.
    """
    if getattr(args, "type", None) == "long":
        print("Notice: Alias --type 'long' used, normalizing to 'compilation'.")
        args.type = "compilation"

    if getattr(args, "mode", None) in ["short", "compilation", "long", "both"]:
        fmt_val = args.mode
        if fmt_val == "long":
            fmt_val = "compilation"
        args.type = fmt_val
        args.mode = "cat"
        print(f"Notice: Format '{fmt_val}' was passed to --mode, remapped --type to '{args.type}' and --mode to 'cat'.")

    if getattr(args, "mode", None) in ["feline", "canine", "mixed"]:
        old_mode = args.mode
        args.mode = ANIMAL_MAP.get(old_mode, old_mode)
        print(f"Notice: Alias --mode '{old_mode}' used, normalizing to '{args.mode}'.")

    if getattr(args, "aspect_ratio", None) in ASPECT_RATIO_MAP:
        args.aspect_ratio = ASPECT_RATIO_MAP[args.aspect_ratio]

    return args


def get_job_work_dir(job_id: str, work_base_dir: str = None, **kwargs) -> str:
    import os
    base = kwargs.get("work_dir") or work_base_dir or (r"C:\LionReel\work" if os.path.exists(r"C:\LionReel\work") else os.path.join(os.path.dirname(os.path.abspath(__file__)), "work"))
    if os.path.basename(base) == job_id:
        return base
    if (job_id.startswith("sandbox_") or job_id.startswith("test_")) and not base.endswith("sandbox") and not os.path.basename(base).startswith("test_sandbox_acc_"):
        return os.path.join(base, "sandbox", job_id)
    return os.path.join(base, job_id)


def load_or_verify_job_config(job_id: str, incoming_cfg: Optional[Dict[str, Any]] = None, work_base_dir: str = None, **kwargs) -> Dict[str, Any]:
    import os, json, time
    work_dir = get_job_work_dir(job_id, work_base_dir, **kwargs)
    os.makedirs(work_dir, exist_ok=True)
    cfg_path = os.path.join(work_dir, "job_config.json")
    
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if incoming_cfg:
            for k in ["type", "mode", "animal_mode", "clips", "clip_time", "layout", "aspect_ratio"]:
                if k in incoming_cfg and incoming_cfg[k] is not None and k in existing and existing[k] is not None:
                    val_in = incoming_cfg[k]
                    val_ex = existing[k]
                    if k == "mode" and str(val_in).lower() in ["cat", "dog"]:
                        # incoming mode was used as animal_mode; compare against existing animal_mode
                        val_ex = str(existing.get("animal_mode", "")).lower()
                        val_in = str(val_in).lower()
                    elif k in ["type", "mode", "layout"]:
                        val_in = str(val_in).lower()
                        val_ex = str(val_ex).lower()
                        if val_in == "long": val_in = "compilation"
                        if val_ex == "long": val_ex = "compilation"
                        if val_ex == "both" and val_in in ("compilation", "both"):
                            val_in = "both"
                    elif k in ["animal_mode"]:
                        val_in = str(val_in).lower()
                        val_ex = str(val_ex).lower()
                    elif k in ["aspect_ratio"]:
                        val_in = ASPECT_RATIO_MAP.get(str(val_in).lower(), str(val_in))
                        val_ex = ASPECT_RATIO_MAP.get(str(val_ex).lower(), str(val_ex))
                    elif k in ["clips"]:
                        val_in = int(val_in)
                        val_ex = int(val_ex)
                    elif k in ["clip_time"]:
                        val_in = round(float(val_in), 2)
                        val_ex = round(float(val_ex), 2)
                    if val_in != val_ex:
                        raise ValueError(f"Relaunch of job {job_id} with conflicting settings rejected. Setting '{k}': existing {val_ex} != requested {val_in}")
        return existing
    
    if incoming_cfg is None:
        raise ValueError(f"No job_config.json found for job {job_id} and no incoming config provided.")
    
    asp = incoming_cfg.get("aspect_ratio") or incoming_cfg.get("ASPECT_RATIO")
    c_type = incoming_cfg.get("type") or incoming_cfg.get("VIDEO_TYPE") or "compilation"
    if not asp:
        asp = "16:9" if c_type in ["long", "compilation", "both"] else "9:16"
    canonical_asp = ASPECT_RATIO_MAP.get(str(asp).lower(), "16:9" if c_type in ["long", "compilation", "both"] else "9:16")
    w_out, h_out = RESOLUTION_BY_ASPECT.get(canonical_asp, (1920, 1080) if canonical_asp == "16:9" else (1080, 1920))

    tgt_sec = incoming_cfg.get("target_seconds")
    if tgt_sec is None:
        if c_type in ["long", "compilation", "both"]:
            req_min = float(incoming_cfg.get("TARGET_DURATION_MIN") or 0)
            if req_min > 0:
                tgt_sec = req_min * 60.0
            elif incoming_cfg.get("target_duration_s"):
                tgt_sec = float(incoming_cfg.get("target_duration_s"))
            elif incoming_cfg.get("clips") and incoming_cfg.get("clip_time"):
                tgt_sec = float(incoming_cfg.get("clips")) * float(incoming_cfg.get("clip_time"))
            else:
                tgt_sec = 300.0
        else:
            tgt_sec = float(incoming_cfg.get("clips") or 4) * float(incoming_cfg.get("clip_time") or 7.5)

    clp_cnt = int(incoming_cfg.get("clip_count") or incoming_cfg.get("clips") or 4)
    clp_time = float(incoming_cfg.get("clip_time") or 7.5)

    tsr = incoming_cfg.get("teaser")
    if tsr is None and c_type == "both":
        tsr = {
            "seconds": 45.0,
            "ratio": "9:16",
            "resolution": "1080x1920"
        }

    saved_cfg = {
        "job_id": job_id,
        "mode": c_type,
        "type": c_type,
        "animal_mode": incoming_cfg.get("animal_mode") or incoming_cfg.get("ANIMAL_MODE") or "cat",
        "ratio": canonical_asp,
        "aspect_ratio": canonical_asp,
        "width": w_out,
        "height": h_out,
        "resolution": f"{w_out}x{h_out}",
        "video_cat_type": incoming_cfg.get("video_cat_type") or incoming_cfg.get("VIDEO_CAT_TYPE") or "auto",
        "target_seconds": round(float(tgt_sec), 2),
        "clip_time": round(float(clp_time), 2),
        "clip_count": int(clp_cnt),
        "clips": int(clp_cnt),
        "teaser": tsr,
        "layout": incoming_cfg.get("layout") or incoming_cfg.get("LAYOUT_MODE") or "smart_crop",
        "allow_shorter": bool(incoming_cfg.get("allow_shorter") or incoming_cfg.get("ALLOW_SHORTER", False)),
        "allow_reuse": bool(incoming_cfg.get("allow_reuse") or incoming_cfg.get("ALLOW_REUSE", False)),
        "pace": incoming_cfg.get("pace") or incoming_cfg.get("PACE_PROFILE") or "fast",
        "slicing": incoming_cfg.get("slicing") or incoming_cfg.get("SLICING_MODE") or "peak_viral",
        "settings_snapshot": incoming_cfg.get("settings_snapshot") or {},
        "created_at": incoming_cfg.get("created_at") or time.time()
    }
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(saved_cfg, f, indent=2)
    return saved_cfg


def is_job_process_alive(job_id: str, work_base_dir: str = None, exclude_pid: Optional[int] = None, **kwargs) -> bool:
    import os
    work_dir = get_job_work_dir(job_id, work_base_dir, **kwargs)
    for fname in [".pid_lock", "job.lock"]:
        lock_file = os.path.join(work_dir, fname)
        if os.path.exists(lock_file):
            try:
                with open(lock_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if not content:
                    continue
                try:
                    import json
                    d = json.loads(content)
                    pid = int(d.get("pid", 0))
                except Exception:
                    pid = int(content)
                if pid <= 0:
                    continue
                if exclude_pid is not None and pid == exclude_pid:
                    continue
                if os.name == 'nt':
                    import ctypes
                    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                    STILL_ACTIVE = 259
                    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                    if h:
                        exit_code = ctypes.c_ulong()
                        alive = False
                        if ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code)):
                            alive = (exit_code.value == STILL_ACTIVE)
                        ctypes.windll.kernel32.CloseHandle(h)
                        if alive:
                            return True
                else:
                    try:
                        os.kill(pid, 0)
                        return True
                    except OSError:
                        pass
            except Exception:
                pass
    return False


def acquire_job_lock(job_id: str, pid: Optional[int] = None, work_base_dir: str = None, **kwargs) -> bool:
    import os
    work_dir = get_job_work_dir(job_id, work_base_dir, **kwargs)
    os.makedirs(work_dir, exist_ok=True)
    lock_file = os.path.join(work_dir, ".pid_lock")
    my_pid = pid or os.getpid()
    
    if is_job_process_alive(job_id, work_base_dir, exclude_pid=my_pid, **kwargs):
        return False
    try:
        with open(lock_file, "w", encoding="utf-8") as f:
            f.write(str(my_pid))
        return True
    except Exception:
        return False


def release_job_lock(job_id: str, work_base_dir: str = None, **kwargs) -> None:
    import os
    work_dir = get_job_work_dir(job_id, work_base_dir, **kwargs)
    for fname in [".pid_lock", "job.lock"]:
        lock_file = os.path.join(work_dir, fname)
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
        except Exception:
            pass


def record_user_action(job_id: str, action: str, triggered_by_or_details: Any = "ui", work_base_dir: str = None, **kwargs) -> str:
    import os, json, time, uuid
    work_dir = get_job_work_dir(job_id, work_base_dir, **kwargs)
    os.makedirs(work_dir, exist_ok=True)
    action_file = os.path.join(work_dir, "action.json")
    event_id = str(uuid.uuid4())
    triggered_by = "ui"
    details = {}
    if isinstance(triggered_by_or_details, dict):
        details = triggered_by_or_details
    elif isinstance(triggered_by_or_details, str):
        triggered_by = triggered_by_or_details
    event = {
        "job_id": job_id,
        "event_id": event_id,
        "action": action.lower().strip(),
        "timestamp": time.time(),
        "triggered_by": triggered_by,
        "details": details,
        "consumed": False
    }
    with open(action_file, "w", encoding="utf-8") as f:
        json.dump(event, f, indent=2)
    return event


def consume_user_action(job_id: str, work_base_dir: str = None, **kwargs) -> Optional[Dict[str, Any]]:
    import os, json
    work_dir = get_job_work_dir(job_id, work_base_dir, **kwargs)
    action_file = os.path.join(work_dir, "action.json")
    if not os.path.exists(action_file):
        return None
    try:
        with open(action_file, "r", encoding="utf-8") as f:
            action_data = json.load(f)
        consumed_file = os.path.join(work_dir, "action.consumed.json")
        try:
            os.replace(action_file, consumed_file)
        except Exception:
            try: os.remove(action_file)
            except Exception: pass
        action_data["consumed"] = True
        return action_data
    except Exception:
        return None


def save_wait_checkpoint(job_id: str, checkpoint_data: Dict[str, Any], work_base_dir: str = None, **kwargs) -> str:
    import os, json
    work_dir = get_job_work_dir(job_id, work_base_dir, **kwargs)
    os.makedirs(work_dir, exist_ok=True)
    cp_path = os.path.join(work_dir, "wait_checkpoint.json")
    with open(cp_path, "w", encoding="utf-8") as f:
        json.dump(checkpoint_data, f, indent=2)
    return cp_path


def load_wait_checkpoint(job_id: str, work_base_dir: str = None, **kwargs) -> Dict[str, Any]:
    import os, json
    work_dir = get_job_work_dir(job_id, work_base_dir, **kwargs)
    cp_path = os.path.join(work_dir, "wait_checkpoint.json")
    if os.path.exists(cp_path):
        try:
            with open(cp_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def get_failure_action_options(
    reason_code: str = "SHORTAGE_WAIT_EXCEEDED",
    clips_ready: int = 0,
    clips_needed: int = 4,
    current_length_s: float = 30.0,
    possible_length_s: float = 15.0,
    reuse_share_pct: float = 25.0,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    TASK 9: Clear one-click choices on shortage/failure screen (no dialogs, nothing chosen silently):
    1. 'Find new footage now' (starts the harvest and resumes when ready)
    2. 'Resume when ready' (waits in the background, job stays in Library as 'Waiting for footage')
    3. 'Allow reuse of old footage for this video' (shows the share)
    4. 'Make a shorter video' (shows the new length)
    """
    return [
        {
            "id": "find_new_footage_now",
            "label": "Find new footage now",
            "desc": "Starts background harvest immediately and resumes job when verified clips are ready",
            "action": "harvest_and_resume"
        },
        {
            "id": "resume_when_ready",
            "label": "Resume when ready",
            "desc": "Waits in the background; job stays in Library as 'Waiting for footage'",
            "action": "wait_background"
        },
        {
            "id": "allow_reuse_old_footage",
            "label": f"Allow reuse of old footage for this video ({int(round(reuse_share_pct))}% reused share)",
            "desc": f"Allows previously used clips to fill the deficit ({int(round(reuse_share_pct))}% reused)",
            "action": "allow_reuse"
        },
        {
            "id": "make_shorter_video",
            "label": f"Make a shorter video ({int(possible_length_s)}s instead of {int(current_length_s)}s)",
            "desc": f"Renders a {int(possible_length_s)}s video with {clips_ready} verified clips",
            "action": "shorten"
        }
    ]

