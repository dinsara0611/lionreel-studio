"""
LionReel local storage locations and tool discovery, in one place.

Set LIONREEL_ROOT to redirect every local path (data, work, cache, models, tools)
to another root. Tests and sandbox runs do this so they can never reach
production data. See tests/conftest.py.
"""

import os
import shutil
import sys

PRODUCTION_ROOT = r"C:\LionReel"


def use_local_pycache() -> None:
    """Keeps compiled Python on the local disk: reading it through Google Drive is very slow."""
    prefix = local_path("pycache")
    os.environ.setdefault("PYTHONPYCACHEPREFIX", prefix)
    if sys.pycache_prefix is None:
        sys.pycache_prefix = prefix


def root() -> str:
    return os.environ.get("LIONREEL_ROOT") or PRODUCTION_ROOT


def local_path(*parts: str) -> str:
    return os.path.join(root(), *parts)


def work_root() -> str:
    return local_path("work")


def data_root() -> str:
    return os.environ.get("LIONREEL_DATA_DIR") or local_path("data")


def cache_root() -> str:
    return os.environ.get("LIONREEL_CACHE_DIR") or local_path("cache")


def models_root() -> str:
    return local_path("models")


def venv_python() -> str:
    """The interpreter that engine and worker subprocesses should run under."""
    candidate = local_path("venv", "Scripts", "python.exe")
    return candidate if os.path.exists(candidate) else (sys.executable or "python")


def is_production_root() -> bool:
    return os.path.normcase(os.path.normpath(root())) == os.path.normcase(PRODUCTION_ROOT)


def ffprobe_exe():
    """Path of a real ffprobe, or None. Callers must treat None as 'not measured'."""
    override = os.environ.get("LIONREEL_FFPROBE")
    if override and os.path.exists(override):
        return override
    name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    for candidate in (local_path("tools", name), os.path.join(PRODUCTION_ROOT, "tools", name)):
        if os.path.exists(candidate):
            return candidate
    try:
        import imageio_ffmpeg
        sibling = os.path.join(os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe()), name)
        if os.path.exists(sibling):
            return sibling
    except Exception:
        pass
    return shutil.which("ffprobe")


use_local_pycache()
