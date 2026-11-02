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
    output_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Construct standardized job_result.json payload conforming to Section 1 specification:
    {status, reason_code, message, exit_code, clips_ready, clips_needed, eta, updated_at, ...}
    """
    import time
    success_val = True if status == STATE_SUCCESS else (False if status == STATE_FAILED else None)
    return {
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
        "error": message if status == STATE_FAILED else None,
        "stage_index": int(stage_index),
        "stage_name": stage_name or message,
        "progress_pct": int(progress_pct),
        "output_file": output_file
    }

# Allowed values and aliases
FORMAT_MAP = {
    "short": "short",
    "long": "compilation",
    "compilation": "compilation",
    "both": "both"
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

    # 1. Format / Video Type
    raw_format = str(cfg.get("VIDEO_TYPE") or cfg.get("FORMAT") or "short").strip().lower()
    if raw_format not in FORMAT_MAP:
        return False, {}, f"Unknown format '{raw_format}'. Allowed: short, long, both"
    canonical_type = FORMAT_MAP[raw_format]

    # 2. Animal Mode
    raw_animal = str(cfg.get("ANIMAL_MODE") or cfg.get("VIDEO_MODE") or "cat").strip().lower()
    if raw_animal not in ANIMAL_MAP:
        return False, {}, f"Unknown animal mode '{raw_animal}'. Allowed: cat (feline), dog (canine), duo (mixed)"
    canonical_mode = ANIMAL_MAP[raw_animal]

    # 3. Layout Mode
    raw_layout = str(cfg.get("LAYOUT_MODE") or "smart_crop").strip().lower()
    if raw_layout not in LAYOUT_MAP:
        return False, {}, f"Unknown layout mode '{raw_layout}'. Allowed: smart_crop, blur_fit, auto"
    canonical_layout = LAYOUT_MAP[raw_layout]

    # 4. Language
    raw_lang = str(cfg.get("LANG") or cfg.get("LANGUAGE") or "en").strip().lower()
    if raw_lang not in LANG_MAP:
        return False, {}, f"Unknown language '{raw_lang}'. Allowed: en, si"
    canonical_lang = LANG_MAP[raw_lang]

    # 5. Pace Profile
    raw_pace = str(cfg.get("SPEED_PROFILE") or cfg.get("PACE") or "fast").strip().lower()
    if raw_pace not in PACE_MAP:
        return False, {}, f"Unknown pace profile '{raw_pace}'. Allowed: fast, balanced, cinematic"
    canonical_pace = PACE_MAP[raw_pace]

    # 6. Slicing / Moment Cut Mode
    raw_slicing = str(cfg.get("MOMENT_CUT_MODE") or cfg.get("SLICING") or "peak_viral").strip().lower()
    if raw_slicing not in SLICING_MAP:
        return False, {}, f"Unknown moment slicing mode '{raw_slicing}'. Allowed: peak_viral, fast_action, funny_moments, balanced"
    canonical_slicing = SLICING_MAP[raw_slicing]

    # 7. Numeric parameters with sensible clamping
    try:
        clips = int(cfg.get("TARGET_CLIPS", 25 if raw_format in ["long", "both"] else 4))
        if clips < 1 or clips > 100:
            return False, {}, f"Clips count must be between 1 and 100 (got {clips})"
    except (ValueError, TypeError):
        return False, {}, f"Invalid target clips count: {cfg.get('TARGET_CLIPS')}"

    try:
        clip_time = float(cfg.get("SHORT_CLIP_SEC", 12.0 if raw_format in ["long", "both"] else 7.5))
        if clip_time < 1.0 or clip_time > 60.0:
            return False, {}, f"Clip duration must be between 1.0s and 60.0s (got {clip_time})"
    except (ValueError, TypeError):
        return False, {}, f"Invalid clip duration: {cfg.get('SHORT_CLIP_SEC')}"

    allow_shorter = bool(cfg.get("ALLOW_SHORTER", False))
    allow_reuse = bool(cfg.get("ALLOW_REUSE", False))
    use_cache = bool(cfg.get("USE_CACHE", False))

    normalized = {
        "raw_format": raw_format,
        "type": canonical_type,
        "mode": canonical_mode,
        "layout": canonical_layout,
        "lang": canonical_lang,
        "pace": canonical_pace,
        "slicing": canonical_slicing,
        "clips": clips,
        "clip_time": clip_time,
        "allow_shorter": allow_shorter,
        "allow_reuse": allow_reuse,
        "use_cache": use_cache
    }

    return True, normalized, None

def build_cli_args(normalized: Dict[str, Any], job_id: str, job_start_time: Optional[float] = None) -> List[str]:
    """
    Build CLI arguments list for lion_automate_v97.py from normalized parameters.
    """
    args = [
        "--job-id", job_id,
        "--mode", normalized["mode"],
        "--type", normalized["type"],
        "--clips", str(normalized["clips"]),
        "--clip-time", str(normalized["clip_time"]),
        "--pace", normalized["pace"],
        "--slicing", normalized["slicing"],
        "--layout", normalized["layout"],
        "--lang", normalized["lang"]
    ]
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
        choices=["cat", "dog", "duo", "feline", "canine", "mixed"],
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

    if getattr(args, "mode", None) in ["feline", "canine", "mixed"]:
        old_mode = args.mode
        args.mode = ANIMAL_MAP.get(old_mode, old_mode)
        print(f"Notice: Alias --mode '{old_mode}' used, normalizing to '{args.mode}'.")

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
            for k in ["type", "mode", "clips", "clip_time", "layout"]:
                if k in incoming_cfg and incoming_cfg[k] is not None and k in existing and existing[k] is not None:
                    val_in = incoming_cfg[k]
                    val_ex = existing[k]
                    if k in ["type", "mode", "layout"]:
                        val_in = str(val_in).lower()
                        val_ex = str(val_ex).lower()
                        if val_in == "long": val_in = "compilation"
                        if val_ex == "long": val_ex = "compilation"
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
    
    saved_cfg = {
        "job_id": job_id,
        "type": incoming_cfg.get("type") or incoming_cfg.get("VIDEO_TYPE") or "compilation",
        "mode": incoming_cfg.get("mode") or incoming_cfg.get("ANIMAL_MODE") or "cat",
        "clips": incoming_cfg.get("clips") or incoming_cfg.get("CLIPS_COUNT") or 4,
        "clip_time": incoming_cfg.get("clip_time") or incoming_cfg.get("CLIP_TIME") or 12.0,
        "layout": incoming_cfg.get("layout") or incoming_cfg.get("LAYOUT_MODE") or "smart_crop",
        "allow_shorter": bool(incoming_cfg.get("allow_shorter") or incoming_cfg.get("ALLOW_SHORTER", False)),
        "allow_reuse": bool(incoming_cfg.get("allow_reuse") or incoming_cfg.get("ALLOW_REUSE", False)),
        "pace": incoming_cfg.get("pace") or incoming_cfg.get("PACE_PROFILE"),
        "slicing": incoming_cfg.get("slicing") or incoming_cfg.get("SLICING_MODE"),
        "settings_snapshot": incoming_cfg.get("settings_snapshot") or {},
        "created_at": incoming_cfg.get("created_at") or time.time()
    }
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(saved_cfg, f, indent=2)
    return saved_cfg


def is_job_process_alive(job_id: str, work_base_dir: str = None, **kwargs) -> bool:
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
    
    if is_job_process_alive(job_id, work_base_dir, **kwargs):
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
