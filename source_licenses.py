"""
What is actually known about a source's licence and creator.

A licence is "verified" only when the platform itself showed a Creative Commons
licence for that video. Nothing here guesses: an unknown creator stays unknown.
The records live in data/source_licenses.json, never in the ledger's own rows.
"""

import json
import os
import re
import time

import lion_paths

NOT_RECORDED = "not recorded"
VERIFIED = "verified"
NOT_SHOWN = "no licence shown"
UNCHECKED = "not checked"


def records_path() -> str:
    return os.path.join(lion_paths.data_root(), "source_licenses.json")


def load_records() -> dict:
    try:
        with open(records_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_record(video_id: str, record: dict) -> None:
    records = load_records()
    records[video_id] = record
    path = records_path()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def video_id_from(source) -> str:
    """cache_<id>.mp4, a path to it, or a YouTube URL give the 11-character video id."""
    text = str(source or "")
    m = re.search(r"cache_([A-Za-z0-9_-]{11})(?:\.\w+)?$", text) or re.search(r"[?&]v=([A-Za-z0-9_-]{11})", text)
    return m.group(1) if m else ""


def is_cc_license(text) -> bool:
    return "creative commons" in str(text or "").lower()


def record_from_info(info: dict) -> dict:
    """Builds a licence record from platform metadata."""
    shown = info.get("license")
    sizes = [(f.get("width") or 0, f.get("height") or 0) for f in info.get("formats") or [] if f.get("vcodec") not in (None, "none")]
    width, height = max(sizes, key=lambda wh: wh[0] * wh[1]) if sizes else (info.get("width") or 0, info.get("height") or 0)
    return {
        "video_id": info.get("id"),
        "status": VERIFIED if is_cc_license(shown) else NOT_SHOWN,
        "license": shown or None,
        "creator": info.get("uploader") or info.get("channel") or None,
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "width": width,
        "height": height,
        "video_url": info.get("webpage_url") or f"https://www.youtube.com/watch?v={info.get('id')}",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def fetch_record(video_id: str) -> dict:
    """Asks the platform for metadata only. Nothing is downloaded."""
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 20, "retries": 1}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    return record_from_info(info)


def worth_downloading(record: dict, min_seconds: float = 60.0) -> tuple:
    """Screens length and resolution from metadata, so nothing unusable is downloaded."""
    width, height = record.get("width") or 0, record.get("height") or 0
    if (record.get("duration") or 0) < min_seconds:
        return False, "TOO_SHORT"
    landscape = width >= height
    if (landscape and height < 960) or (not landscape and (width < 540 or height < 960)):
        return False, "LOW_RESOLUTION"
    return True, "OK"


def lookup(source) -> dict:
    return load_records().get(video_id_from(source), {})


def status_of(source) -> str:
    return lookup(source).get("status") or UNCHECKED


def creator_of(source, fallback=None) -> str:
    return lookup(source).get("creator") or fallback or NOT_RECORDED


def license_of(source, fallback=None) -> str:
    return lookup(source).get("license") or fallback or NOT_RECORDED
