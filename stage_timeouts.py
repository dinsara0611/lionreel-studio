"""
LIONREEL STUDIO — STAGE TIMEOUTS
Defines maximum execution budgets per stage and wraps subprocess/network calls
with explicit timeouts, preventing infinite hangs across all pipeline operations.
"""

import os
import sys
import json
import time
import subprocess

class StageTimeoutError(RuntimeError):
    """Raised when an engine stage exceeds its maximum execution budget."""
    def __init__(self, stage_id: int, stage_name: str, elapsed_sec: float, max_sec: float, call_info: str = ""):
        self.stage_id = stage_id
        self.stage_name = stage_name
        self.elapsed_sec = elapsed_sec
        self.max_sec = max_sec
        self.call_info = call_info
        detail = f" [Call: {call_info}]" if call_info else ""
        msg = (
            f"STAGE_TIMEOUT: Stage {stage_id} '{stage_name}' exceeded maximum allowed duration of "
            f"{max_sec:.1f}s (elapsed {elapsed_sec:.1f}s).{detail}"
        )
        super().__init__(msg)

class SubprocessTimeoutError(RuntimeError):
    """Raised when a subprocess (ffmpeg, ffprobe, etc.) exceeds its allocated timeout."""
    def __init__(self, stage_name: str, command: str, timeout_sec: float, waited_for: str = ""):
        self.stage_name = stage_name
        self.command = command
        self.timeout_sec = timeout_sec
        self.waited_for = waited_for
        msg = (
            f"SUBPROCESS_TIMEOUT in stage '{stage_name}': Command exceeded {timeout_sec:.1f}s timeout "
            f"while waiting for {waited_for or 'subprocess completion'}. Command: {command[:200]}"
        )
        super().__init__(msg)

DEFAULT_STAGE_TIMEOUTS_SHORT = {
    0: 60.0,    # Initialization & setup
    1: 60.0,    # Collect candidate moments from ledger (extended to 300s during deficit harvest)
    2: 90.0,    # Prepare sources & cut segments
    3: 60.0,    # Quality check & frame validation
    4: 90.0,    # Watermark detection
    5: 180.0,   # AI auto-reframe prediction
    6: 360.0,   # Reframe rendering & cut export
    7: 60.0,    # Color grading
    8: 60.0,    # Dynamic animated captions
    9: 90.0,    # Audio mixing & concatenation
    10: 180.0,  # Master QA, deduplication & final export
}

DEFAULT_STAGE_NAMES = {
    0: "Job Initialization",
    1: "Collect candidate moments from ledger",
    2: "Prepare sources",
    3: "Check quality and frame rate",
    4: "Detect watermarks",
    5: "AI Auto-Reframe prediction",
    6: "Reframe cuts and render video",
    7: "Color grading and look adjustment",
    8: "Generate synchronized captions",
    9: "Audio mixing and final concatenation",
    10: "Master QA and registration",
}

DEFAULT_SUBPROCESS_TIMEOUTS = {
    "ffprobe": 30.0,
    "ffmpeg_probe": 30.0,
    "ffmpeg_cut": 90.0,
    "ffmpeg_render": 300.0,
    "ffmpeg_concat": 120.0,
    "sqlite_query": 10.0,
    "network_fetch": 45.0,
    "download_source": 300.0,
}

def get_stage_timeout_sec(stage_id: int, video_type: str = "short", is_harvesting: bool = False) -> float:
    """Returns the maximum execution duration in seconds for a given stage."""
    # Check config.json overrides if present
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cfg_file = os.path.join(base_dir, "config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                timeouts = cfg.get("STAGE_TIMEOUTS", {})
                if str(stage_id) in timeouts:
                    return float(timeouts[str(stage_id)])
        except Exception:
            pass

    if stage_id == 1 and is_harvesting:
        return 300.0  # 5 minutes if deficit harvesting is required

    return DEFAULT_STAGE_TIMEOUTS_SHORT.get(int(stage_id), 120.0)

def check_stage_timeout(stage_id: int, elapsed_sec: float, video_type: str = "short", is_harvesting: bool = False) -> tuple:
    """
    Checks if the elapsed time exceeds the stage's maximum execution limit.
    Returns (is_exceeded: bool, reason: str).
    """
    max_sec = get_stage_timeout_sec(stage_id, video_type=video_type, is_harvesting=is_harvesting)
    stage_name = DEFAULT_STAGE_NAMES.get(int(stage_id), f"Stage {stage_id}")
    if elapsed_sec > max_sec:
        reason = f"Stage {stage_id} '{stage_name}' exceeded maximum timeout of {max_sec:.1f}s (elapsed: {elapsed_sec:.1f}s)"
        return True, reason
    return False, ""

def run_subprocess_with_timeout(cmd, timeout_sec: float = None, stage_name: str = "general", waited_for: str = "", **kwargs) -> subprocess.CompletedProcess:
    """
    Executes a subprocess command with a strict timeout.
    Raises SubprocessTimeoutError with exact stage and waiting details if timeout is hit.
    """
    if timeout_sec is None:
        cmd_str = str(cmd)
        if "ffprobe" in cmd_str:
            timeout_sec = DEFAULT_SUBPROCESS_TIMEOUTS["ffprobe"]
        elif "ffmpeg" in cmd_str:
            timeout_sec = DEFAULT_SUBPROCESS_TIMEOUTS["ffmpeg_render"]
        else:
            timeout_sec = 60.0

    try:
        return subprocess.run(cmd, timeout=timeout_sec, **kwargs)
    except subprocess.TimeoutExpired as exc:
        cmd_display = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        raise SubprocessTimeoutError(
            stage_name=stage_name,
            command=cmd_display,
            timeout_sec=timeout_sec,
            waited_for=waited_for or "process execution"
        ) from exc
