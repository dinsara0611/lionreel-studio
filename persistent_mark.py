"""
Channel marks and burned-in titles that stay in the same place for a whole source video.

A mark stays put while the footage around it changes. Sharp edges are sampled across the whole
video; edges present in most samples are grouped into boxes, and a box counts as a mark only when
the picture right around it keeps changing. That last test keeps still-camera scenes (a sofa, a
paved floor) from being taken for a logo.
"""
import os

import cv2
import numpy as np

PROC_W = 640
N_FRAMES = 40
EDGE_MAG = 40
PERSIST_SHARE = 0.70        # an edge present in at least 70% of samples is persistent
MIN_BOX_W = 24
MIN_BOX_PX = 300            # persistent edge pixels in a box (640-wide scale)
MAX_BOX_H_SHARE = 0.40      # a logo with a line of text under it can be this tall
RING_PX = 14                # width of the band around a box
MIN_RING_STD = 40.0         # the band must change over time (0-255 grey levels)
MIN_MEDIAN_EDGE = 0.60      # share of the mark's edges still sharp in the median of all samples
DEBUG = False

# One result per source video, kept so a source is measured once
CACHE_FILE = "source_marks.json"


def _ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _sample_gray(path, n=N_FRAMES):
    """
    n grey frames spread over the whole video, 640 px wide. Each frame is read with a fast ffmpeg
    seek: seeking with OpenCV took up to 5 minutes on long sources.
    """
    import timed_subprocess as subprocess
    cap = cv2.VideoCapture(path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        w, h = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0, cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0
    finally:
        cap.release()
    if fps <= 0 or total < n * 2 or w <= 0 or h <= 0:
        return []
    dur = total / fps
    out_h = max(2, int(round(h * PROC_W / w / 2.0)) * 2)
    frames = []
    for i in range(n):
        t = dur * (0.04 + 0.92 * i / (n - 1))
        cmd = [_ffmpeg_exe(), "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
               "-vf", f"scale={PROC_W}:{out_h}", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
        except Exception:
            continue
        if len(res.stdout) == PROC_W * out_h:
            frames.append(np.frombuffer(res.stdout, np.uint8).reshape(out_h, PROC_W))
    return frames


def _persistent_mask(frames):
    acc = None
    for g in frames:
        b = cv2.GaussianBlur(g, (3, 3), 0)
        mag = cv2.magnitude(cv2.Sobel(b, cv2.CV_32F, 1, 0), cv2.Sobel(b, cv2.CV_32F, 0, 1))
        e = (mag > EDGE_MAG).astype(np.float32)
        acc = e if acc is None else acc + e
    mask = ((acc / len(frames)) >= PERSIST_SHARE).astype(np.uint8)
    h, w = mask.shape
    # Frame borders and letterbox edges are long straight runs, not marks
    horiz = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((1, max(2, w // 4)), np.uint8))
    vert = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((max(2, h // 4), 1), np.uint8))
    return cv2.subtract(mask, cv2.dilate(cv2.bitwise_or(horiz, vert), np.ones((3, 3), np.uint8)))


def find_marks_in_frames(frames):
    """Boxes (x, y, w, h, edge_px, ring_std) of marks, on the 640-wide scale."""
    if len(frames) < 8:
        return None
    mask = _persistent_mask(frames)
    h, w = mask.shape
    stack = np.stack(frames).astype(np.float32)
    std = stack.std(axis=0)
    # A real mark is the same in every sample, so it stays sharp in the median picture. Busy texture
    # (gravel, paving, a patterned sofa) has edges everywhere but in different places, and blurs out.
    med = cv2.GaussianBlur(np.median(stack, axis=0).astype(np.uint8), (3, 3), 0)
    med_edges = cv2.magnitude(cv2.Sobel(med, cv2.CV_32F, 1, 0), cv2.Sobel(med, cv2.CV_32F, 0, 1)) > EDGE_MAG
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 17), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(closed)
    marks = []
    for i in range(1, n):
        x, y, bw, bh, _ = (int(v) for v in stats[i])
        px = int(mask[y:y + bh, x:x + bw].sum())
        if bw < MIN_BOX_W or not (6 <= bh <= h * MAX_BOX_H_SHARE) or px < MIN_BOX_PX:
            continue
        x0, y0 = max(0, x - RING_PX), max(0, y - RING_PX)
        x1, y1 = min(w, x + bw + RING_PX), min(h, y + bh + RING_PX)
        ring = np.ones((y1 - y0, x1 - x0), bool)
        ring[y - y0:y - y0 + bh, x - x0:x - x0 + bw] = False
        ring_std = float(np.median(std[y0:y1, x0:x1][ring])) if ring.any() else 0.0
        on_mark = mask[y:y + bh, x:x + bw] > 0
        med_share = float(med_edges[y:y + bh, x:x + bw][on_mark].mean()) if on_mark.any() else 0.0
        if DEBUG or (ring_std >= MIN_RING_STD and med_share >= MIN_MEDIAN_EDGE):
            marks.append((x, y, bw, bh, px, round(ring_std, 1), round(med_share, 2)))
    return sorted(marks, key=lambda m: -m[4])


def check_source_marks(video_path):
    """
    {"passed": True|False|None, "reason", "marks"}. None when the video cannot be sampled:
    a source that was not checked is never reported as clean.
    """
    if not video_path or not os.path.isfile(video_path):
        return {"passed": None, "reason": "SOURCE_NOT_FOUND", "marks": []}
    marks = find_marks_in_frames(_sample_gray(video_path))
    if marks is None:
        return {"passed": None, "reason": "TOO_FEW_FRAMES", "marks": []}
    if marks:
        x, y, bw, bh = marks[0][:4]
        return {"passed": False, "marks": marks,
                "reason": f"CHANNEL_MARK ({len(marks)} fixed mark(s), largest {bw}x{bh} at {x},{y} on a 640-wide frame)"}
    return {"passed": True, "reason": "NO_FIXED_MARK", "marks": []}


def _cache_path():
    import lion_paths
    return os.path.join(lion_paths.data_root(), CACHE_FILE)


def check_source_marks_cached(video_path):
    """check_source_marks, measured once per source and remembered. Only results that ran are kept."""
    import json
    from clip_ledger import source_key
    key = source_key(video_path)
    path = _cache_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    if key in cache and cache[key].get("passed") is not None:
        return cache[key]
    res = check_source_marks(video_path)
    if res.get("passed") is not None:
        cache[key] = {"passed": res["passed"], "reason": res["reason"], "marks": [list(m) for m in res["marks"][:5]]}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=1)
            os.replace(tmp, path)
        except Exception:
            pass
    return res


def marked_source_keys():
    """Source keys measured as carrying a channel mark. Unmeasured sources are not in it."""
    import json
    try:
        with open(_cache_path(), "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        return set()
    return {k for k, v in cache.items() if isinstance(v, dict) and v.get("passed") is False}


def measure_sources(paths, max_seconds=180.0, log=None):
    """
    Measures sources not measured yet, oldest first, within a time budget, so a job knows which
    bank footage carries a channel mark before it plans. Returns how many were measured.
    """
    import json
    import time
    from clip_ledger import source_key
    try:
        with open(_cache_path(), "r", encoding="utf-8") as f:
            done = {k for k, v in json.load(f).items() if isinstance(v, dict) and v.get("passed") is not None}
    except Exception:
        done = set()
    t0, measured, seen = time.time(), 0, set()
    for p in paths:
        key = source_key(p)
        if not p or key in done or key in seen or not os.path.isfile(p):
            continue
        seen.add(key)
        if time.time() - t0 > max_seconds:
            break
        res = check_source_marks_cached(p)
        measured += 1
        if log and res.get("passed") is False:
            log(f"  [MARK CHECK] {os.path.basename(p)} carries a channel mark; its clips are left out")
    return measured
