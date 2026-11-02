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
