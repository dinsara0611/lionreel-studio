"""
subprocess, with a timeout on every blocking call.

Import it as `subprocess`. A hung ffmpeg, ffprobe or yt-dlp raises TimeoutExpired
instead of leaving a job at 0% for hours. Callers can still pass their own timeout.
"""

import os
import subprocess as _subprocess
from subprocess import *  # noqa: F401,F403

DEFAULT_TIMEOUTS_SEC = {
    "ffprobe": 60.0,
    "taskkill": 15.0,
    "yt-dlp": 900.0,
    "yt_dlp": 900.0,
    "ffmpeg": 3600.0,
}
FALLBACK_TIMEOUT_SEC = 900.0


def default_timeout(cmd) -> float:
    parts = [cmd] if isinstance(cmd, str) else [str(p) for p in cmd]
    head = " ".join(parts[:4]).lower()
    for name, seconds in DEFAULT_TIMEOUTS_SEC.items():
        if name in os.path.basename(parts[0]).lower() or name in head:
            return seconds
    return FALLBACK_TIMEOUT_SEC


def run(cmd, *args, **kwargs):
    kwargs.setdefault("timeout", default_timeout(cmd))
    return _subprocess.run(cmd, *args, **kwargs)


def call(cmd, *args, **kwargs):
    kwargs.setdefault("timeout", default_timeout(cmd))
    return _subprocess.call(cmd, *args, **kwargs)


def check_call(cmd, *args, **kwargs):
    kwargs.setdefault("timeout", default_timeout(cmd))
    return _subprocess.check_call(cmd, *args, **kwargs)


def check_output(cmd, *args, **kwargs):
    kwargs.setdefault("timeout", default_timeout(cmd))
    return _subprocess.check_output(cmd, *args, **kwargs)


def __getattr__(name):
    return getattr(_subprocess, name)
