"""
LionReel Windows System Power & Sleep Prevention Utility
Keeps the PC awake during active render and analysis jobs using SetThreadExecutionState.
Releases execution state when the job completes or pauses.
Tracks system sleep events via Windows Event Log or timestamp gaps so sleep time
is never counted as active working time in elapsed/ETA calculations.
"""

import sys
import os
import time
import subprocess
import ctypes
from typing import Optional, Tuple

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_AWAYMODE_REQUIRED = 0x00000040

_IS_AWAKE_HELD = False


def keep_system_awake() -> bool:
    """
    Prevents the Windows PC from entering sleep or standby while a job is running.
    Allows the display to turn off while keeping the system executing.
    """
    global _IS_AWAKE_HELD
    if sys.platform != "win32":
        return True
    try:
        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
        ret = ctypes.windll.kernel32.SetThreadExecutionState(flags)
        if ret != 0:
            _IS_AWAKE_HELD = True
            return True
    except Exception as e:
        print(f"[Power] Warning: SetThreadExecutionState failed: {e}")
    return False


def release_system_awake() -> bool:
    """
    Restores default Windows power management so the PC can sleep normally.
    """
    global _IS_AWAKE_HELD
    if sys.platform != "win32":
        return True
    try:
        ret = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        _IS_AWAKE_HELD = False
        return bool(ret != 0)
    except Exception as e:
        print(f"[Power] Warning: Release SetThreadExecutionState failed: {e}")
    return False


class SleepTracker:
    """
    Tracks whether the computer slept during a job.
    Records timestamp heartbeats and detects timestamp jumps (e.g. > 45s between 5s ticks).
    """
    def __init__(self, start_epoch: Optional[float] = None):
        self.start_epoch = start_epoch or time.time()
        self.last_heartbeat = time.time()
        self.total_sleep_seconds = 0.0
        self.sleep_events = []

    def tick(self) -> float:
        """
        Call periodically during execution. Returns detected sleep seconds added this tick.
        """
        now = time.time()
        delta = now - self.last_heartbeat
        # If heartbeat interval was expected to be ~5s, but delta is > 45s, PC was suspended/slept
        sleep_detected = 0.0
        if delta > 45.0:
            sleep_detected = delta - 5.0
            self.total_sleep_seconds += sleep_detected
            self.sleep_events.append({
                "time": now,
                "sleep_seconds": sleep_detected
            })
        self.last_heartbeat = now
        return sleep_detected

    def get_sleep_summary(self) -> dict:
        return {
            "total_sleep_seconds": round(self.total_sleep_seconds, 1),
            "sleep_events_count": len(self.sleep_events),
            "formatted": format_sleep_duration(self.total_sleep_seconds)
        }


def format_sleep_duration(seconds: float) -> str:
    """Formats sleep duration, e.g., 'computer slept for 1 h 12 min'"""
    sec = int(round(seconds))
    if sec < 60:
        return f"{sec} s"
    mins = sec // 60
    hours = mins // 60
    rem_mins = mins % 60
    if hours > 0:
        return f"{hours} h {rem_mins} min"
    return f"{mins} min"


if __name__ == "__main__":
    ok = keep_system_awake()
    print(f"Keep awake initialized: {ok}")
    time.sleep(1)
    rel = release_system_awake()
    print(f"Keep awake released: {rel}")
