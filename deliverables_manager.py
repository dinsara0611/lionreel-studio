import os
import sys

# Self-heal Python runtime: ensure Python 3.12 venv
if sys.version_info >= (3, 13) or sys.version_info < (3, 11):
    _CANDIDATE_VENVS = [
        r"C:\LionReel\venv\Scripts\python.exe",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Scripts", "python.exe")
    ]
    for _venv_py in _CANDIDATE_VENVS:
        if os.path.exists(_venv_py) and os.path.normpath(sys.executable) != os.path.normpath(_venv_py):
            import subprocess
            sys.exit(subprocess.call([_venv_py] + sys.argv))

import json
import zipfile
import io
import cv2
import mimetypes
from typing import Dict, Any, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FINISHED_DIR = os.path.join(BASE_DIR, "finished")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

def safe_rel_path(filepath: str) -> str:
    """Safely converts filepath to a clean relative path, handling cross-drive paths on Windows."""
    norm_fp = os.path.normpath(os.path.abspath(filepath))
    from web_server import get_local_work_dir
    local_work = os.path.normpath(os.path.abspath(get_local_work_dir()))
    
    # Try relative to BASE_DIR first
    try:
        if os.path.splitdrive(norm_fp)[0].lower() == os.path.splitdrive(BASE_DIR)[0].lower():
            return os.path.relpath(norm_fp, BASE_DIR).replace("\\", "/")
    except Exception:
        pass

    # Try relative to local_work
    try:
        if os.path.splitdrive(norm_fp)[0].lower() == os.path.splitdrive(local_work)[0].lower():
            return "work/" + os.path.relpath(norm_fp, local_work).replace("\\", "/")
    except Exception:
        pass

    # Fallback to filename
    return os.path.basename(norm_fp)

def format_file_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024.0:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024.0 * 1024.0):.1f} MB"
    else:
        return f"{num_bytes / (1024.0 * 1024.0 * 1024.0):.2f} GB"

def get_allowed_roots() -> List[str]:
    from web_server import get_local_work_dir
    roots = [
        os.path.abspath(BASE_DIR),
        os.path.abspath(FINISHED_DIR),
        os.path.abspath(OUTPUT_DIR),
        os.path.abspath(get_local_work_dir())
    ]
    return list(set(roots))

def resolve_safe_job_file(job_id: str, requested_path: str) -> str:
    """
    Prevents path traversal attacks by ensuring the target file:
    1. Resides strictly within BASE_DIR, FINISHED_DIR, OUTPUT_DIR, or LOCAL_WORK_DIR.
    2. Matches the job_id or belongs to the job's directory hierarchy.
    """
    if not requested_path or ".." in requested_path.replace("\\", "/"):
        raise PermissionError("Access denied: path traversal detected")

    clean_req = requested_path.strip().lstrip("/\\")
    
    # Try direct relative path inside BASE_DIR
    candidates = [
        os.path.abspath(os.path.join(BASE_DIR, clean_req)),
        os.path.abspath(os.path.join(FINISHED_DIR, os.path.basename(clean_req))),
        os.path.abspath(os.path.join(OUTPUT_DIR, job_id, os.path.basename(clean_req))),
        os.path.abspath(os.path.join(OUTPUT_DIR, job_id, "thumbnails", os.path.basename(clean_req))),
    ]
    try:
        from web_server import get_local_work_dir
        candidates.append(os.path.abspath(os.path.join(get_local_work_dir(), job_id, os.path.basename(clean_req))))
    except Exception:
        pass

    target_path = None
    for cand in candidates:
        if os.path.exists(cand) and os.path.isfile(cand):
            target_path = cand
            break

    if not target_path:
        raise FileNotFoundError(f"Requested file not found: {requested_path}")

    # Check root containment
    allowed_roots = get_allowed_roots()
    is_safe = False
    for root in allowed_roots:
        try:
            if os.path.commonpath([target_path, root]) == root:
                is_safe = True
                break
        except Exception:
            continue

    if not is_safe:
        raise PermissionError("Access denied: file outside permitted directories")

    return target_path

def discover_job_deliverables(job_id: str) -> Dict[str, Any]:
    """
    Scans finished/, output/<job_id>/, and work/<job_id>/ for all outputs of this job.
    Never returns fake data; returns exact sizes, dimensions, and formats from disk.
    """
    deliverables = []
    seen_types = set()
    total_bytes = 0

    seen_filenames = set()

    def _add_deliverable(item: dict, fp: str) -> bool:
        nonlocal total_bytes
        fn = item["filename"]
        # Normalize duplicate names like metadata.json vs job_metadata.json
        dedup_key = fn.replace(job_id + "_", "").replace(job_id, "")
        if dedup_key in seen_filenames:
            return False
        seen_filenames.add(dedup_key)
        seen_filenames.add(fn)
        sz = os.path.getsize(fp)
        total_bytes += sz
        deliverables.append(item)
        return True

    from web_server import get_local_work_dir
    search_dirs = [
        os.path.join(OUTPUT_DIR, job_id),
        os.path.join(OUTPUT_DIR, job_id, "thumbnails"),
        FINISHED_DIR,
        os.path.join(FINISHED_DIR, "thumbnails"),
        os.path.join(get_local_work_dir(), job_id),
        os.path.join(BASE_DIR, "work", job_id)
    ]

    # 1. Primary Video
    video_found = False
    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        for f in os.listdir(sdir):
            if f.endswith(".mp4") and (job_id in f or f == f"{job_id}.mp4"):
                fp = os.path.join(sdir, f)
                if os.path.isfile(fp):
                    sz = os.path.getsize(fp)
                    total_bytes += sz
                    res_str = "1080p"
                    dur_s = 0.0
                    try:
                        cap = cv2.VideoCapture(fp)
                        if cap.isOpened():
                            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
                            dur_s = frames / fps if fps > 0 else 0.0
                            res_str = f"{w}x{h}"
                            cap.release()
                    except Exception:
                        pass

                    rel = safe_rel_path(fp)
                    _add_deliverable({
                        "id": "master_video",
                        "category": "video",
                        "name": f"Master Video ({res_str})",
                        "filename": f,
                        "rel_path": rel,
                        "size_bytes": sz,
                        "size_formatted": format_file_size(sz),
                        "type": "video/mp4",
                        "download_url": f"/api/jobs/{job_id}/download/{urllib_quote(rel)}",
                        "meta": {
                            "resolution": res_str,
                            "duration_sec": round(dur_s, 1),
                            "duration_formatted": f"{int(dur_s // 60)}:{int(dur_s % 60):02d}" if dur_s > 0 else "--:--"
                        }
                    }, fp)
                    video_found = True
                    seen_types.add("video")
                    break
        if video_found:
            break

    # 2. Report Files (PDF, HTML, JSON)
    for ext, ctype, cat, label in [
        (".pdf", "application/pdf", "report_pdf", "Executive PDF Report (A4)"),
        (".html", "text/html", "report_html", "HTML Interactive Report"),
        (".json", "application/json", "report_json", "Machine-Readable Report (JSON)")
    ]:
        for sdir in search_dirs:
            if not os.path.exists(sdir):
                continue
            for f in os.listdir(sdir):
                if "report" in f.lower() and f.endswith(ext) and (job_id in f or f == f"report{ext}"):
                    fp = os.path.join(sdir, f)
                    if os.path.isfile(fp):
                        sz = os.path.getsize(fp)
                        rel = safe_rel_path(fp)
                        _add_deliverable({
                            "id": cat,
                            "category": "report",
                            "name": label,
                            "filename": f,
                            "rel_path": rel,
                            "size_bytes": sz,
                            "size_formatted": format_file_size(sz),
                            "type": ctype,
                            "download_url": f"/api/jobs/{job_id}/download/{urllib_quote(rel)}",
                            "meta": {}
                        }, fp)
                        seen_types.add(cat)
                        break
            if cat in seen_types:
                break

    # 3. Thumbnails (Contract: Long videos only, decide strictly by job mode, not length)
    import thumbnail_maker
    thumb_supported, _ = thumbnail_maker.is_thumbnail_supported_for_job(job_id)
    if thumb_supported:
        for sdir in search_dirs:
            if not os.path.exists(sdir):
                continue
            for f in os.listdir(sdir):
                lower_f = f.lower()
                if ("thumb" in lower_f or "thumbnail" in lower_f) and (lower_f.endswith(".jpg") or lower_f.endswith(".png")):
                    fp = os.path.join(sdir, f)
                    if os.path.isfile(fp):
                        sz = os.path.getsize(fp)
                        rel = safe_rel_path(fp)
                    dim_str = ""
                    try:
                        im = cv2.imread(fp)
                        if im is not None:
                            h, w = im.shape[:2]
                            dim_str = f"{w}x{h}"
                    except Exception:
                        pass
                    
                    label = f"Thumbnail ({dim_str or f})"
                    if "4k" in lower_f or "3840x2160" in lower_f:
                        label = f"4K Ultra-HD Master Thumbnail ({dim_str or '3840x2160'})"
                    elif "master" in lower_f:
                        label = f"Master Thumbnail ({dim_str or '1920x1080'})"
                    elif "mobile" in lower_f:
                        label = f"Mobile-Safe Thumbnail ({dim_str or '1280x720'})"
                    elif "variant" in lower_f:
                        label = f"Thumbnail Variant ({dim_str})"

                    _add_deliverable({
                        "id": f"thumb_{f}",
                        "category": "thumbnail",
                        "name": label,
                        "filename": f,
                        "rel_path": rel,
                        "size_bytes": sz,
                        "size_formatted": format_file_size(sz),
                        "type": "image/jpeg" if lower_f.endswith(".jpg") else "image/png",
                        "download_url": f"/api/jobs/{job_id}/download/{urllib_quote(rel)}",
                        "meta": {"dimensions": dim_str}
                    }, fp)

    # 4. Metadata Packages (TXT & JSON)
    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        for f in os.listdir(sdir):
            if ("metadata" in f.lower() or "credits" in f.lower()) and (job_id in f or f in ("metadata.txt", "metadata.json", "credits.txt", "credits.json")):
                fp = os.path.join(sdir, f)
                if os.path.isfile(fp):
                    sz = os.path.getsize(fp)
                    rel = safe_rel_path(fp)
                    _add_deliverable({
                        "id": f"meta_{f}",
                        "category": "metadata",
                        "name": f"Metadata & Credits ({f})",
                        "filename": f,
                        "rel_path": rel,
                        "size_bytes": sz,
                        "size_formatted": format_file_size(sz),
                        "type": "text/plain" if f.endswith(".txt") else "application/json",
                        "download_url": f"/api/jobs/{job_id}/download/{urllib_quote(rel)}",
                        "meta": {}
                    }, fp)

    # 5. QA & Diagnostics & Visuals
    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        for f in os.listdir(sdir):
            if ("contact_sheet" in f.lower() or "qa_report" in f.lower() or "timings" in f.lower() or "planner_decision" in f.lower() or "csv" in f.lower()) and (job_id in f or f in ("contact_sheet.png", "qa_report.json", "timings.json", "planner_decision.json")):
                fp = os.path.join(sdir, f)
                if os.path.isfile(fp):
                    sz = os.path.getsize(fp)
                    rel = safe_rel_path(fp)
                    cat = "visual" if f.endswith(".png") or f.endswith(".jpg") else "qa"
                    _add_deliverable({
                        "id": f"aux_{f}",
                        "category": cat,
                        "name": f"Diagnostic Asset ({f})",
                        "filename": f,
                        "rel_path": rel,
                        "size_bytes": sz,
                        "size_formatted": format_file_size(sz),
                        "type": mimetypes.guess_type(f)[0] or "application/octet-stream",
                        "download_url": f"/api/jobs/{job_id}/download/{urllib_quote(rel)}",
                        "meta": {}
                    }, fp)

    # Folder path
    primary_folder = os.path.join(OUTPUT_DIR, job_id)
    if not os.path.exists(primary_folder):
        primary_folder = FINISHED_DIR

    return {
        "job_id": job_id,
        "deliverables": deliverables,
        "total_deliverables": len(deliverables),
        "total_size_bytes": total_bytes,
        "total_size_formatted": format_file_size(total_bytes),
        "has_video": video_found,
        "folder_path": primary_folder
    }

def create_non_video_download_pack(job_id: str) -> Tuple[io.BytesIO, str]:
    """
    Creates an on-the-fly zip archive containing all non-video deliverables.
    Video is excluded by contract (video downloaded separately).
    """
    data = discover_job_deliverables(job_id)
    mem_zip = io.BytesIO()
    
    with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        added_names = set()
        for item in data.get("deliverables", []):
            if item.get("category") == "video":
                continue # strictly exclude video
            rel = item.get("rel_path")
            if not rel:
                continue
            abs_p = os.path.abspath(os.path.join(BASE_DIR, rel))
            if os.path.exists(abs_p) and os.path.isfile(abs_p):
                fname = item["filename"]
                if fname in added_names:
                    fname = f"{item['category']}_{fname}"
                added_names.add(fname)
                zf.write(abs_p, arcname=fname)

    mem_zip.seek(0)
    zip_filename = f"{job_id}_assets.zip"
    return mem_zip, zip_filename

def urllib_quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s)
