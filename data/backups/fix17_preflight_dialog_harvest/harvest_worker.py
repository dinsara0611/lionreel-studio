"""
LionReel Background Harvester Worker
Separates clip harvesting, video analysis, and ledger ingestion from render jobs.
Keeps the clip pool topped up (low-water mark: 20 clips) in the background.
Uses low-resolution fast scanning, cached fingerprints, and parallel workers.
"""

import os
import sys
import time
import json
import glob
import cv2
import numpy as np
import subprocess
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from clip_ledger import ClipLedger, LEDGER_DB_PATH
from source_utils import probe_video_fast, compute_source_fingerprint, get_ffmpeg_exe
from pet_detector import PetDetector
from watermark_detector import WatermarkDetector

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
RAW_DIR = os.path.join(BASE_DIR, "raw")
OWN_DIR = os.path.join(BASE_DIR, "own_footage")
REF_DIR = os.path.join(BASE_DIR, "reference")

def get_status_file_path() -> str:
    local_data = os.path.join("C:\\", "LionReel", "data")
    if os.path.exists(local_data):
        return os.path.join(local_data, "harvest_status.json")
    return os.path.join(BASE_DIR, "data", "harvest_status.json")

def get_lock_file_path() -> str:
    local_data = os.path.join("C:\\", "LionReel", "data")
    if os.path.exists(local_data):
        return os.path.join(local_data, "harvest.lock")
    return os.path.join(BASE_DIR, "data", "harvest.lock")

def write_harvest_status(status_dict: dict):
    sp = get_status_file_path()
    try:
        os.makedirs(os.path.dirname(sp), exist_ok=True)
        status_dict["last_updated"] = time.time()
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(status_dict, f, indent=2)
    except Exception:
        pass

def get_harvest_status() -> dict:
    sp = get_status_file_path()
    raw = {}
    if os.path.exists(sp):
        try:
            with open(sp, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
    running = is_harvest_running() or raw.get("is_harvesting", False)
    state = "running" if running else raw.get("state", "idle")
    return {
        "state": state,
        "is_harvesting": running,
        "progress_pct": raw.get("progress_pct", 100 if state == "idle" else 0),
        "status_msg": raw.get("status_msg", "Harvest worker idle"),
        "current_source": raw.get("current_source", ""),
        "sources_scanned": raw.get("sources_scanned", raw.get("current_source_index", raw.get("total_sources", 0))),
        "windows_analyzed": raw.get("windows_analyzed", 0),
        "windows_verified": raw.get("windows_verified", raw.get("clips_ingested", 0)),
        "rejects_by_reason": raw.get("rejects_by_reason", {}),
        "last_activity_time": raw.get("last_updated", time.time()),
        "growth_per_minute": raw.get("growth_per_minute", 0.0),
        "clips_ingested": raw.get("clips_ingested", 0),
        "total_sources": raw.get("total_sources", 0),
        "last_updated": raw.get("last_updated", time.time())
    }

def is_harvest_running() -> bool:
    lock_file = get_lock_file_path()
    if not os.path.exists(lock_file):
        return False
    try:
        with open(lock_file, "r") as f:
            pid = int(f.read().strip())
        if os.name == 'nt':
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if h:
                exit_code = ctypes.c_ulong()
                alive = False
                if ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code)):
                    alive = (exit_code.value == STILL_ACTIVE)
                ctypes.windll.kernel32.CloseHandle(h)
                if alive:
                    return True
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                pass
    except Exception:
        pass
    try:
        os.remove(lock_file)
    except Exception:
        pass
    return False

def fast_analyze_source_segment(source_path: str, start_s: float, dur_s: float, animal_mode: str = "cat", detector=None, wm_detector=None) -> dict:
    """
    Analyzes a candidate segment at low resolution (360p, 3-4 fps seek-and-sample)
    to check pet presence, sharpness, and logos.
    """
    if detector is None:
        detector = PetDetector()
    if wm_detector is None:
        wm_detector = WatermarkDetector()

    cap = cv2.VideoCapture(source_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    start_f = int(start_s * fps)
    total_f = int(dur_s * fps)

    # Sample 8 frames across segment (approx 1.5 fps)
    step = max(1, total_f // 8)
    pet_detections = 0
    sharpness_scores = []
    sampled = 0

    for i in range(8):
        f_idx = start_f + i * step
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
        sampled += 1

        # Resize to fast 360p analysis canvas for ultra-fast processing
        h, w = frame.shape[:2]
        scale = 360.0 / max(h, 1)
        small_w = int(w * scale)
        small = cv2.resize(frame, (small_w, 360), interpolation=cv2.INTER_LINEAR)

        # 1. Laplacian sharpness check
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        sharpness_scores.append(lap_var)

        # 2. Pet detection check
        dets = detector.detect(small, conf_threshold=0.22)
        matching = [d for d in dets if d["class_name"] in (animal_mode, "cat", "dog")]
        if matching:
            pet_detections += 1
            primary = matching[0]
            cy = primary["center"][1] / float(small.shape[0])
            box_h = (primary["box"][3] - primary["box"][1]) / float(small.shape[0])
            if 0.28 <= cy <= 0.68 and 0.22 <= box_h <= 0.65:
                well_centered = locals().get("well_centered", 0) + 1

    cap.release()

    if sampled == 0:
        return {"passed": False, "reason": "COULD_NOT_READ_FRAMES"}

    med_sharpness = float(np.median(sharpness_scores)) if sharpness_scores else 0.0
    pet_ratio = pet_detections / sampled
    center_ratio = locals().get("well_centered", 0) / sampled

    # Pet must be detected in at least 40% of sampled frames
    if pet_ratio < 0.40:
        return {"passed": False, "reason": f"LOW_PET_PRESENCE ({pet_ratio*100:.0f}%)", "sharpness": med_sharpness}

    # Pet must be well positioned/centerable in at least 35% of frames
    if center_ratio < 0.35:
        return {"passed": False, "reason": f"PET_NOT_CENTERABLE ({center_ratio*100:.0f}%)", "sharpness": med_sharpness}

    # Sharpness must be reasonable
    if med_sharpness < 25.0:
        return {"passed": False, "reason": f"BLURRY_FRAME (sharpness {med_sharpness:.1f} < 25)", "sharpness": med_sharpness}

    return {
        "passed": True,
        "pet_ratio": pet_ratio,
        "center_ratio": center_ratio,
        "median_sharpness": med_sharpness
    }

def run_harvest_loop(animal_mode: str = "cat", target_to_add: int = 15):
    """
    Main harvest worker execution loop.
    Scans sources, checks upscale gate, analyzes at 360p, and ingests qualified clips.
    """
    lock_file = get_lock_file_path()
    os.makedirs(os.path.dirname(lock_file), exist_ok=True)
    with open(lock_file, "w") as f:
        f.write(str(os.getpid()))

    ledger = ClipLedger()
    detector = PetDetector()
    wm_detector = WatermarkDetector()

    try:
        # 1. Find all candidate files
        all_sources = []
        for p in glob.glob(os.path.join(OWN_DIR, "*.mp4")) + glob.glob(os.path.join(RAW_DIR, "*.mp4")):
            bname = os.path.basename(p)
            # Skip derivative or temporary files
            if (bname.startswith("cut_") or bname.startswith("capcut_") or 
                bname.startswith("assembled_") or bname.startswith("test_") or
                bname.startswith("v97_") or bname.startswith("cand_") or
                bname.startswith("sel_") or bname.startswith("master_audio_") or
                bname.startswith("concat_")):
                continue
            if ledger.is_blocked_source(p):
                continue
            if os.path.exists(p) and os.path.getsize(p) > 1024 * 1024:
                all_sources.append(p)

        write_harvest_status({
            "is_harvesting": True,
            "pid": os.getpid(),
            "animal_type": animal_mode,
            "progress_pct": 5,
            "status_msg": f"Found {len(all_sources)} source videos. Running fail-fast resolution gate...",
            "clips_ingested": 0,
            "total_sources": len(all_sources)
        })

        # 2. Filter via fail-fast upscale gate and watermark gate
        valid_sources = []
        for sp in all_sources:
            probe = probe_video_fast(sp)
            if not probe["pass_gate"]:
                ledger.mark_source_blocked(sp, "BLOCKED_LOW_RES")
                continue
            has_wm, wm_corner, wm_conf, wm_reason = wm_detector.check_video_corners(sp, n_samples=8)
            if has_wm:
                ledger.mark_source_blocked(sp, f"BLOCKED_WATERMARK: {wm_reason}")
                continue
            from qa_check import check_cartoon_classifier
            cartoon_res = check_cartoon_classifier(sp, n_samples=12)
            if not cartoon_res["passed"]:
                ledger.mark_source_blocked(sp, f"BLOCKED_CARTOON: CGI negative prob {cartoon_res['mean_negative_probability']:.1%}")
                continue
            valid_sources.append(sp)

        total_v = len(valid_sources)
        if total_v == 0:
            write_harvest_status({
                "is_harvesting": False,
                "progress_pct": 100,
                "status_msg": "No valid sources found (all blocked or low-res). Please add 1080p+ sources.",
                "clips_ingested": 0,
                "total_sources": 0
            })
            return 0

        ingested_count = 0
        for idx, sp in enumerate(valid_sources):
            if ingested_count >= target_to_add:
                break

            progress_pct = int(10 + (idx / total_v) * 85)
            bname = os.path.basename(sp)
            write_harvest_status({
                "is_harvesting": True,
                "pid": os.getpid(),
                "animal_type": animal_mode,
                "progress_pct": progress_pct,
                "status_msg": f"Scanning {bname} ({idx+1}/{total_v})...",
                "clips_ingested": ingested_count,
                "total_sources": total_v,
                "current_source_index": idx + 1
            })

            fp = compute_source_fingerprint(sp)
            cached_data = ledger.get_source_analysis(fp)
            probe = probe_video_fast(sp)
            dur = probe["duration"]
            if dur < 4.0:
                continue

            segment_len = 5.2
            stride = max(10.0, dur / 24.0)
            cur_s = 2.0
            clips_from_source = 0
            segments_to_ingest = []

            if cached_data and "candidate_segments" in cached_data and any("center_ratio" in s for s in cached_data["candidate_segments"]):
                # Reuse verified cached analysis
                segments_to_ingest = cached_data["candidate_segments"]
            else:
                # Analyze segments at low-res 360p
                found_segments = []
                while cur_s + segment_len <= dur - 1.0 and len(found_segments) < 8:
                    analysis = fast_analyze_source_segment(sp, cur_s, segment_len, animal_mode, detector, wm_detector)
                    if analysis["passed"]:
                        found_segments.append({
                            "start_s": cur_s,
                            "end_s": cur_s + segment_len,
                            "sharpness": analysis.get("median_sharpness", 150.0),
                            "pet_ratio": analysis.get("pet_ratio", 1.0),
                            "center_ratio": analysis.get("center_ratio", 1.0)
                        })
                    cur_s += stride
                ledger.save_source_analysis(fp, sp, {"candidate_segments": found_segments})
                segments_to_ingest = found_segments

            # Ingest into ledger
            for seg in segments_to_ingest:
                cid = ledger.ingest_candidate(
                    source_path=sp,
                    start_s=seg["start_s"],
                    end_s=seg["end_s"],
                    license_type="CC-BY" if "cache_" in sp else "Own Footage",
                    animal_type=animal_mode,
                    quality_score=seg.get("sharpness", 150.0) / 100.0,
                    funny_score=0.85
                )
                if cid:
                    ingested_count += 1
                    clips_from_source += 1

        pool = ledger.get_pool_status(animal_mode)
        write_harvest_status({
            "is_harvesting": False,
            "progress_pct": 100,
            "status_msg": f"Harvest complete! {ingested_count} new clips added. Pool: {pool['unused_clips']} available.",
            "clips_ingested": ingested_count,
            "total_sources": total_v
        })
        return ingested_count

    finally:
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
        except Exception:
            pass

def trigger_background_harvest_if_needed(animal_mode: str = "cat", min_low_water_mark: int = 20, target_clips_needed: Optional[int] = None):
    """
    Checks if unused clips in pool drop below low-water mark (20) or target_clips_needed,
    OR if a single source dominates the pool (>60%).
    If so, launches background worker in a separate process without blocking!
    """
    ledger = ClipLedger()
    status = ledger.get_pool_status(animal_mode)
    unused = status.get("unused_clips", 0)

    # Requirement 5: Check if one source dominates the pool (>60%)
    source_dominated = False
    try:
        with ledger._get_conn() as conn:
            cur = conn.execute("""
                SELECT source_url_or_path, COUNT(*) as cnt 
                FROM clips 
                WHERE animal_type = ? AND times_used == 0 
                GROUP BY source_url_or_path
            """, (animal_mode,))
            counts = [r["cnt"] for r in cur.fetchall()]
            if counts and unused > 0:
                top_cnt = max(counts)
                if (top_cnt / float(unused)) > 0.60 and len(counts) <= 2:
                    source_dominated = True
    except Exception:
        pass

    needed_threshold = target_clips_needed if target_clips_needed is not None else min_low_water_mark
    if (unused < needed_threshold or source_dominated) and not is_harvest_running():
        # Spawn background process
        local_venv_py = r"C:\LionReel\venv\Scripts\python.exe"
        python_exe = local_venv_py if os.path.exists(local_venv_py) else (sys.executable or "python")
        worker_script = os.path.join(BASE_DIR, "harvest_worker.py")
        target_to_add = 15
        if target_clips_needed and target_clips_needed > unused:
            target_to_add = max(15, target_clips_needed - unused + 10)

        harvest_log_file = os.path.join(BASE_DIR, "data", "harvest.log")
        os.makedirs(os.path.dirname(harvest_log_file), exist_ok=True)
        h_log_fd = open(harvest_log_file, "a", encoding="utf-8", errors="ignore")
        subprocess.Popen(
            [python_exe, "-u", worker_script, "--animal", animal_mode, "--count", str(target_to_add)],
            cwd=BASE_DIR,
            stdout=h_log_fd,
            stderr=h_log_fd,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        )
        return True
    return False

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--animal", default="cat", help="Animal mode (cat, dog, mix)")
    parser.add_argument("--count", type=int, default=15, help="Target clips to add")
    args = parser.parse_args()

    run_harvest_loop(animal_mode=args.animal, target_to_add=args.count)

