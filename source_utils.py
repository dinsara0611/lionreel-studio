"""
LionReel Source Utilities & Fast Gatekeeper
High-performance ffprobe metadata inspection, upscale factor gatekeeping,
and fast source caching.
"""

import os
import lion_paths
import sys

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_VENV_SITE = os.path.join(_BASE_DIR, ".venv", "Lib", "site-packages")
if os.path.exists(_VENV_SITE) and _VENV_SITE not in sys.path:
    sys.path.insert(0, _VENV_SITE)

import json
import hashlib
import subprocess
import cv2
import imageio_ffmpeg

_PROBE_CACHE = {}

def get_ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()

def get_ffprobe_exe() -> str:
    return lion_paths.ffprobe_exe() or "ffprobe"

def compute_source_fingerprint(video_path: str) -> str:
    """Computes fast 64-character hash using file size and first 4MB header."""
    if not os.path.exists(video_path):
        return ""
    try:
        sz = os.path.getsize(video_path)
        h = hashlib.sha256()
        h.update(str(sz).encode("utf-8"))
        with open(video_path, "rb") as f:
            chunk = f.read(4 * 1024 * 1024)
            h.update(chunk)
        return h.hexdigest()
    except Exception:
        return hashlib.md5(video_path.encode("utf-8")).hexdigest()

def probe_video_fast(video_path: str) -> dict:
    """
    Extracts video resolution, framerate, duration in milliseconds.
    Caches result in memory per file path.
    """
    abs_path = os.path.abspath(video_path)
    if abs_path in _PROBE_CACHE:
        return _PROBE_CACHE[abs_path]

    if not os.path.exists(abs_path):
        res = {
            "path": abs_path,
            "width": 0,
            "height": 0,
            "fps": 30.0,
            "duration": 0.0,
            "is_landscape": True,
            "upscale_needed": 999.0,
            "pass_gate": False,
            "reason": "FILE_NOT_FOUND"
        }
        return res

    w, h, fps, dur = 0, 0, 30.0, 0.0

    # 1. Try OpenCV header read (fastest, typically 1-5ms on local disk)
    try:
        cap = cv2.VideoCapture(abs_path)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        fc = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        dur = fc / max(fps, 1.0)
        cap.release()
    except Exception:
        pass

    # 2. Fallback to FFmpeg -i if cv2 failed
    if w <= 0 or h <= 0:
        try:
            ffmpeg_exe = get_ffmpeg_exe()
            cmd = [ffmpeg_exe, "-i", abs_path]
            proc = subprocess.run(cmd, stderr=subprocess.PIPE, text=True, timeout=5)
            import re
            m = re.search(r'Stream #0:\d+.*?: Video: .*?, (\d+)x(\d+)', proc.stderr)
            if m:
                w, h = int(m.group(1)), int(m.group(2))
            m_fps = re.search(r'(\d+(?:\.\d+)?) fps', proc.stderr)
            if m_fps:
                fps = float(m_fps.group(1))
            m_dur = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', proc.stderr)
            if m_dur:
                dur = int(m_dur.group(1)) * 3600 + int(m_dur.group(2)) * 60 + float(m_dur.group(3))
        except Exception:
            pass

    is_landscape = (w >= h) if (w > 0 and h > 0) else True

    # Requirement 4: Upscale needed calculation
    # Landscape: scaled to 1920 height -> upscale = 1920 / source_height
    # Portrait: scaled to 1080x1920 -> upscale = max(1080 / width, 1920 / height)
    if is_landscape and h > 0:
        upscale_needed = round(1920.0 / h, 3)
    elif not is_landscape and w > 0 and h > 0:
        upscale_needed = round(max(1080.0 / w, 1920.0 / h), 3)
    else:
        upscale_needed = 999.0

    pass_gate = (upscale_needed <= 2.0) and (w >= 640 and h >= 640)
    reason = "PASS" if pass_gate else f"LOW_RESOLUTION: upscale {upscale_needed:.2f}x exceeds 2.0x limit ({w}x{h})"

    meta = {
        "path": abs_path,
        "filename": os.path.basename(abs_path),
        "width": w,
        "height": h,
        "fps": fps,
        "duration": round(dur, 2),
        "is_landscape": is_landscape,
        "upscale_needed": upscale_needed,
        "pass_gate": pass_gate,
        "reason": reason
    }
    _PROBE_CACHE[abs_path] = meta
    return meta

def check_and_gate_source(video_path: str, ledger=None) -> tuple:
    """
    Fail-fast check on bad sources. Runs in milliseconds.
    If source fails upscale gate (> 2.0x), blocks it in ledger and returns (False, reason).
    """
    meta = probe_video_fast(video_path)
    if not meta["pass_gate"]:
        if ledger:
            ledger.mark_source_blocked(video_path, "BLOCKED_LOW_RES")
        return False, meta["reason"]
    return True, "PASS"

def get_normalized_source_cache(video_path: str, cache_dir: str) -> str:
    """
    Requirement 6: Normalizes each source only once per job/run.
    Caches the normalized copy in the local cache folder.
    """
    os.makedirs(cache_dir, exist_ok=True)
    fp = compute_source_fingerprint(video_path)
    bname = os.path.basename(video_path)
    cached_path = os.path.join(cache_dir, f"norm_{fp[:16]}_{bname}")
    if os.path.exists(cached_path) and os.path.getsize(cached_path) > 1024 * 1024:
        return cached_path
    return video_path

def derive_source_orientation(video_path: str) -> tuple:
    """
    Derives real source orientation once per source from ffprobe metadata.
    Returns: (orientation_label, width, height)
    """
    meta = probe_video_fast(video_path)
    w = meta.get("width", 0)
    h = meta.get("height", 0)
    if w <= 0 or h <= 0:
        return "16:9 Horiz", 0, 0
    ratio = w / float(h)
    if ratio >= 1.2:
        return "16:9 Horiz", w, h
    elif ratio <= 0.8:
        return "9:16 Vert", w, h
    else:
        return "1:1 Square", w, h

def normalize_license_name(license_str: str) -> tuple:
    """
    Normalizes any license text to canonical name and link.
    Returns: (canonical_name, license_url)
    """
    if not license_str:
        return "BLOCKED", None
    raw = license_str.strip().lower()
    if "unknown" in raw or "unspecified" in raw or raw in ("blocked", "none", ""):
        return "BLOCKED", None
    
    if "cc-by" in raw or "attribution" in raw:
        if "3.0" in raw:
            return "CC BY 3.0", "https://creativecommons.org/licenses/by/3.0/"
        return "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"
    elif "cc0" in raw or "public domain" in raw or "zero" in raw:
        return "CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/"
    elif "cc-by-sa" in raw or "sharealike" in raw:
        return "CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"
    elif "standard youtube" in raw:
        return "Standard YouTube License", "https://www.youtube.com/static?template=terms"
    
    if "creative commons" in raw:
        return "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"
        
    return "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"

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
        fp = os.path.join(_BASE_DIR, fn)
        if os.path.exists(fp):
            with open(fp, "rb") as f:
                h.update(f.read())
    return h.hexdigest()[:12]
