"""
LIONREEL STUDIO — KEEP WORK PRESERVATION ENGINE (SHORTAGE FIX 2)
Preserves rendered and verified clips across job pauses, waits, retries, and resumes.
Avoids discarding completed rendering work when shortage pauses occur.
"""

import os
import json
from typing import List, Dict, Any

CLIPS_RENDERED_FILE = "clips_rendered.json"

def get_preserved_rendered_clips(job_dir: str, target_clips_count: int = 4) -> List[Dict[str, Any]]:
    """
    Scans job directory for previously rendered and verified clips from an earlier attempt.
    Returns list of valid clip descriptors up to target_clips_count.
    """
    if not job_dir or not os.path.exists(job_dir):
        return []

    manifest_path = os.path.join(job_dir, CLIPS_RENDERED_FILE)
    preserved = []
    seen_ids = set()

    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            clips = data.get("rendered_clips", [])
            for c in clips:
                fpath = c.get("file") or c.get("path")
                if not fpath:
                    continue
                # If relative, resolve relative to job_dir
                if not os.path.isabs(fpath):
                    fpath = os.path.join(job_dir, fpath)
                cid = c.get("clip_id")
                if os.path.exists(fpath) and os.path.getsize(fpath) > 0 and cid not in seen_ids:
                    c_copy = dict(c)
                    c_copy["file"] = fpath
                    c_copy["path"] = fpath
                    preserved.append(c_copy)
                    if cid:
                        seen_ids.add(cid)
                    if len(preserved) >= target_clips_count:
                        return preserved
        except Exception:
            pass

    # Also scan clips subdirectory for checkpoint clips
    clips_dir = os.path.join(job_dir, "clips")
    if os.path.exists(clips_dir):
        import glob
        for meta_file in sorted(glob.glob(os.path.join(clips_dir, "*.json"))):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    c = json.load(f)
                cid = c.get("clip_id")
                if not cid or cid in seen_ids:
                    continue
                score = c.get("actual_score") or c.get("framing_score") or 0.0
                if score < 0.80:
                    continue
                fpath = c.get("path")
                if not fpath or not os.path.exists(fpath):
                    base_name = os.path.splitext(os.path.basename(meta_file))[0]
                    mp4_cand = os.path.join(clips_dir, f"{base_name}.mp4")
                    if os.path.exists(mp4_cand):
                        fpath = mp4_cand
                if fpath and os.path.exists(fpath) and os.path.getsize(fpath) > 0:
                    c_copy = dict(c)
                    c_copy["file"] = fpath
                    c_copy["path"] = fpath
                    preserved.append(c_copy)
                    seen_ids.add(cid)
                    if len(preserved) >= target_clips_count:
                        break
            except Exception:
                pass

    return preserved

def record_clip_rendered(job_dir: str, clip_info: Dict[str, Any]) -> None:
    """
    Appends or updates a rendered clip record in clips_rendered.json in job_dir.
    """
    if not job_dir or not clip_info:
        return
    try:
        os.makedirs(job_dir, exist_ok=True)
        manifest_path = os.path.join(job_dir, CLIPS_RENDERED_FILE)
        data = {"rendered_clips": []}
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {"rendered_clips": []}

        clips = data.setdefault("rendered_clips", [])
        cid = clip_info.get("clip_id")
        idx = clip_info.get("index")
        existing_idx = -1
        for i, c in enumerate(clips):
            if (cid and c.get("clip_id") == cid) or (idx is not None and c.get("index") == idx):
                existing_idx = i
                break

        c_entry = dict(clip_info)
        if not c_entry.get("file") and c_entry.get("path"):
            c_entry["file"] = c_entry["path"]

        if existing_idx >= 0:
            clips[existing_idx] = c_entry
        else:
            clips.append(c_entry)

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def get_preserved_summary(preserved_count: int, target_clips: int) -> str:
    """Returns human-readable summary for console and UI."""
    if preserved_count <= 0:
        return ""
    return f"{preserved_count} of {target_clips} clips already rendered"
