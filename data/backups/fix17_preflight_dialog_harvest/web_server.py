import os
import sys

# Self-heal Python runtime: C-extensions (OpenCV, NumPy) are compiled for Python 3.12.
# If invoked via system Python (e.g. Python 3.14 on PATH), automatically re-exec under the verified Python 3.12 venv.
if sys.version_info >= (3, 13) or sys.version_info < (3, 11):
    _CANDIDATE_VENVS = [
        r"C:\LionReel\venv\Scripts\python.exe",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Scripts", "python.exe")
    ]
    for _venv_py in _CANDIDATE_VENVS:
        if os.path.exists(_venv_py) and os.path.normpath(sys.executable) != os.path.normpath(_venv_py):
            import subprocess
            sys.exit(subprocess.call([_venv_py] + sys.argv))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_VENV_SITE = os.path.join(BASE_DIR, ".venv", "Lib", "site-packages")
if os.path.exists(_VENV_SITE) and _VENV_SITE not in sys.path and sys.version_info[:2] == (3, 12):
    sys.path.insert(0, _VENV_SITE)

import json
import time
import subprocess
import threading
import socketserver
import re
import uuid
import shutil
import gc
import urllib.parse
from http.server import SimpleHTTPRequestHandler
from typing import Optional, List, Dict, Any, Tuple
import atexit

PORT = int(os.environ.get("PORT", 8000))
RUNNING_PROCESS = None
RUNNING_PROCESS_START_TIME = None
CURRENT_JOB_ID = None
LAST_EXIT_CODE = None
LOG_FILE = "gui_run.log"
CONFIG_FILE = "config.json"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FINISHED_DIR = os.path.join(BASE_DIR, "finished")
RAW_DIR = os.path.join(BASE_DIR, "raw")
OWN_FOOTAGE_DIR = os.path.join(BASE_DIR, "own_footage")
LOCK_FILE = os.path.join(BASE_DIR, "web_server.lock")

def acquire_server_lock():
    pid = os.getpid()
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                existing_pid = int(content)
                if existing_pid != pid:
                    import ctypes
                    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                    STILL_ACTIVE = 259
                    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, existing_pid)
                    if h:
                        exit_code = ctypes.c_ulong()
                        is_active = False
                        if ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code)):
                            is_active = (exit_code.value == STILL_ACTIVE)
                        ctypes.windll.kernel32.CloseHandle(h)
                        if is_active:
                            print(f"[FATAL] Another instance of LionReel Web Server is already running (PID: {existing_pid}).")
                            print(f"       Exiting immediately to prevent port collision and duplicate logging.")
                            sys.exit(1)
        except (ValueError, OSError):
            pass
        except Exception as e_lk:
            print(f"Notice during lock check: {e_lk}")
    try:
        with open(LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(str(pid))
    except Exception:
        pass

def release_server_lock():
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content == str(os.getpid()):
                os.remove(LOCK_FILE)
    except Exception:
        pass

atexit.register(release_server_lock)

def format_log_lines_monotonic(raw_lines: List[str], req_seq: int = 0) -> List[Dict[str, Any]]:
    """
    Format lines with strictly monotonic 1..N sequence numbering based on line position.
    Preserves all lines without dropping collisions between embedded [SEQ:...] tags and file line indices.
    Isolates active session starting from the latest launch banner and deduplicates lines.
    """
    res = []
    banner_indices = [i for i, line in enumerate(raw_lines) if "=== Launching LionReel Automation Script" in line]
    active_lines = raw_lines[banner_indices[-1]:] if banner_indices else raw_lines

    seen_entries = set()
    seq_counter = 1
    for line_str in active_lines:
        clean_str = line_str.rstrip("\r\n")
        if not clean_str:
            continue
        entry_key = (seq_counter, clean_str)
        if entry_key not in seen_entries:
            seen_entries.add(entry_key)
            if seq_counter > req_seq:
                res.append({"seq": seq_counter, "text": clean_str})
            seq_counter += 1
    return res

def get_local_work_dir():
    try:
        cfg_file = os.path.join(BASE_DIR, "config.json")
        if os.path.exists(cfg_file):
            with open(cfg_file, "r", encoding="utf-8") as f:
                c = json.load(f)
                if c.get("LOCAL_WORK_DIR"):
                    os.makedirs(c["LOCAL_WORK_DIR"], exist_ok=True)
                    return c["LOCAL_WORK_DIR"]
    except Exception:
        pass
    local_p = os.path.join("C:\\", "LionReel", "work")
    try:
        os.makedirs(local_p, exist_ok=True)
        return local_p
    except Exception:
        fallback = os.path.join(BASE_DIR, "work")
        os.makedirs(fallback, exist_ok=True)
        return fallback

def compute_pool_capacity(verified_windows: int, usable_sources: int, target_clips: int = 100) -> dict:
    """
    Requirement 5: capacity = min(verified_windows, usable_sources * 3).
    min_sources_needed_for_100 = 34.
    """
    cap = min(int(verified_windows), int(usable_sources) * 3)
    needed = max(1, (int(target_clips) + 2) // 3)
    can_supply = cap >= int(target_clips)
    warning_msg = "" if can_supply else f"This pool can supply at most {cap} clips. {target_clips} clips need at least {needed} sources."
    return {
        "capacity": cap,
        "verified_windows": int(verified_windows),
        "usable_sources": int(usable_sources),
        "target_clips": int(target_clips),
        "min_sources_needed_for_100": needed,
        "can_supply_target": can_supply,
        "warning": warning_msg,
        "options": ["set_n_clips", "harvest_first", "start_anyway"] if not can_supply else []
    }


def should_auto_resume_job(job_id: str, status: str) -> bool:
    """
    Requirement 2 & 3:
    Production supervisor/auto_resume_watcher never resumes sandbox_ or test_ jobs.
    Only resumes waiting_for_clips or needs_sources jobs.
    """
    if not job_id:
        return False
    if str(job_id).startswith("sandbox_") or str(job_id).startswith("test_"):
        return False
    return status in ("waiting_for_clips", "needs_sources")

WORK_DIR = get_local_work_dir()
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
JOB_RESULT_FILE = os.path.join(BASE_DIR, "job_result.json")

for d in [FINISHED_DIR, RAW_DIR, OWN_FOOTAGE_DIR, WORK_DIR, OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)

DEFAULT_CONFIG = {
    "VIDEO_MODE": "cat",
    "SOURCE_MODE": "classic",
    "CUSTOM_URL": "",
    "OWN_FOOTAGE_FILE": "",
    "VIDEO_TYPE": "short",
    "TARGET_DURATION_MIN": 5.0,
    "ASPECT_RATIO": "9:16",
    "BYPASS_QUALITY_GATE": False,
    "BYPASS_FUNNY_CHECK": False,
    "TARGET_CLIPS": 4,
    "SHORT_CLIP_SEC": 7.5,
    "ALLOW_SHORTER": False,
    "SPEED_PROFILE": "fast",
    "CHECK_SHARPNESS": True,
    "CHECK_SHAKE": True,
    "CHECK_WATERMARK": True,
    "CHECK_DUPLICATES": True,
    "APPLY_COLOR_GRADING": False,
    "APPLY_SMART_CROP": True,
    "ADD_BACKGROUND_MUSIC": True,
    "CHECK_AUDIO_LEVELS": True,
    "ENFORCE_ASPECT_RATIO": True,
    "CHECK_AI_VIDEO": True,
    "CHECK_CARTOON": True,
    "CHECK_ADVERTISING": True,
    "MOMENT_CUT_MODE": "peak_viral"
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except:
            pass
    return DEFAULT_CONFIG

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=4)
        return True
    except:
        return False

def ensure_icon():
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    png_path = os.path.join(workspace_dir, "lion_logo.png")
    ico_path = os.path.join(workspace_dir, "lion_logo.ico")
    
    if os.path.exists(png_path) and not os.path.exists(ico_path):
        try:
            from PIL import Image
            img = Image.open(png_path)
            icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
            img.save(ico_path, format="ICO", sizes=icon_sizes)
            return True
        except Exception as e:
            print(f"Error creating ico from png: {e}")
    return os.path.exists(ico_path)


def robust_remove(filepath, max_retries=6, delay=0.15):
    """
    Safely and aggressively removes a file or directory on Windows,
    handling file locks, retry delays, and Python garbage collection.
    """
    if not filepath or not os.path.exists(filepath):
        return True
    
    for attempt in range(max_retries):
        try:
            if os.path.isdir(filepath):
                shutil.rmtree(filepath)
            else:
                os.remove(filepath)
            if not os.path.exists(filepath):
                return True
        except PermissionError:
            # File or folder is locked by another process (or open socket/player)
            gc.collect()
            time.sleep(delay * (attempt + 1))
        except Exception:
            time.sleep(delay)
    
    if not os.path.exists(filepath):
        return True
    
    # Fallback on Windows: try renaming to a temp delete file
    try:
        if os.path.isfile(filepath):
            trash_path = filepath + f".del_{int(time.time() * 1000)}"
            os.rename(filepath, trash_path)
            try:
                os.remove(trash_path)
            except Exception:
                pass
            return not os.path.exists(filepath)
    except Exception:
        pass

    return not os.path.exists(filepath)

def delete_compilation_files(filename):
    """
    Deletes a compilation and ALL its related artifacts across:
    - FINISHED_DIR (mp4, mapping.json, credits.json, metadata.txt, txt, qa_report.json, contact_sheet.png, thumbs)
    - OUTPUT_DIR (subfolder <stem> and any matching files)
    - WORK_DIR (subfolder <stem> and any matching files)
    - JOB_RESULT_FILE (if it points to this video)
    - ClipLedger (releases clips back to pool and removes from output_registry)
    Returns (success: bool, deleted_files: list, error_message: str)
    """
    if not filename:
        return False, [], "Filename is empty"
    
    clean_name = os.path.basename(filename).split("?")[0].split("#")[0].strip()
    if not clean_name:
        return False, [], "Invalid filename"
    
    stem = os.path.splitext(clean_name)[0]
    # If passed e.g. lion_metadata_cat_123.txt, extract lion_cat_123
    if stem.startswith("lion_metadata_"):
        stem = stem.replace("lion_metadata_", "lion_")
    if stem.endswith("_metadata"):
        stem = stem[:-9]
    if stem.endswith("_thumb"):
        stem = stem[:-6]
    
    deleted_files = []
    failed_locks = []

    # 1. FINISHED_DIR: find all related files
    if os.path.exists(FINISHED_DIR):
        for f in os.listdir(FINISHED_DIR):
            fp = os.path.join(FINISHED_DIR, f)
            if not os.path.isfile(fp):
                continue
            is_match = False
            if f == clean_name or f == f"{stem}.mp4" or f == f"{stem}.txt":
                is_match = True
            elif f.startswith(stem + "_") or f.startswith(stem + "."):
                is_match = True
            # Also handle legacy lion_ / lion_metadata_
            elif "lion_" in stem and f.replace("lion_metadata_", "lion_").startswith(stem):
                is_match = True
            
            if is_match:
                if robust_remove(fp):
                    deleted_files.append(f"finished/{f}")
                else:
                    failed_locks.append(f"finished/{f}")

    # 2. OUTPUT_DIR: remove output/<stem> subfolder and any direct matching files
    if os.path.exists(OUTPUT_DIR):
        # Dedicated job subfolder in output/
        job_dir = os.path.join(OUTPUT_DIR, stem)
        if os.path.exists(job_dir):
            if robust_remove(job_dir):
                deleted_files.append(f"output/{stem}/")
            else:
                failed_locks.append(f"output/{stem}/")
        
        # Direct files in output/
        for f in os.listdir(OUTPUT_DIR):
            fp = os.path.join(OUTPUT_DIR, f)
            if os.path.isfile(fp):
                if f == clean_name or f.startswith(stem + "_") or f.startswith(stem + "."):
                    if robust_remove(fp):
                        deleted_files.append(f"output/{f}")
                    else:
                        failed_locks.append(f"output/{f}")

    # 3. WORK_DIR: remove work/<stem> subfolder
    if os.path.exists(WORK_DIR):
        work_job_dir = os.path.join(WORK_DIR, stem)
        if os.path.exists(work_job_dir):
            if robust_remove(work_job_dir):
                deleted_files.append(f"work/{stem}/")

    # 4. Clear JOB_RESULT_FILE if it points to this output
    if os.path.exists(JOB_RESULT_FILE):
        try:
            with open(JOB_RESULT_FILE, "r", encoding="utf-8") as f_jr:
                jr_data = json.load(f_jr)
            out_file = jr_data.get("output_file", "")
            j_id = jr_data.get("job_id", "")
            if out_file == clean_name or j_id == stem or (stem and stem in out_file):
                robust_remove(JOB_RESULT_FILE)
                deleted_files.append("job_result.json")
        except Exception:
            pass

    # 5. Release clips from ClipLedger & remove from output_registry
    try:
        from clip_ledger import ClipLedger
        ledger = ClipLedger()
        ledger.delete_output(stem)
    except Exception as e_led:
        print(f"Notice: ClipLedger release: {e_led}")

    if failed_locks:
        return False, deleted_files, f"File(s) locked by another process: {', '.join(failed_locks)}"

    # If nothing matched in finished or output, check if the file existed anywhere
    if not deleted_files:
        direct_p = os.path.join(FINISHED_DIR, clean_name)
        if os.path.exists(direct_p):
            if not robust_remove(direct_p):
                return False, [], f"Could not remove locked file: {clean_name}"
            deleted_files.append(f"finished/{clean_name}")
        else:
            return True, [], f"File was already removed or not found: {clean_name}"

    return True, deleted_files, ""


class DashboardHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_PUT(self):
        return self.do_POST()

    def do_HEAD(self):
        if self.path.startswith("/finished/"):
            clean_path = self.path.split("?")[0].split("#")[0]
            filename = urllib.parse.unquote(clean_path.replace("/finished/", ""))
            filepath = os.path.join(FINISHED_DIR, filename)
            if os.path.exists(filepath):
                self.send_response(200)
                lower = filename.lower()
                if lower.endswith(".mp4"):
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Accept-Ranges", "bytes")
                elif lower.endswith(".jpg") or lower.endswith(".jpeg"):
                    self.send_header("Content-Type", "image/jpeg")
                elif lower.endswith(".png"):
                    self.send_header("Content-Type", "image/png")
                elif lower.endswith(".json"):
                    self.send_header("Content-Type", "application/json")
                else:
                    self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(os.path.getsize(filepath)))
                self.end_headers()
                return
            else:
                self.send_error(404, "File not found")
                return

        if self.path == "/" or self.path == "":
            self.path = "/gui/index.html"
        elif not self.path.startswith("/gui/"):
            self.path = f"/gui{self.path}"
        self.path = self.path.replace("//", "/")
        return super().do_HEAD()

    def do_GET(self):
        global RUNNING_PROCESS, RUNNING_PROCESS_START_TIME, LAST_EXIT_CODE
        clean_path = self.path.split("?")[0]
        
        # Route API Calls
        if self.path.startswith("/api/status"):
            is_running = False
            start_time_ms = None
            elapsed_sec = 0
            if RUNNING_PROCESS is not None:
                poll_res = RUNNING_PROCESS.poll()
                if poll_res is None:
                    is_running = True
                    if RUNNING_PROCESS_START_TIME:
                        start_time_ms = int(RUNNING_PROCESS_START_TIME * 1000)
                        elapsed_sec = int(time.time() - RUNNING_PROCESS_START_TIME)
                else:
                    LAST_EXIT_CODE = poll_res
                    final_elapsed = round(time.time() - RUNNING_PROCESS_START_TIME, 1) if RUNNING_PROCESS_START_TIME else 0
                    RUNNING_PROCESS = None
                    RUNNING_PROCESS_START_TIME = None

                    if poll_res != 0:
                        job_log_path = os.path.join(WORK_DIR, CURRENT_JOB_ID, "job.log") if CURRENT_JOB_ID else None
                        stderr_tail = []
                        if job_log_path and os.path.exists(job_log_path):
                            try:
                                with open(job_log_path, "r", encoding="utf-8", errors="ignore") as f_jl:
                                    lines = f_jl.readlines()
                                    stderr_tail = [l.strip() for l in lines[-20:] if l.strip()]
                            except Exception:
                                pass

                        log_tail_text = "\n".join(stderr_tail)
                        if poll_res == 2:
                            reason_code = "INVALID_ARGUMENTS"
                            arg_err_match = re.search(r"error:\s*(.+)", log_tail_text)
                            if arg_err_match:
                                human_error = f"Invalid option: {arg_err_match.group(1)}"
                            else:
                                human_error = "Invalid arguments passed to engine (exit code 2)"
                        elif poll_res < 0 or poll_res in (15, 9):
                            reason_code = "KILLED"
                            human_error = "Job process was terminated or killed"
                        else:
                            reason_code = "CRASH"
                            human_error = f"Process crashed with error code {poll_res}"

                        print(f"[Job Error] Reason: {reason_code} | {human_error} | Exit code: {poll_res}")

                        try:
                            with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_err:
                                json.dump({
                                    "job_id": CURRENT_JOB_ID,
                                    "status": "error",
                                    "success": False,
                                    "reason_code": reason_code,
                                    "error": human_error,
                                    "details": log_tail_text,
                                    "exit_code": poll_res,
                                    "elapsed_seconds": final_elapsed,
                                    "failed_stage": "startup" if final_elapsed < 2 else None
                                }, f_err, indent=2)
                        except Exception:
                            pass
            
            job_res = None
            if os.path.exists(JOB_RESULT_FILE):
                try:
                    with open(JOB_RESULT_FILE, "r", encoding="utf-8") as f_jr:
                        job_res = json.load(f_jr)
                except:
                    pass

            job_id = None
            if job_res:
                job_id = job_res.get("job_id")
            if not job_id and CURRENT_JOB_ID:
                job_id = CURRENT_JOB_ID

            if is_running:
                computed_status = "running"
            elif job_res and job_res.get("status") in ("waiting_for_clips", "needs_sources"):
                computed_status = job_res.get("status")
            elif job_res and job_res.get("status") == "completed" and job_res.get("success"):
                computed_status = "completed"
            elif job_res and (job_res.get("status") == "error" or job_res.get("success") is False):
                computed_status = "error"
            elif LAST_EXIT_CODE is not None:
                if job_res and job_res.get("status") in ("waiting_for_clips", "needs_sources"):
                    computed_status = job_res.get("status")
                elif LAST_EXIT_CODE == 0 and job_res and job_res.get("success"):
                    computed_status = "completed"
                elif LAST_EXIT_CODE == 0:
                    computed_status = job_res.get("status", "completed") if job_res else "completed"
                else:
                    computed_status = "error"
            else:
                computed_status = "idle"

            harvest_info = None
            try:
                from harvest_worker import get_harvest_status
                harvest_info = get_harvest_status()
            except Exception:
                pass

            if not is_running and job_res:
                if job_res.get("elapsed_seconds"):
                    elapsed_sec = int(round(job_res["elapsed_seconds"]))
                elif job_res.get("render_time_sec"):
                    elapsed_sec = int(round(job_res["render_time_sec"]))

            stages_list = None
            stages_file = None
            if job_id:
                stages_file = os.path.join(WORK_DIR, job_id, "stages_state.json")
                if os.path.exists(stages_file):
                    try:
                        with open(stages_file, "r", encoding="utf-8") as f_stg:
                            stages_data = json.load(f_stg)
                            stages_list = stages_data.get("stages")
                    except Exception:
                        pass

            from stage_state_machine import STAGE_DEFINITIONS
            if not stages_list:
                stages_list = []
                for d in STAGE_DEFINITIONS:
                    st = "DONE" if computed_status == "completed" else "PENDING"
                    if computed_status in ("waiting_for_clips", "needs_sources") and d["id"] == 1:
                        st = "WAITING"
                    stages_list.append({
                        "id": d["id"],
                        "key": d["key"],
                        "label": d["label"],
                        "status": st,
                        "duration_sec": 0.0,
                        "evidence": f"Waiting: {job_res.get('clips_ready', 0)} of {job_res.get('clips_needed', 0)} ready" if (computed_status in ("waiting_for_clips", "needs_sources") and d["id"] == 1 and job_res) else "",
                        "reason": f"{job_res.get('clips_ready', 0)} of {job_res.get('clips_needed', 0)} ready" if (computed_status in ("waiting_for_clips", "needs_sources") and d["id"] == 1 and job_res) else "",
                        "toggle_key": d.get("toggle_key"),
                        "allow_parallel": d.get("allow_parallel", False)
                    })
            else:
                # Update stage states based on computed_status
                if computed_status in ("waiting_for_clips", "needs_sources"):
                    changed = False
                    for s_item in stages_list:
                        if s_item.get("id") == 1 or s_item.get("status") == "RUNNING":
                            s_item["status"] = "WAITING"
                            ready = job_res.get("clips_ready", 0) if job_res else 0
                            needed = job_res.get("clips_needed", 0) if job_res else 0
                            s_item["reason"] = f"{ready} of {needed} ready"
                            s_item["evidence"] = f"Waiting: {ready} of {needed} clips ready"
                            changed = True
                            break
                    if changed and stages_file:
                        try:
                            with open(stages_file, "w", encoding="utf-8") as f_stg_w:
                                json.dump({"job_id": job_id, "stages": stages_list}, f_stg_w, indent=2)
                        except Exception:
                            pass
                elif computed_status == "error":
                    changed = False
                    for s_item in stages_list:
                        if s_item.get("status") == "RUNNING":
                            s_item["status"] = "FAILED"
                            s_item["reason"] = "Process terminated unexpectedly"
                            s_item["evidence"] = "Failed: Process terminated unexpectedly"
                            changed = True
                    if changed and stages_file:
                        try:
                            with open(stages_file, "w", encoding="utf-8") as f_stg_w:
                                json.dump({"job_id": job_id, "stages": stages_list}, f_stg_w, indent=2)
                        except Exception:
                            pass

            # Honest server-side estimator calculation
            estimator_telemetry = None
            try:
                from stage_estimator import StageEstimator
                if not hasattr(self.server, "estimator") or self.server.estimator is None:
                    self.server.estimator = StageEstimator()

                current_cfg = load_config()
                if job_id:
                    cfg_p = os.path.join(WORK_DIR, job_id, "config.json")
                    if os.path.exists(cfg_p):
                        try:
                            with open(cfg_p, "r", encoding="utf-8") as f_cfg:
                                current_cfg.update(json.load(f_cfg))
                        except Exception:
                            pass

                st_data = stages_data if (stages_file and os.path.exists(stages_file)) else {"stages": stages_list}
                waiting_s = 0.0
                if job_res and "waiting_seconds" in job_res:
                    waiting_s = float(job_res.get("waiting_seconds", 0.0))

                start_epoch = RUNNING_PROCESS_START_TIME if RUNNING_PROCESS_START_TIME else (start_time_ms / 1000.0 if start_time_ms else time.time())
                estimator_telemetry = self.server.estimator.compute_job_telemetry(
                    job_id=job_id or "job",
                    stages_data=st_data,
                    config=current_cfg,
                    start_time_epoch=start_epoch,
                    is_running=is_running,
                    status=computed_status,
                    waiting_seconds=waiting_s
                )
            except Exception as e_est:
                print(f"[Estimator Error] {e_est}")

            if estimator_telemetry:
                real_elapsed = estimator_telemetry["elapsedSeconds"]
                progress_val = estimator_telemetry["progressPct"]
                eta_val = estimator_telemetry["etaSeconds"]
                eta_fmt = estimator_telemetry["etaFormatted"]
                is_calc = estimator_telemetry["isCalculating"]
                state_lbl = estimator_telemetry["stateLabel"]
                current_stage_idx = estimator_telemetry.get("currentStageId", 1)
                current_stage_name = estimator_telemetry.get("currentStageName", "")
                if computed_status in ("waiting_for_clips", "needs_sources"):
                    state_lbl = "WAITING"
                    if job_res and job_res.get("clips_needed"):
                        progress_val = int(round((job_res.get("clips_ready", 0) / float(max(1, job_res.get("clips_needed", 1)))) * 100))
            else:
                real_elapsed = round(time.time() - RUNNING_PROCESS_START_TIME, 1) if (is_running and RUNNING_PROCESS_START_TIME) else elapsed_sec
                if computed_status in ("waiting_for_clips", "needs_sources") and job_res:
                    progress_val = int(round((job_res.get("clips_ready", 0) / float(max(1, job_res.get("clips_needed", 1)))) * 100))
                else:
                    progress_val = (job_res.get("progress_pct") if job_res else (100 if computed_status == "completed" else 5))
                eta_val = 0
                eta_fmt = "--:--"
                is_calc = False
                state_lbl = "LIVE" if is_running else ("DONE" if computed_status == "completed" else ("WAITING" if computed_status in ("waiting_for_clips", "needs_sources") else "FAILED"))
                current_stage_idx = (job_res.get("stage_index") if job_res else (10 if computed_status == "completed" else 1))
                current_stage_name = (job_res.get("stage_name") if job_res else "")

            active_pid = RUNNING_PROCESS.pid if (RUNNING_PROCESS and RUNNING_PROCESS.poll() is None) else None
            running_procs = [active_pid] if active_pid else []

            wait_checkpoint = None
            if job_id:
                cp_file = os.path.join(WORK_DIR, job_id, "wait_checkpoint.json")
                if os.path.exists(cp_file):
                    try:
                        with open(cp_file, "r", encoding="utf-8") as f_cp:
                            wait_checkpoint = json.load(f_cp)
                    except Exception:
                        pass

            resp_data = {
                "status": computed_status,
                "job_id": job_id,
                "isRunning": is_running,
                "runningPid": active_pid,
                "runningProcesses": running_procs,
                "startTimeMs": start_time_ms,
                "elapsedSeconds": real_elapsed,
                "realElapsedSec": real_elapsed,
                "stageIndex": current_stage_idx,
                "stageName": current_stage_name,
                "progressPct": progress_val,
                "etaSeconds": eta_val,
                "etaFormatted": eta_fmt,
                "isCalculating": is_calc,
                "stateLabel": state_lbl,
                "estimator": estimator_telemetry,
                "candidateReports": (job_res.get("candidate_reports", []) if job_res else []),
                "failedStage": (job_res.get("failed_stage") if job_res else ("startup" if (LAST_EXIT_CODE not in (None, 0) and computed_status == "error") else None)),
                "exitCode": (0 if computed_status in ("waiting_for_clips", "needs_sources") else LAST_EXIT_CODE),
                "reasonCode": (job_res.get("reason_code") if job_res else ("INVALID_ARGUMENTS" if LAST_EXIT_CODE == 2 else ("CRASH" if (LAST_EXIT_CODE and LAST_EXIT_CODE != 0) else None))),
                "errorDetails": (job_res.get("details") if job_res else None),
                "jobResult": job_res,
                "stages": stages_list,
                "harvestStatus": harvest_info,
                "waitCheckpoint": wait_checkpoint,
                "generatedFile": job_res.get("output_file") if (job_res and job_res.get("success")) else None,
                "sha256": job_res.get("sha256") if (job_res and job_res.get("success")) else None,
                "clipList": job_res.get("clip_list") if (job_res and job_res.get("success")) else [],
                "duration": job_res.get("duration") if (job_res and job_res.get("success")) else None,
                "renderTimeSec": job_res.get("render_time_sec") if (job_res and job_res.get("success")) else None,
                "error": (None if computed_status in ("waiting_for_clips", "needs_sources") else (job_res.get("error") if (job_res and not job_res.get("success")) else (
                    ("Invalid option: arguments not accepted by engine" if LAST_EXIT_CODE == 2 else f"Process crashed with exit code {LAST_EXIT_CODE} (CRASH)") if (LAST_EXIT_CODE not in (None, 0) and computed_status == "error") else None
                )))
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(json.dumps(resp_data).encode())
            return

        elif self.path.startswith("/api/stages"):
            from stage_state_machine import STAGE_DEFINITIONS
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(json.dumps({"stages": STAGE_DEFINITIONS}).encode())
            return

        elif self.path.startswith("/api/harvest-status") or self.path.startswith("/api/harvest/status"):
            try:
                from harvest_worker import get_harvest_status
                h_data = get_harvest_status()
            except Exception as e_h:
                h_data = {
                    "is_harvesting": False,
                    "state": "error",
                    "error": str(e_h),
                    "sources_scanned": 0,
                    "windows_analyzed": 0,
                    "windows_verified": 0,
                    "rejects_by_reason": {},
                    "growth_per_minute": 0.0,
                    "last_activity_time": 0.0
                }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(json.dumps(h_data).encode())
            return

        elif self.path.startswith("/api/clear-error") or self.path.startswith("/api/dismiss-error"):
            LAST_EXIT_CODE = None
            if os.path.exists(JOB_RESULT_FILE):
                try: os.remove(JOB_RESULT_FILE)
                except: pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode())
            return

        elif self.path.startswith("/api/config"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(load_config()).encode())
            return

        elif self.path.startswith("/api/pool"):
            animal_type = "cat"
            if "animal=" in self.path:
                try:
                    animal_type = self.path.split("animal=")[1].split("&")[0].lower()
                except:
                    pass
            try:
                from clip_ledger import ClipLedger
                ledger = ClipLedger()
                pool_data = ledger.get_pool_status(animal_type)
            except Exception as e_pool:
                pool_data = {
                    "animal_type": animal_type,
                    "pool_cycle": 1,
                    "total_clips": 0,
                    "used_clips": 0,
                    "unused_clips": 0,
                    "usage_pct": 0.0,
                    "warning": False,
                    "status_label": "Clip pool: 0 clips registered",
                    "error": str(e_pool)
                }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(pool_data).encode())
            return

        elif self.path.startswith("/api/pool-health"):
            animal_type = "cat"
            if "animal=" in self.path:
                try: animal_type = self.path.split("animal=")[1].split("&")[0].lower()
                except: pass
            try:
                from clip_ledger import ClipLedger
                ledger = ClipLedger()
                health_data = ledger.get_pool_status(animal_type)
            except Exception as e_ph:
                health_data = {"error": str(e_ph)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(health_data).encode())
            return

        elif self.path.startswith("/api/preflight"):
            animal = "cat"
            format_type = "short"
            target_clips = 6
            clip_time = 7.5

            if "?" in self.path:
                q = urllib.parse.parse_qs(self.path.split("?", 1)[1])
                if "animal" in q: animal = q["animal"][0]
                if "type" in q: format_type = q["type"][0]
                elif "format" in q: format_type = q["format"][0]
                if "clips" in q:
                    try: target_clips = int(q["clips"][0])
                    except: pass
                if "clip_time" in q:
                    try: clip_time = float(q["clip_time"][0])
                    except: pass

            import job_options
            canonical_animal = job_options.ANIMAL_MAP.get(animal.lower(), "cat")
            is_comp = format_type in ["long", "compilation", "both"]
            if is_comp:
                if target_clips < 10:
                    target_clips = 100
                if clip_time < 8.0:
                    clip_time = 12.0

            verified_windows = 0
            distinct_sources = 0
            vertical_sources = 0
            candidates = 0
            try:
                from clip_ledger import ClipLedger
                ledger = ClipLedger()
                pool_cap = ledger.get_pool_ready_and_capacity(canonical_animal, target_clips=target_clips, allow_reuse=is_comp)
                verified_windows = pool_cap["verified_windows"]
                distinct_sources = pool_cap["usable_sources"]
                candidates = pool_cap["candidates"]
                pool_data = ledger.get_pool_status(canonical_animal)
                vertical_sources = pool_data.get("vertical_sources_count", pool_data.get("vertical_sources", 0))
                landscape_sources = pool_data.get("landscape_sources_count", 0)
            except Exception:
                pool_cap = compute_pool_capacity(verified_windows=0, usable_sources=0, target_clips=target_clips)
                vertical_sources = 0
                landscape_sources = 0

            min_sources_needed = pool_cap["min_sources_needed"]
            sources_shortfall = max(0, min_sources_needed - distinct_sources)
            clips_shortfall = max(0, target_clips - verified_windows)
            est_harvest_time_sec = clips_shortfall * 45
            est_render_time_sec = int(target_clips * clip_time * 2.5)

            is_ready = pool_cap["can_supply_target"]
            status_code = "ready" if is_ready else ("needs_sources" if sources_shortfall > 0 else "needs_harvest")
            needed_sources_cnt = sources_shortfall if sources_shortfall > 0 else max(1, (clips_shortfall + 2) // 3)
            prompt_msg = pool_cap["warning"] if pool_cap["warning"] else f"Pool: {verified_windows} of {target_clips} ready. About {needed_sources_cnt} sources needed."

            resp = {
                "animal": canonical_animal,
                "format": format_type,
                "needed_clips": target_clips,
                "clip_time": clip_time,
                "verified_windows": verified_windows,
                "candidates": candidates,
                "distinct_sources": distinct_sources,
                "vertical_sources": vertical_sources,
                "landscape_sources": landscape_sources,
                "min_sources_needed": min_sources_needed,
                "capacity": pool_cap["capacity"],
                "can_supply_target": pool_cap["can_supply_target"],
                "warning": pool_cap["warning"],
                "options": pool_cap["options"],
                "shortfall": clips_shortfall,
                "sources_shortfall": sources_shortfall,
                "estimated_harvest_time_sec": est_harvest_time_sec,
                "estimated_render_time_sec": est_render_time_sec,
                "estimated_render_time_min": round(est_render_time_sec / 60, 1),
                "is_ready": is_ready,
                "status": status_code,
                "message": prompt_msg
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode())
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/edits"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                from edl_manager import EDLManager
                em = EDLManager()
                edl_data = em.get_edl(job_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(edl_data).encode())
            except Exception as e_edl:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.wfile.write(json.dumps({"error": str(e_edl)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/info"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                from edl_manager import EDLManager
                em = EDLManager()
                info_data = em.get_video_info(job_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(info_data).encode())
            except Exception as e_info:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_info)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and "/sources/check" in clean_path:
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                from edl_manager import EDLManager
                em = EDLManager()
                edl_data = em.get_edl(job_id)
                missing = edl_data.get("missing_sources", [])
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"has_missing_sources": len(missing) > 0, "missing_sources": missing}).encode())
            except Exception as e_chk:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_chk)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/metadata"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                meta_path = os.path.join(WORK_DIR, job_id, "metadata.json")
                if not os.path.exists(meta_path):
                    alt_path = os.path.join(BASE_DIR, "output", job_id, "metadata.json")
                    if os.path.exists(alt_path):
                        meta_path = alt_path

                if os.path.exists(meta_path):
                    with open(meta_path, "r", encoding="utf-8") as fm:
                        pkg = json.load(fm)
                else:
                    from metadata_generator import MetadataGenerator
                    mg = MetadataGenerator()
                    cred_path = os.path.join(WORK_DIR, job_id, f"{job_id}_credits.json")
                    cred_list = []
                    if os.path.exists(cred_path):
                        try:
                            with open(cred_path, "r", encoding="utf-8") as fc:
                                cred_list = json.load(fc).get("credits", [])
                        except:
                            pass
                    cfg = load_config()
                    mode = cfg.get("UPLOAD_METADATA_MODE", "full")
                    pkg = mg.generate_metadata_package(job_id, animal_type=cfg.get("VIDEO_MODE", "cat"), credits_list=cred_list, mode=mode)
                    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
                    with open(meta_path, "w", encoding="utf-8") as fm:
                        json.dump(pkg, fm, indent=2)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(pkg).encode())
            except Exception as e_meta:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_meta)}).encode())
            return

        elif self.path.startswith("/api/clip-bank"):
            try:
                from edl_manager import EDLManager
                em = EDLManager()
                animal = "cat"
                if "animal=" in self.path:
                    animal = self.path.split("animal=")[1].split("&")[0].lower()
                clips = em.get_available_clip_bank(animal_type=animal, limit=50)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"clips": clips, "count": len(clips)}).encode())
            except Exception as e_cb:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_cb), "clips": []}).encode())
            return

        elif self.path.startswith("/api/config/color-presets"):
            cp_path = os.path.join(BASE_DIR, "config", "color_presets.json")
            if os.path.exists(cp_path):
                with open(cp_path, "r", encoding="utf-8") as fcp:
                    data = json.load(fcp)
            else:
                data = {"presets": {}}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
            return

        elif self.path.startswith("/api/config/safe-zones"):
            sz_path = os.path.join(BASE_DIR, "config", "safe_zones.json")
            if os.path.exists(sz_path):
                with open(sz_path, "r", encoding="utf-8") as fsz:
                    data = json.load(fsz)
            else:
                data = {"platforms": {}}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
            return

        elif self.path.startswith("/api/settings/metadata-mode"):
            cfg = load_config()
            mode = cfg.get("UPLOAD_METADATA_MODE", "full")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"upload_metadata_mode": mode}).encode())
            return

        elif clean_path == "/api/feedback/stats" or clean_path.startswith("/api/feedback/stats"):
            try:
                from feedback_manager import FeedbackManager
                fm = FeedbackManager()
                stats = fm.get_stats()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "stats": stats}).encode())
            except Exception as e_fs:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_fs)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and "/clips/" in clean_path and clean_path.endswith("/alternatives"):
            parts = clean_path.split("/")
            job_id = parts[3]
            clip_id = parts[5]
            try:
                from edl_manager import EDLManager
                em = EDLManager()
                edl_data = em.get_edl(job_id)
                clips = edl_data.get("clips", [])
                target_clip = None
                for c in clips:
                    if c.get("clip_id") == clip_id:
                        target_clip = c
                        break
                alts = []
                if target_clip:
                    src = target_clip.get("source_file", "")
                    full_src = os.path.join(RAW_DIR, src) if not os.path.isabs(src) else src
                    if not os.path.exists(full_src):
                        full_src = os.path.join(OWN_FOOTAGE_DIR, src)
                    if os.path.exists(full_src):
                        from funny_event_detector import FunnyEventDetector
                        detector = FunnyEventDetector()
                        cands = detector.get_candidate_windows_for_source(full_src, max_candidates=3, target_dur=target_clip.get("duration", 10.0))
                        alts = cands
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "alternatives": alts}).encode())
            except Exception as e_alt:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_alt)}).encode())
            return

        elif self.path.startswith("/api/logs"):
            # Parse parameters: job_id, offset, seq
            offset = 0
            req_seq = 0
            target_job_id = CURRENT_JOB_ID or ""

            if "?" in self.path:
                query_str = self.path.split("?", 1)[1]
                params = urllib.parse.parse_qs(query_str)
                if "offset" in params:
                    try: offset = int(params["offset"][0])
                    except: pass
                if "seq" in params:
                    try: req_seq = int(params["seq"][0])
                    except: pass
                if "job_id" in params and params["job_id"][0]:
                    target_job_id = params["job_id"][0]

            # Locate per-job log file first.
            # CRITICAL (Fix 6d): If target_job_id is specified, DO NOT fall back to global LOG_FILE
            log_paths = []
            if target_job_id:
                log_paths.append(os.path.join(WORK_DIR, target_job_id, "job.log"))
                log_paths.append(os.path.join(OUTPUT_DIR, target_job_id, f"{target_job_id}.log"))
                log_paths.append(os.path.join(FINISHED_DIR, f"{target_job_id}.log"))
            else:
                log_paths.append(os.path.join(BASE_DIR, LOG_FILE))

            active_log_file = None
            for lp in log_paths:
                if os.path.exists(lp) and os.path.getsize(lp) > 0:
                    active_log_file = lp
                    break

            logs_text = ""
            new_offset = offset
            lines_list = []
            last_seq = req_seq

            if active_log_file and os.path.exists(active_log_file):
                try:
                    with open(active_log_file, "r", encoding="utf-8", errors="ignore") as f:
                        all_lines = f.readlines()
                    
                    # Strict monotonic line numbering per job log file (Section 5)
                    lines_list = format_log_lines_monotonic(all_lines, req_seq)
                    if lines_list:
                        last_seq = max([p["seq"] for p in lines_list])

                    # Backward compatibility raw logs chunk
                    with open(active_log_file, "r", encoding="utf-8", errors="ignore") as f:
                        f.seek(0, 2)
                        file_len = f.tell()
                        if offset <= file_len:
                            f.seek(offset)
                            logs_text = f.read()
                        else:
                            f.seek(0)
                            logs_text = f.read()
                        new_offset = file_len
                except Exception as e:
                    logs_text = f"Error reading logs: {e}"

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(json.dumps({
                "job_id": target_job_id,
                "lines": lines_list,
                "last_seq": last_seq,
                "logs": logs_text,
                "offset": new_offset
            }).encode())
            return

        elif self.path.startswith("/api/finished"):
            finished_dir = FINISHED_DIR
            files = []
            if os.path.exists(finished_dir):
                all_entries = os.listdir(finished_dir)
                for f in sorted(all_entries, key=lambda x: os.path.getmtime(os.path.join(finished_dir, x)) if os.path.exists(os.path.join(finished_dir, x)) else 0, reverse=True):
                    if f.endswith(".mp4"):
                        path = os.path.join(finished_dir, f)
                        size = os.path.getsize(path)
                        thumb_name = f.replace(".mp4", "_thumb.jpg")
                        cs_name = f.replace(".mp4", "_contact_sheet.png")
                        thumb_url = None
                        if os.path.exists(os.path.join(finished_dir, thumb_name)):
                            thumb_url = f"/finished/{thumb_name}"
                        elif os.path.exists(os.path.join(finished_dir, cs_name)):
                            thumb_url = f"/finished/{cs_name}"
                        elif os.path.exists(os.path.join(finished_dir, f.replace(".mp4", "_thumb.png"))):
                            thumb_url = f"/finished/{f.replace('.mp4', '_thumb.png')}"
                        is_169 = ("_long" in f.lower() or "16-9" in f.lower() or "landscape" in f.lower())
                        mapping_p = os.path.join(finished_dir, f.replace(".mp4", "_mapping.json"))
                        expected_dur = None
                        real_dur = None
                        clip_cnt = None
                        cfg_line = None
                        if os.path.exists(mapping_p):
                            try:
                                with open(mapping_p, "r", encoding="utf-8") as fm:
                                    md = json.load(fm)
                                    expected_dur = md.get("expected_duration_s") or md.get("expected_duration")
                                    real_dur = md.get("real_duration_s") or md.get("total_duration")
                                    clip_cnt = md.get("clip_count")
                                    cfg_line = md.get("config_line")
                            except Exception:
                                pass

                        clean_id = f.replace(".mp4", "")
                        v_match = re.search(r'_v(\d+)$', clean_id)
                        if v_match:
                            base_root = re.sub(r'_v\d+$', '', clean_id)
                            ver_num = int(v_match.group(1))
                            ver_str = f"v{ver_num}"
                        else:
                            base_root = clean_id
                            ver_num = 1
                            ver_str = "v1"

                        files.append({
                            "name": f,
                            "job_id": clean_id,
                            "base_root": base_root,
                            "version": ver_str,
                            "version_num": ver_num,
                            "sizeBytes": size,
                            "type": "video",
                            "url": f"/finished/{f}",
                            "thumbnail": thumb_url,
                            "is169": is_169,
                            "aspectRatio": "16:9" if is_169 else "9:16",
                            "duration": real_dur,
                            "expected_duration_s": expected_dur,
                            "clip_count": clip_cnt,
                            "config_line": cfg_line
                        })
                    elif f.endswith(".txt"):
                        path = os.path.join(finished_dir, f)
                        size = os.path.getsize(path)
                        files.append({
                            "name": f,
                            "sizeBytes": size,
                            "type": "metadata",
                            "url": f"/finished/{f}"
                        })

            # Calculate version groupings and is_latest for videos
            video_files = [item for item in files if item.get("type") == "video"]
            base_groups = {}
            for vf in video_files:
                broof = vf.get("base_root", vf["name"].replace(".mp4", ""))
                base_groups.setdefault(broof, []).append(vf)

            for broof, vlist in base_groups.items():
                max_v = max(item["version_num"] for item in vlist)
                sorted_vers = sorted(vlist, key=lambda x: x["version_num"])
                group_summary = [{
                    "version": item["version"],
                    "version_num": item["version_num"],
                    "job_id": item.get("job_id"),
                    "name": item["name"],
                    "url": item["url"],
                    "is_latest": (item["version_num"] == max_v)
                } for item in sorted_vers]

                for item in vlist:
                    item["is_latest"] = (item["version_num"] == max_v)
                    item["version_group"] = group_summary
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"files": files}).encode())
            return

        elif self.path == "/lion_logo.png":
            filepath = os.path.join(BASE_DIR, "lion_logo.png")
            if os.path.exists(filepath):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(os.path.getsize(filepath)))
                self.end_headers()
                try:
                    with open(filepath, "rb") as f:
                        self.wfile.write(f.read())
                except:
                    pass
                return
            else:
                self.send_error(404, "Logo file not found")
                return

        elif self.path in ("/proposal", "/proposal.html"):
            filepath = os.path.join(BASE_DIR, "proposal.html")
            if os.path.exists(filepath):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(os.path.getsize(filepath)))
                self.end_headers()
                try:
                    with open(filepath, "rb") as f:
                        self.wfile.write(f.read())
                except:
                    pass
                return
            else:
                self.send_error(404, "Proposal file not found")
                return

        elif self.path in ("/proposal.pdf", "/LionReel_Studio_Project_Proposal.pdf"):
            filepath = os.path.join(BASE_DIR, "LionReel_Studio_Project_Proposal.pdf")
            if os.path.exists(filepath):
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(os.path.getsize(filepath)))
                self.end_headers()
                try:
                    with open(filepath, "rb") as f:
                        self.wfile.write(f.read())
                except:
                    pass
                return
            else:
                self.send_error(404, "Proposal PDF file not found")
                return


        elif self.path.startswith("/finished/") or self.path.startswith("/raw/") or self.path.startswith("/work/"):
            # Serve files from finished, raw, or work directory directly with full Range support
            clean_path = self.path.split("?")[0].split("#")[0]
            if clean_path.startswith("/finished/"):
                filename = urllib.parse.unquote(clean_path.replace("/finished/", ""))
                filepath = os.path.join(FINISHED_DIR, filename)
            elif clean_path.startswith("/raw/"):
                filename = urllib.parse.unquote(clean_path.replace("/raw/", ""))
                filepath = os.path.join(RAW_DIR, filename)
            else: # /work/
                filename = urllib.parse.unquote(clean_path.replace("/work/", ""))
                filepath = os.path.join(WORK_DIR, filename)

            if os.path.exists(filepath) and os.path.isfile(filepath):
                file_size = os.path.getsize(filepath)
                lower = filename.lower()
                content_type = "application/octet-stream"
                if lower.endswith(".mp4"):
                    content_type = "video/mp4"
                elif lower.endswith(".webm"):
                    content_type = "video/webm"
                elif lower.endswith(".jpg") or lower.endswith(".jpeg"):
                    content_type = "image/jpeg"
                elif lower.endswith(".png"):
                    content_type = "image/png"
                elif lower.endswith(".json"):
                    content_type = "application/json"
                elif lower.endswith(".txt"):
                    content_type = "text/plain"

                range_header = self.headers.get("Range")
                if range_header and lower.endswith(".mp4") and "bytes=" in range_header:
                    try:
                        bytes_range = range_header.split("=")[1].strip()
                        parts = bytes_range.split("-")
                        start = int(parts[0]) if parts[0] else 0
                        end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
                        if end >= file_size:
                            end = file_size - 1
                        length = end - start + 1

                        self.send_response(206)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                        self.send_header("Content-Length", str(length))
                        self.end_headers()

                        with open(filepath, "rb") as f:
                            f.seek(start)
                            bytes_to_send = length
                            chunk_size = 64 * 1024
                            while bytes_to_send > 0:
                                read_now = min(chunk_size, bytes_to_send)
                                data = f.read(read_now)
                                if not data:
                                    break
                                self.wfile.write(data)
                                bytes_to_send -= len(data)
                        return
                    except Exception:
                        return

                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(file_size))
                self.end_headers()
                try:
                    with open(filepath, "rb") as f:
                        while True:
                            chunk = f.read(64 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except:
                    pass
                return
            else:
                self.send_error(404, "File not found")
                return

        # Default static file routing
        if self.path == "/" or self.path == "":
            self.path = "/gui/index.html"
        elif not self.path.startswith("/gui/"):
            self.path = f"/gui{self.path}"

        # Clean double slashes
        self.path = self.path.replace("//", "/")
        
        # Call super method to serve standard files
        return super().do_GET()

    def do_POST(self):
        global RUNNING_PROCESS, RUNNING_PROCESS_START_TIME, LAST_EXIT_CODE, CURRENT_JOB_ID
        clean_path = self.path.split("?")[0]
        
        content_length = int(self.headers.get('Content-Length', 0) or 0)

        # Handle binary streaming uploads directly from self.rfile
        if self.path.startswith("/api/upload"):
            try:
                filename = ""
                if "filename=" in self.path:
                    import urllib.parse
                    filename = urllib.parse.unquote(self.path.split("filename=")[1].split("&")[0])
                if not filename:
                    filename = self.headers.get("X-File-Name", "")
                    if filename:
                        import urllib.parse
                        filename = urllib.parse.unquote(filename)
                if not filename:
                    filename = f"upload_{int(time.time())}.mp4"
                
                filename = os.path.basename(filename)
                os.makedirs(OWN_FOOTAGE_DIR, exist_ok=True)
                os.makedirs(RAW_DIR, exist_ok=True)
                
                target_own = os.path.join(OWN_FOOTAGE_DIR, filename)
                target_raw = os.path.join(RAW_DIR, filename)
                
                remaining = content_length
                chunk_size = 64 * 1024
                with open(target_own, "wb") as f_out:
                    while remaining > 0:
                        chunk = self.rfile.read(min(remaining, chunk_size))
                        if not chunk:
                            break
                        f_out.write(chunk)
                        remaining -= len(chunk)
                
                try:
                    import shutil
                    shutil.copyfile(target_own, target_raw)
                except:
                    pass

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "filename": filename,
                    "sizeBytes": os.path.getsize(target_own) if os.path.exists(target_own) else 0
                }).encode())
                return
            except Exception as e_up:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_up)}).encode())
                return

        # Standard JSON/text payload endpoints
        post_data = self.rfile.read(content_length).decode('utf-8', errors='replace') if content_length > 0 else ""
        
        if self.path.startswith("/api/config"):
            try:
                cfg = json.loads(post_data)
                success = save_config(cfg)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success}).encode())
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(e).encode())
            return

        elif self.path.startswith("/api/delete-file"):
            try:
                params = json.loads(post_data) if post_data else {}
                filename = params.get("filename", "")
                if not filename:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Missing filename parameter"}).encode())
                    return

                success, deleted_files, err_msg = delete_compilation_files(filename)
                if success:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": True, 
                        "filename": filename, 
                        "deleted": deleted_files,
                        "message": f"Successfully deleted {filename} and all associated files from disk."
                    }).encode())
                else:
                    self.send_response(409)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False, 
                        "filename": filename, 
                        "deleted": deleted_files, 
                        "error": err_msg or "Failed to delete file from disk. It may be locked by another program."
                    }).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/edits"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                body = json.loads(post_data) if post_data else {}
                from edl_manager import EDLManager
                em = EDLManager()
                saved_edl = em.save_edl(job_id, body)
                resp_bytes = json.dumps({"success": True, "edl": saved_edl}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
            except Exception as e_pedl:
                err_bytes = json.dumps({"success": False, "error": str(e_pedl)}).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_bytes)))
                self.wfile.write(err_bytes)
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/rerender"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                body = json.loads(post_data) if post_data else {}
                from edl_manager import EDLManager
                em = EDLManager()
                regen_meta = bool(body.get("regenerate_metadata", False))
                # 1. Create child job EDL
                edl_in = body.get("edl") or em.get_edl(job_id)
                child_prep = em.create_child_job_edl(job_id, edl_in)
                child_job_id = child_prep["child_job_id"]
                # 2. Render child job
                res = em.rerender_child_job(child_job_id, regenerate_metadata=regen_meta)
                resp_bytes = json.dumps(res).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
            except Exception as e_rrd:
                err_bytes = json.dumps({"success": False, "error": str(e_rrd)}).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_bytes)))
                self.end_headers()
                self.wfile.write(err_bytes)
            return

        elif self.path.startswith("/api/jobs/") and "/edits/check_framing" in self.path:
            parts = self.path.split("/")
            job_id = parts[3]
            try:
                body = json.loads(post_data) if post_data else {}
                src = body.get("source_file", "")
                s_start = float(body.get("start_sec", 0.0))
                s_dur = float(body.get("duration_sec", 10.0))
                from edl_manager import EDLManager
                em = EDLManager()
                res = em.check_framing(src, s_start, s_dur)
                resp_bytes = json.dumps(res).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
            except Exception as e_cf:
                err_bytes = json.dumps({"passed": False, "score": 0.0, "error": str(e_cf)}).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_bytes)))
                self.end_headers()
                self.wfile.write(err_bytes)
            return

        elif self.path.startswith("/api/jobs/") and "/edits/replace_clip" in self.path:
            parts = self.path.split("/")
            job_id = parts[3]
            try:
                body = json.loads(post_data) if post_data else {}
                c_idx = int(body.get("clip_index", 0))
                rep_id = str(body.get("replacement_clip_id", ""))
                from edl_manager import EDLManager
                em = EDLManager()
                updated_edl = em.replace_clip_in_edl(job_id, c_idx, rep_id)
                resp_bytes = json.dumps({"success": True, "edl": updated_edl}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
            except Exception as e_rc:
                err_bytes = json.dumps({"success": False, "error": str(e_rc)}).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_bytes)))
                self.end_headers()
                self.wfile.write(err_bytes)
            return

        elif self.path.startswith("/api/jobs/") and "/edits/proxy_preview" in self.path:
            parts = self.path.split("/")
            job_id = parts[3]
            try:
                body = json.loads(post_data) if post_data else {}
                cid = str(body.get("clip_id", ""))
                s_start = float(body.get("start_s", 0.0))
                s_dur = float(body.get("dur_s", 5.0))
                speed = float(body.get("speed", 1.0))
                preset = str(body.get("color_preset", "natural"))
                strength = float(body.get("color_strength", 0.6))
                from edl_manager import EDLManager
                em = EDLManager()
                proxy_path = em.render_proxy_preview(job_id, cid, s_start, s_dur, speed=speed, color_preset=preset, color_strength=strength)
                proxy_url = f"/work/{job_id}/preview_{cid}.mp4?t={int(time.time()*1000)}"
                resp_bytes = json.dumps({"success": True, "proxy_url": proxy_url}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
            except Exception as e_pp:
                err_bytes = json.dumps({"success": False, "error": str(e_pp)}).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_bytes)))
                self.end_headers()
                self.wfile.write(err_bytes)
            return

        elif self.path.startswith("/api/jobs/") and "/metadata/generate" in self.path:
            parts = self.path.split("/")
            job_id = parts[3]
            try:
                body = json.loads(post_data) if post_data else {}
                a_type = body.get("animal_type", "cat")
                m_mode = body.get("mode", "full")
                from metadata_generator import MetadataGenerator
                mg = MetadataGenerator()
                cred_path = os.path.join(WORK_DIR, job_id, f"{job_id}_credits.json")
                cred_list = []
                if os.path.exists(cred_path):
                    try:
                        with open(cred_path, "r", encoding="utf-8") as fc:
                            cred_list = json.load(fc).get("credits", [])
                    except: pass
                pkg = mg.generate_metadata_package(job_id, animal_type=a_type, credits_list=cred_list, mode=m_mode)
                meta_path = os.path.join(WORK_DIR, job_id, "metadata.json")
                with open(meta_path, "w", encoding="utf-8") as fm:
                    json.dump(pkg, fm, indent=2)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(pkg).encode())
            except Exception as e_mgen:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_mgen)}).encode())
            return

        elif self.path.startswith("/api/jobs/") and "/metadata/save" in self.path:
            parts = self.path.split("/")
            job_id = parts[3]
            try:
                body = json.loads(post_data) if post_data else {}
                meta_path = os.path.join(WORK_DIR, job_id, "metadata.json")
                with open(meta_path, "w", encoding="utf-8") as fm:
                    json.dump(body, fm, indent=2)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "metadata": body}).encode())
            except Exception as e_msav:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_msav)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and "/clips/" in clean_path and clean_path.endswith("/feedback"):
            parts = clean_path.split("/")
            job_id = parts[3]
            clip_id = parts[5]
            try:
                body = json.loads(post_data) if post_data else {}
                from feedback_manager import FeedbackManager
                fm = FeedbackManager()
                src_file = body.get("source_file", "")
                full_src = os.path.join(RAW_DIR, src_file) if not os.path.isabs(src_file) else src_file
                if not os.path.exists(full_src):
                    full_src = os.path.join(OWN_FOOTAGE_DIR, src_file)
                res = fm.record_feedback(
                    job_id=job_id,
                    clip_id=clip_id,
                    source_file=full_src if os.path.exists(full_src) else src_file,
                    rating=body.get("rating", "positive"),
                    reasons=body.get("reasons", []),
                    marked_peak_s=body.get("marked_peak_s"),
                    window_start_s=float(body.get("start_s", 0.0)),
                    window_end_s=float(body.get("end_s", 10.0)),
                    feedback_type=body.get("feedback_type", "explicit")
                )
                resp_bytes = json.dumps({"success": True, "data": res}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
            except Exception as e_fb:
                err_bytes = json.dumps({"success": False, "error": str(e_fb)}).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_bytes)))
                self.end_headers()
                self.wfile.write(err_bytes)
            return

        elif clean_path == "/api/feedback/retrain" or clean_path.startswith("/api/feedback/retrain"):
            try:
                from feedback_manager import FeedbackManager
                fm = FeedbackManager()
                train_res = fm.train_model()
                resp_bytes = json.dumps({"success": True, "result": train_res}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
            except Exception as e_tr:
                err_bytes = json.dumps({"success": False, "error": str(e_tr)}).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_bytes)))
                self.end_headers()
                self.wfile.write(err_bytes)
            return

        elif self.path.startswith("/api/settings/metadata-mode"):
            try:
                body = json.loads(post_data) if post_data else {}
                mode = body.get("upload_metadata_mode", "full")
                cfg = load_config()
                cfg["UPLOAD_METADATA_MODE"] = mode
                save_config(cfg)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "upload_metadata_mode": mode}).encode())
            except Exception as e_smm:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_smm)}).encode())
            return

        elif self.path.startswith("/api/clear-finished"):
            try:
                deleted_all = []
                failed_all = []
                # 1. FINISHED_DIR: delete all files
                if os.path.exists(FINISHED_DIR):
                    for f in os.listdir(FINISHED_DIR):
                        fp = os.path.join(FINISHED_DIR, f)
                        if os.path.isfile(fp):
                            stem = os.path.splitext(f)[0]
                            # Clean corresponding output/<stem> if video
                            if f.endswith(".mp4"):
                                out_job_dir = os.path.join(OUTPUT_DIR, stem)
                                if os.path.exists(out_job_dir):
                                    robust_remove(out_job_dir)
                            if robust_remove(fp):
                                deleted_all.append(f"finished/{f}")
                            else:
                                failed_all.append(f"finished/{f}")
                
                # 2. Clear job_result.json
                if os.path.exists(JOB_RESULT_FILE):
                    robust_remove(JOB_RESULT_FILE)
                
                # 3. Clear output_registry in ledger & release clips
                try:
                    from clip_ledger import ClipLedger
                    ledger = ClipLedger()
                    with ledger._get_conn() as conn:
                        conn.execute("DELETE FROM output_registry")
                        conn.execute("UPDATE clips SET times_used = 0, last_used_short_id = NULL, pending_short_id = NULL")
                        conn.commit()
                except Exception as e_led:
                    print(f"Notice: ledger clear: {e_led}")

                if failed_all:
                    self.send_response(409)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False, 
                        "error": f"Some files could not be deleted because they are locked: {', '.join(failed_all)}",
                        "count": len(deleted_all)
                    }).encode())
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "count": len(deleted_all)}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

        elif self.path.startswith("/api/clear-raw"):
            try:
                raw_dir = RAW_DIR
                if os.path.exists(raw_dir):
                    for f in os.listdir(raw_dir):
                        path = os.path.join(raw_dir, f)
                        if os.path.isfile(path) and (f.endswith(".mp4") or f.endswith(".part") or f.endswith(".webm") or f.endswith(".mkv") or f.endswith(".tmp")):
                            try: os.remove(path)
                            except: pass
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

        elif self.path.startswith("/api/open-folder"):
            try:
                os.makedirs(FINISHED_DIR, exist_ok=True)
                if os.name == "nt":
                    os.startfile(FINISHED_DIR)
                else:
                    subprocess.Popen(["xdg-open", FINISHED_DIR])
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "path": FINISHED_DIR}).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

        elif self.path.startswith("/api/reset-history") or self.path.startswith("/api/clean-all"):
            LAST_EXIT_CODE = None
            try:
                # 1. Reset clip history tracking files so fresh clips are selected without repeating
                for h_file in ["used_videos.txt", "used_metadata.json", "used_own_footage.txt", "job_result.json"]:
                    hp = os.path.join(BASE_DIR, h_file)
                    if os.path.exists(hp):
                        try: os.remove(hp)
                        except: pass
                
                # 2. Reset log file to a clean state
                try:
                    with open(LOG_FILE, "w", encoding="utf-8") as f_log:
                        f_log.write("=== LionReel Studio Cleaned & History Reset ===\n")
                except:
                    pass

                # 3. Clean temporary moviepy crash fragments and scratch files in BASE_DIR
                try:
                    for f in os.listdir(BASE_DIR):
                        if "TEMP_MPY_" in f or f.endswith(".part") or (f.startswith("scratch_") and f.endswith(".mp4")):
                            fp = os.path.join(BASE_DIR, f)
                            if os.path.isfile(fp):
                                try: os.remove(fp)
                                except: pass
                except:
                    pass

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True, 
                    "message": "Clip history, tracking files, and session caches reset successfully. All finished videos and source footage are safely preserved."
                }).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

        elif self.path.startswith("/api/purge-temp-files") or self.path.startswith("/api/clean-temp"):
            LAST_EXIT_CODE = None
            try:
                removed_files = []
                freed_bytes = 0

                # 1. Clean temporary moviepy crash fragments and scratch videos in BASE_DIR
                try:
                    for f in os.listdir(BASE_DIR):
                        is_scratch = f.startswith("scratch_") and f.lower().endswith((".mp4", ".avi", ".mov", ".mkv", ".webm"))
                        is_temp = "TEMP_MPY_" in f or f.lower().endswith((".part", ".tmp", ".temp"))
                        if is_scratch or is_temp:
                            fp = os.path.join(BASE_DIR, f)
                            if os.path.isfile(fp):
                                try:
                                    sz = os.path.getsize(fp)
                                    os.remove(fp)
                                    removed_files.append(f)
                                    freed_bytes += sz
                                except Exception as e_del:
                                    print(f"Error removing {fp}: {e_del}")
                except Exception as e_scan:
                    print(f"Error scanning BASE_DIR: {e_scan}")

                # 2. In FINISHED_DIR: Keep ONLY 1 most recent finished video, delete all other old videos permanently!
                try:
                    if os.path.exists(FINISHED_DIR):
                        all_vids = []
                        for f in os.listdir(FINISHED_DIR):
                            fp = os.path.join(FINISHED_DIR, f)
                            if os.path.isfile(fp) and f.lower().endswith((".mp4", ".mov", ".mkv", ".webm")):
                                try:
                                    all_vids.append((fp, os.path.getmtime(fp), f))
                                except:
                                    pass

                        all_vids.sort(key=lambda x: x[1], reverse=True)
                        keep_video_path = all_vids[0][0] if all_vids else None
                        keep_video_file = all_vids[0][2] if all_vids else None
                        keep_base = os.path.splitext(keep_video_file)[0] if keep_video_file else None

                        # Delete all older finished videos permanently (keep only 1 video)
                        for old_vp, _, old_vf in all_vids[1:]:
                            try:
                                sz = os.path.getsize(old_vp) if os.path.exists(old_vp) else 0
                                _, del_f, _ = delete_compilation_files(old_vf)
                                removed_files.extend(del_f)
                                freed_bytes += sz
                            except Exception as e_del:
                                print(f"Error removing old video {old_vp}: {e_del}")

                        # Identify matching metadata and thumbnail for the 1 preserved video
                        expected_keep_files = set()
                        if keep_video_file:
                            expected_keep_files.add(keep_video_file)
                            for thumb_ext in [".jpg", ".png", ".jpeg"]:
                                expected_keep_files.add(f"{keep_base}_thumb{thumb_ext}")
                            expected_keep_files.add(f"{keep_base}.txt")
                            # Match lion_metadata pattern
                            m_match = re.search(r"lion_([a-zA-Z0-9_]+)_(\d+.*)\.mp4", keep_video_file)
                            if m_match:
                                expected_keep_files.add(f"lion_metadata_{m_match.group(1)}_{m_match.group(2)}.txt")
                                expected_keep_files.add(f"lion_metadata_{m_match.group(1)}_{m_match.group(2).replace('_long', '')}.txt")

                        # Delete all other thumbnails, metadata, and leftover finished files
                        for f in os.listdir(FINISHED_DIR):
                            fp = os.path.join(FINISHED_DIR, f)
                            if not os.path.isfile(fp):
                                continue
                            if keep_base and f.startswith(keep_base):
                                continue # Preserve latest video and all its artifacts
                            if f in expected_keep_files:
                                continue # Preserve 1 latest video and its assets
                            try:
                                sz = os.path.getsize(fp)
                                if robust_remove(fp):
                                    removed_files.append(f"finished/{f}")
                                    freed_bytes += sz
                            except Exception as e_del:
                                print(f"Error removing {fp}: {e_del}")
                except Exception as e_scan:
                    print(f"Error scanning FINISHED_DIR: {e_scan}")

                # 3. Clean temporary intermediate files in RAW_DIR (preserving source videos like cache_* and raw_*)
                try:
                    if os.path.exists(RAW_DIR):
                        for f in os.listdir(RAW_DIR):
                            # Strictly protect source footage
                            if f.startswith("cache_") or f.startswith("raw_"):
                                continue
                            # Only purge intermediate cut/test/concat files
                            if (f.startswith("cut_") or f.startswith("capcut_") or 
                                f.startswith("assembled_") or f.startswith("test_") or 
                                f.startswith("v97_") or f.startswith("cand_") or 
                                f.startswith("concat_") or f.startswith("master_audio_")):
                                fp = os.path.join(RAW_DIR, f)
                                if os.path.isfile(fp):
                                    try:
                                        sz = os.path.getsize(fp)
                                        os.remove(fp)
                                        removed_files.append(f"raw/{f}")
                                        freed_bytes += sz
                                    except Exception as e_del:
                                        print(f"Error removing {fp}: {e_del}")
                except Exception as e_scan:
                    print(f"Error scanning RAW_DIR: {e_scan}")

                # 3b. Clean isolated job directories in WORK_DIR
                try:
                    if os.path.exists(WORK_DIR):
                        for d in os.listdir(WORK_DIR):
                            dp = os.path.join(WORK_DIR, d)
                            if os.path.isdir(dp):
                                try:
                                    shutil.rmtree(dp, ignore_errors=True)
                                    removed_files.append(f"work/{d}")
                                except Exception:
                                    pass
                except Exception as e_work:
                    print(f"Error cleaning WORK_DIR: {e_work}")

                # 4. Clean scratch directory
                try:
                    scratch_dir = os.path.join(BASE_DIR, "scratch")
                    if os.path.exists(scratch_dir):
                        for root, dirs, files in os.walk(scratch_dir, topdown=False):
                            for f in files:
                                fp = os.path.join(root, f)
                                try:
                                    sz = os.path.getsize(fp)
                                    os.remove(fp)
                                    freed_bytes += sz
                                    removed_files.append(f"scratch/{f}")
                                except:
                                    pass
                            for d in dirs:
                                try:
                                    os.rmdir(os.path.join(root, d))
                                except:
                                    pass
                except Exception as e_scratch:
                    print(f"Error cleaning scratch_dir: {e_scratch}")

                # 4. Reset history tracking files & logs
                for h_file in ["used_videos.txt", "used_metadata.json", "used_own_footage.txt", "job_result.json"]:
                    hp = os.path.join(BASE_DIR, h_file)
                    if os.path.exists(hp):
                        try:
                            sz = os.path.getsize(hp)
                            os.remove(hp)
                            removed_files.append(h_file)
                            freed_bytes += sz
                        except: pass

                try:
                    with open(LOG_FILE, "w", encoding="utf-8") as f_log:
                        f_log.write("=== Workspace Cleaned: Temp, Thumbnails & Old Files Purged ===\n")
                except:
                    pass

                freed_mb = round(freed_bytes / (1024 * 1024), 2)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "removed_count": len(removed_files),
                    "freed_bytes": freed_bytes,
                    "freed_mb": freed_mb,
                    "removed_files": removed_files,
                    "message": f"Successfully purged {len(removed_files)} files and freed {freed_mb} MB of disk space."
                }).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

        elif self.path.startswith("/api/clear-error") or self.path.startswith("/api/dismiss-error"):
            LAST_EXIT_CODE = None
            if os.path.exists(JOB_RESULT_FILE):
                try: os.remove(JOB_RESULT_FILE)
                except: pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode())
            return

        elif self.path.startswith("/api/start"):
            is_running = RUNNING_PROCESS is not None and RUNNING_PROCESS.poll() is None
            if is_running:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": "Already running", "job_id": CURRENT_JOB_ID}).encode())
                return
            
            LAST_EXIT_CODE = None
            if os.path.exists(JOB_RESULT_FILE):
                try: os.remove(JOB_RESULT_FILE)
                except: pass

            cfg = {}
            if post_data:
                try:
                    cfg = json.loads(post_data)
                except Exception as e_cfg:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": f"Invalid JSON payload: {e_cfg}",
                        "reason_code": "INVALID_ARGUMENTS"
                    }).encode())
                    return

            import job_options
            is_valid, norm_cfg, err_msg = job_options.normalize_job_options(cfg)
            if not is_valid:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": err_msg,
                    "reason_code": "INVALID_ARGUMENTS"
                }).encode())
                return

            # Save normalized config
            cfg["LAYOUT_MODE"] = norm_cfg["layout"]
            cfg["VIDEO_TYPE"] = norm_cfg["type"]
            cfg["ANIMAL_MODE"] = norm_cfg["mode"]
            save_config(cfg)

            # Generate unique job_id (timestamp + uuid)
            ts_str = time.strftime('%Y%m%d_%H%M%S')
            CURRENT_JOB_ID = f"lionreel_{norm_cfg['mode']}_{ts_str}_{uuid.uuid4().hex[:8]}"

            # Write initial state to JOB_RESULT_FILE
            try:
                with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_init:
                    json.dump({
                        "job_id": CURRENT_JOB_ID,
                        "status": "running",
                        "success": None
                    }, f_init)
            except Exception:
                pass

            # Create per-job work directory on local drive
            work_job_dir = os.path.join(WORK_DIR, CURRENT_JOB_ID)
            os.makedirs(work_job_dir, exist_ok=True)
            job_log_file = os.path.join(work_job_dir, "job.log")

            # Write immutable job configuration snapshot
            import job_options
            job_options.load_or_verify_job_config(CURRENT_JOB_ID, norm_cfg)

            # Copy active draft EDL into the new job directory if present so edits are honored
            draft_edl = os.path.join(WORK_DIR, "active_draft", "edl.json")
            job_edl = os.path.join(work_job_dir, "edl.json")
            if os.path.exists(draft_edl):
                try:
                    shutil.copy2(draft_edl, job_edl)
                except Exception as e_edl_cp:
                    print(f"Notice: Failed to copy draft EDL: {e_edl_cp}")

            launch_banner = f"=== Launching LionReel Automation Script (Job: {CURRENT_JOB_ID}) ===\n"

            # Clear and initialize log file
            try:
                with open(job_log_file, "w", encoding="utf-8") as f_jlog:
                    f_jlog.write(launch_banner)
            except Exception:
                pass

            # Spawn Python script using local SSD virtual environment (Section 4)
            try:
                local_venv_py = r"C:\LionReel\venv\Scripts\python.exe"
                if os.path.exists(local_venv_py):
                    python_exe = local_venv_py
                else:
                    python_exe = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
                    if not os.path.exists(python_exe):
                        python_exe = sys.executable or "python"
                
                script_to_run = "lion_automate_v97.py"
                if not os.path.exists(os.path.join(BASE_DIR, script_to_run)):
                    script_to_run = "lion_automate.py"

                RUNNING_PROCESS_START_TIME = time.time()
                cli_args = job_options.build_cli_args(norm_cfg, CURRENT_JOB_ID, RUNNING_PROCESS_START_TIME)

                # Pre-validate with parser before spawning
                parser = job_options.build_arg_parser()
                try:
                    parser.parse_args(cli_args)
                except SystemExit:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": "CLI arguments rejected by parser validation",
                        "reason_code": "INVALID_ARGUMENTS"
                    }).encode())
                    return

                cmd = [python_exe, "-u", script_to_run] + cli_args

                # Run script in background and redirect output to per-job log file
                log_fd = open(job_log_file, "a", encoding="utf-8", errors="ignore")
                RUNNING_PROCESS = subprocess.Popen(
                    cmd,
                    stdout=log_fd,
                    stderr=log_fd,
                    cwd=BASE_DIR,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "job_id": CURRENT_JOB_ID}).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

        elif self.path.startswith("/api/stop"):
            stopped_pids = []
            if RUNNING_PROCESS is not None:
                try:
                    pid_to_kill = RUNNING_PROCESS.pid
                    stopped_pids.append(pid_to_kill)
                    if os.name == 'nt':
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid_to_kill)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        RUNNING_PROCESS.terminate()
                except Exception as e_k:
                    print(f"Error terminating RUNNING_PROCESS: {e_k}")
                RUNNING_PROCESS = None
                RUNNING_PROCESS_START_TIME = None

            # Clean up job lock and orphan PID if recorded
            if CURRENT_JOB_ID:
                job_lock = os.path.join(WORK_DIR, CURRENT_JOB_ID, ".lock")
                if os.path.exists(job_lock):
                    try:
                        with open(job_lock, "r") as f_lk:
                            lk_pid = int(f_lk.read().strip())
                        if lk_pid not in stopped_pids:
                            if os.name == 'nt':
                                subprocess.run(["taskkill", "/F", "/T", "/PID", str(lk_pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        os.remove(job_lock)
                    except Exception:
                        pass
                # Release ledger reservation
                try:
                    from clip_ledger import ClipLedger
                    ClipLedger().release_reservation(CURRENT_JOB_ID)
                except Exception:
                    pass

            # Append message to log
            try:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write("\n=== Generation Stopped by User ===\n")
            except Exception:
                pass

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode())
            return

        elif self.path.startswith("/api/job-action") or self.path.startswith("/api/jobs/"):
            try:
                target_job = None
                action = None
                if "/api/jobs/" in self.path:
                    parts = self.path.strip("/").split("/")
                    if len(parts) >= 4:
                        target_job = parts[2]
                        sub_action = parts[3]
                        if sub_action == "build_from_ready":
                            action = "make_shorter"
                        elif sub_action == "cancel":
                            action = "cancel"
                if not action and post_data:
                    try:
                        p_data = json.loads(post_data)
                        action = p_data.get("action")
                        target_job = p_data.get("job_id") or target_job
                    except Exception:
                        pass

                target_job = target_job or CURRENT_JOB_ID

                if target_job and action:
                    import job_options
                    job_options.record_user_action(target_job, action, triggered_by="ui")

                if action in ("make_shorter", "build_from_ready", "reduce_to_pool", "reduce"):
                    ready_clips = 0
                    cp_path = os.path.join(WORK_DIR, target_job, "checkpoint.json") if target_job else None
                    if cp_path and os.path.exists(cp_path):
                        try:
                            with open(cp_path, "r", encoding="utf-8") as f_cp:
                                ready_clips = json.load(f_cp).get("got_clips", 0)
                        except Exception:
                            pass
                    if not ready_clips and os.path.exists(JOB_RESULT_FILE):
                        try:
                            with open(JOB_RESULT_FILE, "r", encoding="utf-8") as f_jr:
                                ready_clips = json.load(f_jr).get("clips_ready", 0)
                        except Exception:
                            pass

                    if ready_clips < 1:
                        ready_clips = 2

                    # If process is currently alive and sleeping in waiting loop, it will consume action.json directly!
                    if RUNNING_PROCESS is not None and RUNNING_PROCESS.poll() is None:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": True, "job_id": target_job, "action": action, "active": True}).encode())
                        return

                    local_venv_py = r"C:\LionReel\venv\Scripts\python.exe"
                    py_exe = local_venv_py if os.path.exists(local_venv_py) else (sys.executable or "python")
                    job_log_file = os.path.join(WORK_DIR, target_job, "job.log") if target_job else LOG_FILE
                    log_fd = open(job_log_file, "a", encoding="utf-8", errors="ignore")

                    import job_options
                    try:
                        job_cfg = job_options.load_or_verify_job_config(target_job)
                    except Exception:
                        job_cfg = {"mode": "cat", "type": "compilation", "layout": "smart_crop"}

                    is_comp_job = str(job_cfg.get("type", "")).lower() in ("compilation", "long")
                    cmd = [
                        py_exe, "-u", "lion_automate_v97.py",
                        "--job-id", target_job,
                        "--mode", str(job_cfg.get("mode", "cat")),
                        "--type", str(job_cfg.get("type", "compilation")),
                        "--layout", str(job_cfg.get("layout", "smart_crop")),
                        "--clips", str(ready_clips)
                    ]
                    if not is_comp_job or ready_clips >= 10:
                        cmd.append("--allow-shorter")
                    RUNNING_PROCESS_START_TIME = time.time()
                    CURRENT_JOB_ID = target_job
                    RUNNING_PROCESS = subprocess.Popen(
                        cmd,
                        stdout=log_fd,
                        stderr=log_fd,
                        cwd=BASE_DIR,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "job_id": target_job, "action": "make_shorter", "clips": ready_clips}).encode())
                    return

                elif action in ("keep_searching", "keep_waiting"):
                    from harvest_worker import trigger_background_harvest_if_needed
                    trigger_background_harvest_if_needed(animal_mode="cat", target_clips_needed=100)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "action": "keep_waiting"}).encode())
                    return

                elif action == "cancel":
                    if RUNNING_PROCESS:
                        try:
                            if os.name == 'nt':
                                subprocess.run(["taskkill", "/F", "/T", "/PID", str(RUNNING_PROCESS.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            else:
                                RUNNING_PROCESS.terminate()
                        except Exception:
                            pass
                        RUNNING_PROCESS = None
                    try:
                        with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_can:
                            json.dump({
                                "job_id": target_job,
                                "status": "error",
                                "reason_code": "CANCELLED",
                                "message": "Job cancelled by user",
                                "exit_code": 0
                            }, f_can, indent=2)
                    except Exception:
                        pass
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "action": "cancel"}).encode())
                    return
            except Exception as e_act:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_act)}).encode())
                return

        elif self.path.startswith("/api/harvest/start") or self.path.startswith("/api/harvest-start"):
            try:
                from harvest_worker import trigger_background_harvest_if_needed
                animal = "cat"
                if post_data:
                    try:
                        p_data = json.loads(post_data)
                        animal = p_data.get("animal", "cat")
                    except Exception:
                        pass
                trigger_background_harvest_if_needed(animal_mode=animal, min_low_water_mark=9999)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": "Harvest started", "animal": animal}).encode())
                return
            except Exception as e_hstart:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_hstart)}).encode())
                return

        elif self.path.startswith("/api/create-shortcut"):
            if os.name != 'nt':
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "Creating desktop shortcuts is only supported on Windows. Since this is running in the cloud (Linux/Codespaces), please bookmark this webpage in your browser instead!"}).encode())
                return
            try:
                params = json.loads(post_data)
                hotkey = params.get("hotkey", "CTRL+ALT+L").upper()
                
                # 1. Determine pythonw.exe path to run silently
                workspace_dir = os.path.dirname(os.path.abspath(__file__))
                current_exe = sys.executable
                if current_exe.endswith("python.exe"):
                    pythonw_exe = current_exe.replace("python.exe", "pythonw.exe")
                elif current_exe.endswith("python"):
                    pythonw_exe = current_exe + "w"
                else:
                    pythonw_exe = "pythonw.exe"
                
                # 2. Ensure ICO file exists
                ico_exists = ensure_icon()
                ico_path = os.path.join(workspace_dir, "lion_logo.ico") if ico_exists else ""
                
                # 3. Create Windows Shortcut using PowerShell targeting pythonw.exe
                ps_command = f"""
                $DesktopPath = [Environment]::GetFolderPath('Desktop')
                $ShortcutPath = Join-Path $DesktopPath "LionReel Studio.lnk"
                $WScriptShell = New-Object -ComObject WScript.Shell
                $Shortcut = $WScriptShell.CreateShortcut($ShortcutPath)
                $Shortcut.TargetPath = "{pythonw_exe}"
                $Shortcut.Arguments = "web_server.py"
                $Shortcut.WorkingDirectory = "{workspace_dir}"
                """
                if ico_exists:
                    # Windows paths in PowerShell need backslash escaping or quote wrapping
                    ico_path_esc = ico_path.replace('"', '`"')
                    ps_command += f'\n$Shortcut.IconLocation = "{ico_path_esc}"'
                
                if hotkey:
                    ps_command += f'\n$Shortcut.Hotkey = "{hotkey}"'
                
                ps_command += '\n$Shortcut.Description = "Launch LionReel Dashboard Server"\n$Shortcut.Save()'
                
                system_root = os.environ.get("SystemRoot", "C:\\Windows")
                powershell_exe = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
                if not os.path.exists(powershell_exe):
                    powershell_exe = "powershell.exe"
                
                res = subprocess.run([powershell_exe, "-NoProfile", "-Command", ps_command], capture_output=True, text=True)
                
                if res.returncode == 0:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "message": f"Shortcut created on Desktop (Hotkey: {hotkey})"}).encode())
                else:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": res.stderr}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = False if os.name == "nt" else True

if __name__ == "__main__":
    if "--test-import" in sys.argv:
        from source_utils import get_pipeline_build_id
        import cv2, numpy
        print(f"Imports verified successfully under {sys.executable} (Python {sys.version.split()[0]})")
        sys.exit(0)
    acquire_server_lock()
    # Ensure raw and finished folders exist
    os.makedirs(FINISHED_DIR, exist_ok=True)
    os.makedirs(RAW_DIR, exist_ok=True)
    
    server = ThreadedTCPServer(("", PORT), DashboardHandler)
    from source_utils import get_pipeline_build_id
    b_id = get_pipeline_build_id()
    print(f"============================================================")
    print(f"  LionReel GUI Dashboard Server launched successfully! (PID: {os.getpid()})")
    print(f"  --> Build ID: {b_id} | Python: {sys.executable}")
    print(f"  --> Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  --> Open: http://localhost:{PORT} in your web browser")
    print(f"============================================================")
    
    def auto_resume_watcher():
        global RUNNING_PROCESS, RUNNING_PROCESS_START_TIME, CURRENT_JOB_ID
        while True:
            time.sleep(4.0)
            try:
                if RUNNING_PROCESS is not None and RUNNING_PROCESS.poll() is None:
                    continue

                if not os.path.exists(JOB_RESULT_FILE):
                    continue

                with open(JOB_RESULT_FILE, "r", encoding="utf-8") as f_jr:
                    res_data = json.load(f_jr)

                job_status = res_data.get("status")
                job_id = res_data.get("job_id") or CURRENT_JOB_ID
                if not should_auto_resume_job(job_id, job_status):
                    continue

                target_clips = int(res_data.get("clips_needed") or res_data.get("target_clips") or 100)
                min_sources_needed = max(1, (target_clips + 2) // 3)

                import job_options
                if job_options.is_job_process_alive(job_id):
                    continue

                from clip_ledger import ClipLedger
                ledger = ClipLedger()
                cap_res = ledger.get_pool_ready_and_capacity("cat", target_clips=target_clips)
                ready_windows = cap_res.get("ready", 0)
                usable_sources = cap_res.get("usable_sources", 0)

                if ready_windows >= target_clips and usable_sources >= min_sources_needed:
                    print(f"[AUTO-RESUME] Bank now has {ready_windows} verified windows across {usable_sources} sources (needed {target_clips} clips, {min_sources_needed} sources). Resuming job {job_id}...")
                    work_job_dir = os.path.join(WORK_DIR, job_id)
                    os.makedirs(work_job_dir, exist_ok=True)
                    job_log_file = os.path.join(work_job_dir, "job.log")
                    launch_banner = f"=== Launching LionReel Automation Script (Job: {job_id}) ===\n"
                    with open(job_log_file, "w", encoding="utf-8") as f_jinit:
                        f_jinit.write(launch_banner)
                    log_fd = open(job_log_file, "a", encoding="utf-8", errors="ignore")
                    python_exe = r"C:\LionReel\venv\Scripts\python.exe"
                    if not os.path.exists(python_exe):
                        python_exe = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
                    if not os.path.exists(python_exe):
                        python_exe = sys.executable or "python"
                    RUNNING_PROCESS_START_TIME = time.time()
                    import job_options
                    job_cfg = job_options.load_job_config(job_id)
                    if job_cfg:
                        cli_args = job_options.build_cli_args(job_cfg, job_id, RUNNING_PROCESS_START_TIME)
                        cmd = [python_exe, "-u", "lion_automate_v97.py"] + cli_args
                    else:
                        cmd = [python_exe, "-u", "lion_automate_v97.py", "--job-id", job_id, "--job-start-time", str(RUNNING_PROCESS_START_TIME)]
                    CURRENT_JOB_ID = job_id
                    RUNNING_PROCESS = subprocess.Popen(
                        cmd, stdout=log_fd, stderr=log_fd, cwd=BASE_DIR,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
                    )
            except Exception:
                pass

    def open_browser_delayed(port):
        if os.environ.get("NO_BROWSER"):
            return
        import time
        import webbrowser
        time.sleep(0.5)
        try:
            webbrowser.open(f"http://localhost:{port}")
        except:
            pass

    threading.Thread(target=auto_resume_watcher, daemon=True).start()
    threading.Thread(target=open_browser_delayed, args=(PORT,), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()
        server.server_close()
