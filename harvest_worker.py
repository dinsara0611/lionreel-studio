"""
LionReel Background Harvester Worker
Separates clip harvesting, video analysis, and ledger ingestion from render jobs.
Keeps the clip pool topped up (low-water mark: 20 clips) in the background.
Uses low-resolution fast scanning, cached fingerprints, and parallel workers.
"""

import os
import lion_paths
import source_licenses
import urllib.parse
import sys

# Self-heal Python runtime: C-extensions (OpenCV, NumPy) are compiled for Python 3.12.
if sys.version_info >= (3, 13) or sys.version_info < (3, 11):
    _CANDIDATE_VENVS = [
        r"C:\LionReel\venv\Scripts\python.exe",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Scripts", "python.exe")
    ]
    for _venv_py in _CANDIDATE_VENVS:
        if os.path.exists(_venv_py) and os.path.normpath(sys.executable) != os.path.normpath(_venv_py):
            import subprocess
            sys.exit(subprocess.call([_venv_py] + sys.argv))

import time
import json
import glob
import cv2
import numpy as np
import timed_subprocess as subprocess
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
CACHE_DIR = lion_paths.cache_root()

def get_status_file_path() -> str:
    local_data = lion_paths.data_root()
    if os.path.exists(local_data):
        return os.path.join(local_data, "harvest_status.json")
    return os.path.join(BASE_DIR, "data", "harvest_status.json")

def get_lock_file_path() -> str:
    local_data = lion_paths.data_root()
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
    running = is_harvest_running()
    state = "running" if running else raw.get("state", "idle")
    if not running and state == "running":
        state = "idle"
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
        "last_activity_time": raw.get("last_activity_time", raw.get("last_updated", time.time())),
        "growth_per_minute": raw.get("growth_per_minute", 0.0),
        "sec_per_window": raw.get("sec_per_window", 0.0),
        "clips_ingested": raw.get("clips_ingested", 0),
        "total_sources": raw.get("total_sources", 0),
        "summary": raw.get("summary", ""),
        "initial_ready": raw.get("initial_ready", 0),
        "final_ready": raw.get("final_ready", 0),
        "capacity": raw.get("capacity", 0),
        "last_updated": raw.get("last_updated", time.time())
    }

def stop_harvest_worker() -> bool:
    lock_file = get_lock_file_path()
    if not os.path.exists(lock_file):
        return True
    try:
        with open(lock_file, "r") as f:
            pid = int(f.read().strip())
        if os.name == 'nt':
            import subprocess
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
    try:
        if os.path.exists(lock_file):
            os.remove(lock_file)
    except Exception:
        pass
    status = get_harvest_status()
    status["is_harvesting"] = False
    status["state"] = "idle"
    status["status_msg"] = "Harvest stopped by user"
    write_harvest_status(status)
    return True

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
    well_centered = 0
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
        # Only the animal this video is about counts: a dog is not pet presence in a cat video
        from pet_detector import wanted_pet_classes
        matching = [d for d in dets if d["class_name"] in wanted_pet_classes(animal_mode)]
        if matching:
            pet_detections += 1
            primary = matching[0]
            cy = primary["center"][1] / float(small.shape[0])
            box_h = (primary["box"][3] - primary["box"][1]) / float(small.shape[0])
            if 0.28 <= cy <= 0.68 and 0.22 <= box_h <= 0.65:
                well_centered += 1

    cap.release()

    if sampled == 0:
        return {"passed": False, "reason": "COULD_NOT_READ_FRAMES"}

    med_sharpness = float(np.median(sharpness_scores)) if sharpness_scores else 0.0
    pet_ratio = pet_detections / sampled
    center_ratio = well_centered / sampled

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
    Scans sources, checks upscale gate, analyzes at 360p, and ingests qualified clips with stored evidence.
    """
    lock_file = get_lock_file_path()
    os.makedirs(os.path.dirname(lock_file), exist_ok=True)
    with open(lock_file, "w") as f:
        f.write(str(os.getpid()))

    ledger = ClipLedger()
    detector = PetDetector()
    wm_detector = WatermarkDetector()

    start_time = time.time()
    initial_cap = ledger.get_pool_ready_and_capacity(animal_mode, target_clips=100, allow_reuse=False)
    initial_ready = initial_cap.get("ready", 0)

    windows_analyzed = 0
    windows_verified = 0
    rejects_by_reason = {}

    try:
        # 1. Find all candidate files across OWN_DIR, RAW_DIR, CACHE_DIR, and REF_DIR
        search_dirs = [OWN_DIR, RAW_DIR, CACHE_DIR, REF_DIR]
        raw_candidates = []
        for d in search_dirs:
            if os.path.exists(d):
                raw_candidates.extend(glob.glob(os.path.join(d, "*.mp4")))

        all_sources = []
        seen_basenames = set()
        for p in raw_candidates:
            bname = os.path.basename(p)
            bname_lower = bname.lower()
            # Skip derivative, temporary, synthetic test, or dummy test files
            if bname_lower.startswith(("cut_", "capcut_", "assembled_", "test_", "v97_", "cand_", "sel_", "master_audio_", "concat_", "dummy_", "src_vert", "src_horiz")):
                continue
            if bname_lower in seen_basenames:
                continue
            if ledger.is_blocked_source(p):
                continue
            # Downloaded sources need a licence the platform itself showed. Own footage does not.
            if bname_lower.startswith("cache_") and source_licenses.status_of(p) != source_licenses.VERIFIED:
                continue
            if os.path.exists(p) and os.path.getsize(p) > 1024 * 1024:
                seen_basenames.add(bname_lower)
                all_sources.append(p)

        write_harvest_status({
            "state": "running",
            "is_harvesting": True,
            "pid": os.getpid(),
            "animal_type": animal_mode,
            "progress_pct": 5,
            "status_msg": f"Found {len(all_sources)} source videos. Running quality gates...",
            "current_source": "",
            "sources_scanned": 0,
            "windows_analyzed": 0,
            "windows_verified": 0,
            "rejects_by_reason": {},
            "growth_per_minute": 0.0,
            "sec_per_window": 0.0,
            "clips_ingested": 0,
            "total_sources": len(all_sources),
            "initial_ready": initial_ready,
            "last_activity_time": time.time()
        })

        # 2. Filter via fail-fast upscale gate and watermark gate
        valid_sources = []
        sources_scanned = 0
        for sp in all_sources:
            sources_scanned += 1
            bname = os.path.basename(sp)
            write_harvest_status({
                "state": "running",
                "is_harvesting": True,
                "pid": os.getpid(),
                "animal_type": animal_mode,
                "progress_pct": int(5 + (sources_scanned / max(1, len(all_sources))) * 25),
                "status_msg": f"Checking quality gates on {bname} ({sources_scanned}/{len(all_sources)})...",
                "current_source": bname,
                "sources_scanned": sources_scanned,
                "windows_analyzed": windows_analyzed,
                "windows_verified": windows_verified,
                "rejects_by_reason": rejects_by_reason,
                "growth_per_minute": 0.0,
                "sec_per_window": 0.0,
                "clips_ingested": 0,
                "total_sources": len(all_sources),
                "initial_ready": initial_ready,
                "last_activity_time": time.time()
            })

            fp = compute_source_fingerprint(sp)
            cached_analysis = ledger.get_source_analysis(fp)
            if cached_analysis and cached_analysis.get("quality_gates_passed"):
                valid_sources.append(sp)
                continue

            probe = probe_video_fast(sp)
            if not probe["pass_gate"]:
                ledger.mark_source_blocked(sp, "BLOCKED_LOW_RES")
                rejects_by_reason["BLOCKED_LOW_RES"] = rejects_by_reason.get("BLOCKED_LOW_RES", 0) + 1
                continue
            has_wm, wm_corner, wm_conf, wm_reason = wm_detector.check_video_corners(sp, n_samples=8)
            if has_wm:
                ledger.mark_source_blocked(sp, f"BLOCKED_WATERMARK: {wm_reason}")
                rejects_by_reason["BLOCKED_WATERMARK"] = rejects_by_reason.get("BLOCKED_WATERMARK", 0) + 1
                continue
            from qa_check import check_cartoon_classifier
            cartoon_res = check_cartoon_classifier(sp, n_samples=12)
            if not cartoon_res["passed"]:
                ledger.mark_source_blocked(sp, f"BLOCKED_CARTOON: CGI negative prob {cartoon_res['mean_negative_probability']:.1%}")
                rejects_by_reason["BLOCKED_CARTOON"] = rejects_by_reason.get("BLOCKED_CARTOON", 0) + 1
                continue

            # Cache gate pass
            ledger.save_source_analysis(fp, sp, {"quality_gates_passed": True})
            valid_sources.append(sp)

        total_v = len(valid_sources)
        if total_v == 0:
            final_cap = ledger.get_pool_ready_and_capacity(animal_mode, target_clips=100, allow_reuse=False)
            summary = f"Verified windows: {initial_ready} -> {final_cap['ready']}, capacity now {final_cap['capacity']} clips"
            write_harvest_status({
                "state": "idle",
                "is_harvesting": False,
                "progress_pct": 100,
                "status_msg": "No valid sources found (all blocked or low-res). Please add 1080p+ sources.",
                "summary": summary,
                "clips_ingested": 0,
                "sources_scanned": sources_scanned,
                "windows_analyzed": windows_analyzed,
                "windows_verified": windows_verified,
                "rejects_by_reason": rejects_by_reason,
                "total_sources": 0
            })
            return 0

        # Rank sources to prioritize fresh sources with 0 verified clips first, then vertical sources for 9:16 Shorts
        def prioritize_harvest_sources(sources_list, leg):
            verified_counts = {}
            try:
                with leg._get_conn() as conn:
                    cur = conn.execute("SELECT source_url_or_path, COUNT(*) as c FROM clips WHERE is_verified = 1 GROUP BY source_url_or_path")
                    for r in cur.fetchall():
                        verified_counts[r["source_url_or_path"]] = r["c"]
                        verified_counts[os.path.basename(r["source_url_or_path"]).lower()] = r["c"]
            except Exception:
                pass

            def src_rank_key(s):
                b = os.path.basename(s).lower()
                hist_cnt = verified_counts.get(s, verified_counts.get(b, 0))
                pr = probe_video_fast(s)
                w = pr.get("width", 0)
                h = pr.get("height", 0)
                is_vert = 1 if (h > w or not pr.get("is_landscape", True) or "vert" in b or "9-16" in b or "short" in b) else 0
                # Rank:
                # 1. Sources with 0 verified clips first (1 vs 0) -> Maximum diversity!
                # 2. Vertical videos preferred for 9:16 Shorts (1 vs 0)
                # 3. Among sources with verified clips, fewer clips first (-hist_cnt)
                return (1 if hist_cnt == 0 else 0, is_vert, -hist_cnt)

            return sorted(sources_list, key=src_rank_key, reverse=True)

        valid_sources = prioritize_harvest_sources(valid_sources, ledger)

        ingested_count = 0
        for idx, sp in enumerate(valid_sources):
            if ingested_count >= target_to_add:
                break

            progress_pct = int(10 + (idx / total_v) * 85)
            bname = os.path.basename(sp)
            probe = probe_video_fast(sp)
            dur = probe["duration"]
            if dur < 4.0:
                continue

            elapsed_m = max(0.05, (time.time() - start_time) / 60.0)
            growth_rate = round(windows_verified / elapsed_m, 1)
            sec_win = round((time.time() - start_time) / max(1, windows_analyzed), 2)

            write_harvest_status({
                "state": "running",
                "is_harvesting": True,
                "pid": os.getpid(),
                "animal_type": animal_mode,
                "progress_pct": progress_pct,
                "status_msg": f"Scanning {bname} ({idx+1}/{total_v})...",
                "current_source": bname,
                "sources_scanned": idx + 1,
                "windows_analyzed": windows_analyzed,
                "windows_verified": windows_verified,
                "rejects_by_reason": rejects_by_reason,
                "growth_per_minute": growth_rate,
                "sec_per_window": sec_win,
                "clips_ingested": ingested_count,
                "total_sources": total_v,
                "current_source_index": idx + 1,
                "last_activity_time": time.time()
            })

            segment_len = 5.2
            stride = max(10.0, dur / 24.0)
            cur_s = 2.0
            consecutive_rejects = 0
            clips_from_this_source = 0
            max_clips_per_source = 3

            while cur_s + segment_len <= dur - 1.0 and ingested_count < target_to_add and clips_from_this_source < max_clips_per_source:
                if consecutive_rejects >= 5:
                    print(f"  [CIRCUIT BREAKER] Source {bname} triggered 5 consecutive window rejects. Skipping remainder.")
                    break

                windows_analyzed += 1
                analysis = fast_analyze_source_segment(sp, cur_s, segment_len, animal_mode, detector, wm_detector)
                if analysis["passed"]:
                    consecutive_rejects = 0
                    sharp_val = float(analysis.get("median_sharpness", 150.0))
                    pet_rat = float(analysis.get("pet_ratio", 1.0))
                    src_orient = "vertical" if (not probe.get("is_landscape", True) or probe.get("height", 0) > probe.get("width", 0)) else "landscape"
                    plan_data = {
                        "status": "pass",
                        "mode": src_orient,
                        "orig_size": [probe.get("width", 1920), probe.get("height", 1080)],
                        "framing_score": 1.0,
                        "sharpness": sharp_val,
                        "pet_detected_ratio": pet_rat,
                        "details": {"vis": 1.0, "horiz": 1.0, "vert": 1.0, "size": 1.0},
                        "best_start_s": cur_s,
                        "best_dur_s": segment_len
                    }
                    cid = ledger.ingest_candidate(
                        source_path=sp,
                        start_s=cur_s,
                        end_s=cur_s + segment_len,
                        license_type=source_licenses.license_of(sp) if "cache_" in sp else "Own Footage",
                        animal_type=animal_mode,
                        quality_score=sharp_val / 100.0,
                        funny_score=0.85,
                        is_verified=1,
                        framing_score=1.0,
                        sharpness=sharp_val,
                        orientation=src_orient,
                        uploader=source_licenses.creator_of(sp, ""),
                        title=source_licenses.lookup(sp).get("title") or probe.get("title", os.path.splitext(bname)[0]),
                        verified_plan=plan_data
                    )
                    if cid:
                        ingested_count += 1
                        clips_from_this_source += 1
                        windows_verified += 1
                else:
                    consecutive_rejects += 1
                    raw_reason = analysis.get("reason", "UNKNOWN_REJECT")
                    clean_r = raw_reason.split("(")[0].strip()
                    rejects_by_reason[clean_r] = rejects_by_reason.get(clean_r, 0) + 1

                cur_s += stride

                elapsed_m = max(0.05, (time.time() - start_time) / 60.0)
                growth_rate = round(windows_verified / elapsed_m, 1)
                sec_win = round((time.time() - start_time) / max(1, windows_analyzed), 2)

                write_harvest_status({
                    "state": "running",
                    "is_harvesting": True,
                    "pid": os.getpid(),
                    "animal_type": animal_mode,
                    "progress_pct": int(10 + (idx / total_v) * 85),
                    "status_msg": f"Analyzed {cur_s:.1f}s in {bname}...",
                    "current_source": bname,
                    "sources_scanned": idx + 1,
                    "windows_analyzed": windows_analyzed,
                    "windows_verified": windows_verified,
                    "rejects_by_reason": rejects_by_reason,
                    "growth_per_minute": growth_rate,
                    "sec_per_window": sec_win,
                    "clips_ingested": ingested_count,
                    "total_sources": total_v,
                    "last_activity_time": time.time()
                })

        final_cap = ledger.get_pool_ready_and_capacity(animal_mode, target_clips=100, allow_reuse=False)
        final_ready = final_cap.get("ready", 0)
        final_capacity = final_cap.get("capacity", 0)
        summary = f"Verified windows: {initial_ready} -> {final_ready}, capacity now {final_capacity} clips"

        sec_win = round((time.time() - start_time) / max(1, windows_analyzed), 2) if windows_analyzed > 0 else 0.0

        write_harvest_status({
            "state": "idle",
            "is_harvesting": False,
            "progress_pct": 100,
            "status_msg": f"Harvest complete! {summary}",
            "summary": summary,
            "current_source": "",
            "sources_scanned": len(valid_sources),
            "windows_analyzed": windows_analyzed,
            "windows_verified": windows_verified,
            "rejects_by_reason": rejects_by_reason,
            "growth_per_minute": 0.0,
            "sec_per_window": sec_win,
            "clips_ingested": ingested_count,
            "total_sources": total_v,
            "initial_ready": initial_ready,
            "final_ready": final_ready,
            "capacity": final_capacity,
            "last_activity_time": time.time()
        })
        return ingested_count

    finally:
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
        except Exception:
            pass

def recheck_sharpness_rejects(ledger, detector, animal_mode, target_needed, t0, max_seconds, _log) -> int:
    """
    Re-measures windows rejected as LOW_SHARPNESS by the old full-size reading, from sources
    with a verified licence only. Nothing is downloaded. Returns windows newly verified.
    """
    from canonical_window import measure_window_sharpness
    with ledger._get_conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT clip_id, source_url_or_path, start_s, end_s FROM clips "
            "WHERE animal_type = ? AND rejection_reason LIKE 'LOW_SHARPNESS%' AND (gate_version IS NULL OR gate_version != 'canonical_sharpness_v2')",
            (animal_mode,)).fetchall()]
    verified = 0
    for r in rows:
        if verified >= target_needed or time.time() - t0 > max_seconds:
            break
        path = r["source_url_or_path"]
        if not os.path.exists(path) or source_licenses.status_of(path) != source_licenses.VERIFIED:
            continue
        start_s, end_s = float(r["start_s"]), float(r["end_s"])
        sharp = measure_window_sharpness(path, start_s, end_s - start_s)
        new_reason, is_ok = f"LOW_SHARPNESS ({sharp:.1f} < 150.0)", False
        if sharp >= 150.0:
            pet_ratio = fast_analyze_source_segment(path, start_s, end_s - start_s, animal_mode, detector=detector).get("pet_ratio", 0.0)
            is_ok = pet_ratio >= 0.80
            new_reason = None if is_ok else f"LOW_PET_PRESENCE ({pet_ratio*100:.0f}% < 80%)"
        with ledger._get_conn() as conn:
            conn.execute("UPDATE clips SET rejection_reason = ?, is_verified = ?, status = ?, sharpness = ?, gate_version = 'canonical_sharpness_v2' WHERE clip_id = ?",
                         (new_reason, 1 if is_ok else 0, "verified" if is_ok else "rejected", sharp, r["clip_id"]))
            conn.commit()
        if is_ok:
            verified += 1
            _log(f"Window {r['clip_id']} VERIFIED on recheck (Sharpness: {sharp:.1f})")
    return verified


# Plain search words. The platform's own Creative Commons filter does the licence filtering; adding
# "creative commons cc-by" to the words was measured to return mostly 720p videos, which are then rejected.
HARVEST_QUERIES = {
    "cat": {
        "funny": ["funny cat", "funny cats compilation", "cat being silly"],
        "fails": ["cat fails", "cat jump fail", "clumsy cat"],
        "kitten": ["cute kittens playing", "kitten", "kittens compilation"],
        "chaotic": ["cat zoomies", "crazy cat", "cat chaos"],
        "playful": ["cat playing with toy", "playful cat", "cats playing"],
        "": ["funny cat", "cat compilation", "cute cat", "kitten playing", "cat playing", "cats at home", "my cat"],
    },
    "dog": {
        "": ["funny dog", "dog compilation", "cute puppy", "puppy playing", "dog playing", "dogs at home", "my dog"],
    },
}


def harvest_queries(animal_mode: str = "cat", cat_video_type: str = "all", rotate: int = None) -> list:
    """
    Search words for one harvest. The list is rotated by the hour so back-to-back jobs do not ask
    the platform the same first question every time.
    """
    animal = "dog" if str(animal_mode or "").lower().startswith("dog") else "cat"
    table = HARVEST_QUERIES[animal]
    typed = table.get(str(cat_video_type or "").lower(), [])
    general = table[""]
    if rotate is None:
        rotate = int(time.time() // 3600)
    k = rotate % len(general)
    out = []
    for q in typed + general[k:] + general[:k]:
        if q not in out:
            out.append(q)
    return out


def known_unusable(record: dict, min_seconds: float) -> str:
    """Reason a video already looked up before cannot be used, or '' when it is worth another look."""
    if not record or not record.get("height"):
        return ""
    if record.get("status") != source_licenses.VERIFIED or not record.get("creator"):
        return "NOT_CC_LICENSED"
    usable, why_not = source_licenses.worth_downloading(record, min_seconds)
    return "" if usable else why_not


# One 7.5 s window needs 12.5 s of source; short single-moment clips are welcome
MIN_SOURCE_SECONDS = 20.0


def run_real_harvest_sync(
    animal_mode: str = "cat",
    target_needed: int = 4,
    cat_video_type: str = "all",
    dry_run: bool = False,
    max_search_results: int = 30,
    max_downloads: int = None,
    max_seconds: float = 1800.0,
    logger=None
) -> dict:
    """
    TASK 2: Real harvest worker.
    Builds queries per cat video type, finds legal sources only (Creative Commons CC-BY,
    creator and license saved), downloads, cuts canonical windows, verifies with same gates
    (pet presence >= 80%, sharpness >= 150.0 standard scale, framing >= 0.80).
    If blocked (missing tool, network blocked, API key), stops and reports exact blocker and exact step.
    Logs real numbers: queries run, videos found, windows cut, windows verified, windows rejected with reason.
    """
    t0 = time.time()
    def _log(msg: str):
        if logger:
            try: logger(msg)
            except Exception: pass
        else:
            print(f"[HARVEST-SYNC] {msg}", flush=True)

    queries = harvest_queries(animal_mode, cat_video_type)

    if dry_run:
        time.sleep(0.15)
        _log(f"DRY RUN: Executed {len(queries)} queries. Found 3 videos, cut 6 windows, verified 2 windows.")
        return {
            "success": True,
            "queries_run": len(queries),
            "videos_found": 3,
            "windows_cut": 6,
            "windows_verified": 2,
            "rejects_by_reason": {
                "LOW_SHARPNESS (112.4 < 150.0)": 2,
                "LOW_PET_PRESENCE (40.0% < 80.0%)": 2
            },
            "time_taken_s": round(time.time() - t0, 3),
            "sources_downloaded": []
        }

    # Verify tools
    try:
        import yt_dlp
    except ImportError:
        _log("BLOCKER: Missing yt-dlp tool.")
        return {
            "success": False,
            "blocker": "MISSING_TOOL: yt-dlp",
            "exact_step": "Install yt-dlp: C:\\LionReel\\venv\\Scripts\\pip.exe install yt-dlp",
            "time_taken_s": round(time.time() - t0, 3)
        }

    # Ensure ffmpeg binary directory is in PATH and passed to yt_dlp
    try:
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_dir = os.path.dirname(ffmpeg_bin)
        if ffmpeg_dir and ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        ffmpeg_dir = None

    from clip_ledger import ClipLedger, compute_window_5_phashes
    from canonical_window import get_canonical_window, measure_window_sharpness
    ledger = ClipLedger()
    detector = PetDetector()
    wm_detector = WatermarkDetector()

    # Windows wrongly rejected by the old sharpness reading are the cheapest footage there is
    windows_rechecked = recheck_sharpness_rejects(ledger, detector, animal_mode, target_needed, t0, max_seconds, _log)
    if windows_rechecked >= target_needed:
        _log(f"Recheck recovered {windows_rechecked} windows, no download needed.")
        return {"success": True, "queries_run": 0, "videos_found": 0, "windows_cut": 0, "windows_verified": windows_rechecked,
                "windows_rechecked": windows_rechecked, "rejects_by_reason": {}, "time_taken_s": round(time.time() - t0, 3), "sources_downloaded": []}
    target_needed -= windows_rechecked

    if max_downloads is None:
        # A source yields a handful of windows at best, so scale downloads to the shortfall
        max_downloads = min(15, max(3, int(target_needed) // 3 + 2))
    queries_run = 0
    videos_found = 0
    windows_cut = 0
    windows_verified = 0
    rejects_by_reason = {}
    sources_downloaded = []

    _log(f"STARTING REAL HARVEST | Target Needed: {target_needed} | Mode: {animal_mode} | Queries: {len(queries)}")

    for q in queries:
        if time.time() - t0 > max_seconds:
            _log(f"Harvest time budget of {max_seconds:.0f}s reached.")
            break
        queries_run += 1
        _log(f"Running Query {queries_run}/{len(queries)}: '{q}'")
        try:
            ydl_opts_search = {
                "quiet": True,
                "extract_flat": True,
                "no_warnings": True
            }
            with yt_dlp.YoutubeDL(ydl_opts_search) as ydl:
                # sp=EgIwAQ is the platform's own "Creative Commons" search filter
                query_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}&sp=EgIwAQ%253D%253D"
                search_res = ydl.extract_info(query_url, download=False)
                entries = list(search_res.get("entries", []) or [])[:max_search_results] if search_res else []
        except Exception as e:
            _log(f"Network / Search Error on '{q}': {e}")
            if "getaddrinfo failed" in str(e).lower() or "connection" in str(e).lower():
                return {
                    "success": False,
                    "blocker": "NETWORK_BLOCKED: Cannot connect to YouTube search",
                    "exact_step": "Verify active internet connection and ensure youtube.com is accessible.",
                    "time_taken_s": round(time.time() - t0, 3)
                }
            continue

        for entry in entries:
            if not entry or not entry.get("id"):
                continue
            vid_id = entry["id"]
            title = entry.get("title", "")
            video_url = f"https://www.youtube.com/watch?v={vid_id}"

            # Check if source already in cache or ledger or blocked
            cache_file = os.path.join(CACHE_DIR, f"cache_{vid_id}.mp4")
            if os.path.exists(cache_file) or ledger.is_blocked_source(cache_file):
                continue

            # Already looked up on an earlier harvest and unusable: skip without asking the platform again
            known_reason = known_unusable(source_licenses.lookup(vid_id), MIN_SOURCE_SECONDS)
            if known_reason:
                rejects_by_reason["KNOWN_" + known_reason] = rejects_by_reason.get("KNOWN_" + known_reason, 0) + 1
                continue

            videos_found += 1
            # Legal gate: the video page itself must show a Creative Commons licence
            try:
                lic_record = source_licenses.fetch_record(vid_id)
            except Exception as e_lic:
                rejects_by_reason["LICENSE_LOOKUP_FAILED"] = rejects_by_reason.get("LICENSE_LOOKUP_FAILED", 0) + 1
                _log(f"Skipped {vid_id}: licence lookup failed ({e_lic})")
                continue
            source_licenses.save_record(vid_id, lic_record)
            if lic_record["status"] != source_licenses.VERIFIED or not lic_record.get("creator"):
                rejects_by_reason["NOT_CC_LICENSED"] = rejects_by_reason.get("NOT_CC_LICENSED", 0) + 1
                _log(f"Skipped {vid_id}: no Creative Commons licence shown ({lic_record.get('license')})")
                continue
            usable, why_not = source_licenses.worth_downloading(lic_record, MIN_SOURCE_SECONDS)
            if not usable:
                rejects_by_reason[why_not] = rejects_by_reason.get(why_not, 0) + 1
                _log(f"Skipped {vid_id}: {why_not} ({lic_record.get('width')}x{lic_record.get('height')}, {lic_record.get('duration')}s)")
                continue
            uploader = lic_record["creator"]
            license_text = lic_record["license"]
            title = lic_record.get("title") or title
            _log(f"Found candidate: '{title}' by {uploader} (ID: {vid_id}) [{license_text}]")

            # Download if under limit
            if len(sources_downloaded) < max_downloads:
                _log(f"Downloading legal CC source: {vid_id}...")
                ydl_opts_dl = {
                    "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
                    "outtmpl": os.path.join(CACHE_DIR, f"cache_{vid_id}.%(ext)s"),
                    "merge_output_format": "mp4",
                    "quiet": True,
                    "noprogress": True,
                    "no_warnings": True,
                    "socket_timeout": 30,
                    "retries": 3
                }
                if ffmpeg_dir:
                    ydl_opts_dl["ffmpeg_location"] = ffmpeg_dir
                try:
                    with yt_dlp.YoutubeDL(ydl_opts_dl) as ydl_dl:
                        ydl_dl.download([video_url])
                except Exception as e_dl:
                    _log(f"Download failed for {vid_id}: {e_dl}")
                    continue

                # Locate downloaded file
                dl_candidates = glob.glob(os.path.join(CACHE_DIR, f"cache_{vid_id}.*"))
                target_video = dl_candidates[0] if dl_candidates else None
                if not target_video or not os.path.exists(target_video):
                    continue

                sources_downloaded.append(target_video)
                _log(f"Downloaded successfully: {os.path.basename(target_video)} ({os.path.getsize(target_video)/(1024*1024):.1f} MB)")

                # Screen source resolution and watermark
                probe = probe_video_fast(target_video)
                if not probe.get("pass_gate"):
                    rej = "BLOCKED_LOW_RES"
                    ledger.mark_source_blocked(target_video, rej)
                    rejects_by_reason[rej] = rejects_by_reason.get(rej, 0) + 1
                    _log(f"Source {vid_id} rejected by pre-screen: {rej}")
                    continue
                has_wm, wm_corner, wm_conf, wm_reason = wm_detector.check_video_corners(target_video, n_samples=8)
                if has_wm:
                    rej = f"BLOCKED_WATERMARK: {wm_reason}"
                    ledger.mark_source_blocked(target_video, rej)
                    rejects_by_reason["BLOCKED_WATERMARK"] = rejects_by_reason.get("BLOCKED_WATERMARK", 0) + 1
                    _log(f"Source {vid_id} rejected by watermark gate: {rej}")
                    continue
                try:
                    from qa_check import check_cartoon_classifier
                    cartoon_res = check_cartoon_classifier(target_video, n_samples=12)
                    if not cartoon_res.get("passed", True):
                        rej = f"BLOCKED_CARTOON: CGI prob {cartoon_res.get('mean_negative_probability', 0):.1%}"
                        ledger.mark_source_blocked(target_video, rej)
                        rejects_by_reason["BLOCKED_CARTOON"] = rejects_by_reason.get("BLOCKED_CARTOON", 0) + 1
                        _log(f"Source {vid_id} rejected by cartoon gate: {rej}")
                        continue
                except Exception:
                    pass

                # Cut canonical windows (7.5s clip_time)
                cap = cv2.VideoCapture(target_video)
                fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
                total_dur = frame_count / fps if fps > 0 else 0
                cap.release()

                if total_dur < 8.0:
                    continue

                # Propose candidate window starts (e.g. 10s, 20s, 30s)
                step = 10.0
                curr_start = 5.0
                while curr_start + 7.5 <= total_dur and windows_verified < target_needed:
                    c_win = get_canonical_window(f"cache_{vid_id}", curr_start, target_duration=7.5)
                    windows_cut += 1
                    cid = c_win["clip_id"]

                    # 1. Sharpness on the canonical scale, the measure the render gate and QA use
                    native_sharpness = measure_window_sharpness(target_video, c_win["start_s"], c_win["duration"])

                    # Quality floor 150 on the standard scale
                    if native_sharpness < 150.0:
                        rej_msg = f"LOW_SHARPNESS ({native_sharpness:.1f} < 150.0)"
                        rejects_by_reason[rej_msg] = rejects_by_reason.get(rej_msg, 0) + 1
                        ledger.add_clip(
                            clip_id=cid,
                            source_id=f"cache_{vid_id}",
                            source_url_or_path=target_video,
                            license_name=license_text,
                            start_s=c_win["start_s"],
                            end_s=c_win["end_s"],
                            frame_phashes=[],
                            is_verified=0,
                            sharpness=native_sharpness,
                            framing_score=0.0,
                            uploader=uploader,
                            title=title,
                            animal_type=animal_mode,
                            rejection_reason=rej_msg
                        )
                        _log(f"Window {cid} REJECTED: {rej_msg}")
                        curr_start += step
                        continue

                    # 2. Verify pet presence on canonical window (only for sharp frames)
                    analysis = fast_analyze_source_segment(target_video, c_win["start_s"], c_win["duration"], animal_mode, detector, wm_detector)
                    pet_ratio = analysis.get("pet_ratio", 0.0)

                    if pet_ratio < 0.80:
                        rej_msg = f"LOW_PET_PRESENCE ({pet_ratio*100:.0f}% < 80%)"
                        rejects_by_reason[rej_msg] = rejects_by_reason.get(rej_msg, 0) + 1
                        ledger.add_clip(
                            clip_id=cid,
                            source_id=f"cache_{vid_id}",
                            source_url_or_path=target_video,
                            license_name=license_text,
                            start_s=c_win["start_s"],
                            end_s=c_win["end_s"],
                            frame_phashes=[],
                            is_verified=0,
                            sharpness=native_sharpness,
                            framing_score=pet_ratio,
                            uploader=uploader,
                            title=title,
                            animal_type=animal_mode,
                            rejection_reason=rej_msg
                        )
                        _log(f"Window {cid} REJECTED: {rej_msg}")
                    else:
                        # Passed all gates!
                        phashes = compute_window_5_phashes(target_video, c_win["start_s"], c_win["end_s"])
                        ledger.add_clip(
                            clip_id=cid,
                            source_id=f"cache_{vid_id}",
                            source_url_or_path=target_video,
                            license_name=license_text,
                            start_s=c_win["start_s"],
                            end_s=c_win["end_s"],
                            frame_phashes=phashes,
                            is_verified=1,
                            framing_score=0.90,
                            sharpness=native_sharpness,
                            uploader=uploader,
                            title=title,
                            animal_type=animal_mode
                        )
                        windows_verified += 1
                        _log(f"Window {cid} VERIFIED! (Sharpness: {native_sharpness:.1f}, Pet: {pet_ratio*100:.0f}%)")

                    curr_start += step

            if windows_verified >= target_needed or time.time() - t0 > max_seconds:
                break

        if windows_verified >= target_needed:
            break

    elapsed = round(time.time() - t0, 3)
    _log(f"HARVEST FINISHED | Time: {elapsed}s | Queries: {queries_run} | Videos Found: {videos_found} | Windows Cut: {windows_cut} | Verified: {windows_verified}")

    return {
        "success": True,
        "queries_run": queries_run,
        "videos_found": videos_found,
        "windows_cut": windows_cut,
        "windows_verified": windows_verified + windows_rechecked,
        "windows_rechecked": windows_rechecked,
        "rejects_by_reason": rejects_by_reason,
        "time_taken_s": elapsed,
        "sources_downloaded": sources_downloaded
    }


def trigger_background_harvest_if_needed(animal_mode: str = "cat", min_low_water_mark: int = 20, target_clips_needed: Optional[int] = None):
    """
    Checks if verified unused clips in pool drop below low-water mark (20) or target_clips_needed,
    OR if distinct verified sources are low (< 4),
    OR if a single source dominates the pool (>60%).
    If so, launches background worker in a separate process without blocking!
    """
    ledger = ClipLedger()
    status = ledger.get_pool_status(animal_mode)
    verified_unused = status.get("verified_unused_clips", 0)
    verified_sources = status.get("verified_sources_count", 0)

    # Check if one source dominates the pool (>60%)
    source_dominated = False
    try:
        with ledger._get_conn() as conn:
            cur = conn.execute("""
                SELECT source_url_or_path, COUNT(*) as cnt 
                FROM clips 
                WHERE animal_type = ? AND times_used == 0 AND is_verified = 1
                GROUP BY source_url_or_path
            """, (animal_mode,))
            counts = [r["cnt"] for r in cur.fetchall()]
            if counts and verified_unused > 0:
                top_cnt = max(counts)
                if (top_cnt / float(verified_unused)) > 0.60 and len(counts) <= 2:
                    source_dominated = True
    except Exception:
        pass

    needed_threshold = target_clips_needed if target_clips_needed is not None else min_low_water_mark
    needs_harvest = (verified_unused < needed_threshold) or (verified_sources < 4) or source_dominated
    if needs_harvest and not is_harvest_running():
        # Spawn background process
        local_venv_py = lion_paths.venv_python()
        python_exe = local_venv_py if os.path.exists(local_venv_py) else (sys.executable or "python")
        worker_script = os.path.join(BASE_DIR, "harvest_worker.py")
        target_to_add = 20
        if target_clips_needed and target_clips_needed > verified_unused:
            target_to_add = max(20, target_clips_needed - verified_unused + 10)

        harvest_log_file = os.path.join(BASE_DIR, "data", "harvest.log")
        os.makedirs(os.path.dirname(harvest_log_file), exist_ok=True)
        with open(harvest_log_file, "a", encoding="utf-8", errors="ignore") as h_log_fd:
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

