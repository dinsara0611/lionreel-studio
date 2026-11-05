import os
import lion_paths
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
import mimetypes
from http.server import SimpleHTTPRequestHandler
from typing import Optional, List, Dict, Any, Tuple
import atexit
import job_options

PORT = int(os.environ.get("PORT", 8000))
RUNNING_PROCESS = None
RUNNING_PROCESS_START_TIME = None
CURRENT_JOB_ID = None
LAST_EXIT_CODE = None
LOG_FILE = "gui_run.log"
CONFIG_FILE = "config.json"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
FINISHED_DIR = os.path.join(BASE_DIR, "finished")
RAW_DIR = os.path.join(BASE_DIR, "raw")
OWN_FOOTAGE_DIR = os.path.join(BASE_DIR, "own_footage")
LOCK_FILE = os.path.join(BASE_DIR, "web_server.lock")
_START_LOCK = threading.Lock()

def acquire_server_lock():
    pid = os.getpid()
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                existing_pid = int(content)
                if existing_pid != pid:
                    is_active = False
                    is_server_proc = False
                    proc_info = ""
                    if sys.platform == "win32":
                        import ctypes
                        import ctypes.wintypes
                        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                        STILL_ACTIVE = 259
                        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, existing_pid)
                        if h:
                            exit_code = ctypes.c_ulong()
                            if ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code)):
                                is_active = (exit_code.value == STILL_ACTIVE)
                            if is_active:
                                buffer = ctypes.create_unicode_buffer(1024)
                                size = ctypes.wintypes.DWORD(1024)
                                if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buffer, ctypes.byref(size)):
                                    proc_info = buffer.value
                                    is_server_proc = ("python" in proc_info.lower())
                            ctypes.windll.kernel32.CloseHandle(h)
                    else:
                        try:
                            os.kill(existing_pid, 0)
                            is_active = True
                            is_server_proc = True
                        except OSError:
                            is_active = False

                    if is_active and is_server_proc:
                        print(f"[INFO] LionReel Web Server is already running (PID: {existing_pid}). Opening browser...")
                        try:
                            import webbrowser
                            webbrowser.open(f"http://localhost:{PORT}")
                        except Exception:
                            pass
                        sys.exit(0)
                    elif is_active and not is_server_proc:
                        print(f"[INFO] Reclaiming stale lock (PID {existing_pid} was recycled by {os.path.basename(proc_info) or 'another process'}).")
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
    Suppresses duplicate consecutive lines and duplicate SEQ lines (Task 8).
    """
    res = []
    banner_indices = [i for i, line in enumerate(raw_lines) if "=== Launching LionReel Automation Script" in line]
    active_lines = raw_lines[banner_indices[-1]:] if banner_indices else raw_lines

    seen_seq_tags = set()
    last_line = None
    seq_counter = 1
    seq_regex = re.compile(r"\[SEQ:(\d+)\]")

    for line_str in active_lines:
        clean_str = line_str.rstrip("\r\n")
        if not clean_str:
            continue

        # Suppress duplicate identical consecutive lines (e.g. repeated launch banners)
        if clean_str == last_line:
            continue

        # Suppress repeated identical [SEQ:X] blocks if duplicate handler/process wrote them
        m = seq_regex.search(clean_str)
        if m:
            seq_num = m.group(1)
            sig_content = seq_regex.sub("", clean_str).strip()
            sig_content = re.sub(r"\[\d{2}:\d{2}:\d{2}\]", "", sig_content).strip()
            tag_sig = (seq_num, sig_content)
            if tag_sig in seen_seq_tags:
                continue
            seen_seq_tags.add(tag_sig)

        last_line = clean_str
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
    local_p = lion_paths.work_root()
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
    norm_status = str(status or "").strip().lower().replace(" ", "_")
    return norm_status in ("waiting_for_clips", "needs_sources", "waiting_for_footage")

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

def update_stages_list_status(stages_list, computed_status, job_res=None):
    """
    Consistency rule:
    1. Stages that already finished (status == 'DONE') must NEVER be overwritten to 'WAITING'.
    2. Only the active stage (RUNNING or WAITING) receives the WAITING status during shortages.
    3. If no stage is running yet, only stage 1 (if not DONE) becomes WAITING.
    """
    if not stages_list:
        return stages_list
    ready = job_res.get("clips_ready", 0) if job_res else 0
    needed = job_res.get("clips_needed", 0) if job_res else 0

    if computed_status in ("waiting_for_clips", "needs_sources"):
        target_stage = None
        for s in stages_list:
            if s.get("status") in ("RUNNING", "WAITING"):
                target_stage = s
                break
        if not target_stage:
            for s in stages_list:
                if s.get("id") == 1 and s.get("status") != "DONE":
                    target_stage = s
                    break
        if target_stage:
            target_stage["status"] = "WAITING"
            target_stage["reason"] = f"{ready} of {needed} ready"
            target_stage["evidence"] = f"Waiting: {ready} of {needed} clips ready"
    elif computed_status == "error":
        for s in stages_list:
            if s.get("status") == "RUNNING":
                s["status"] = "FAILED"
                s["reason"] = "Process terminated unexpectedly"
                s["evidence"] = "Failed: Process terminated unexpectedly"
    return stages_list

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
        import urllib.parse
        clean_path = self.path.split("?")[0].split("#")[0]
        if (clean_path.startswith("/finished/") or 
            clean_path.startswith("/raw/") or 
            clean_path.startswith("/work/") or 
            clean_path.startswith("/output/")):
            
            rel_path = ""
            base_dir = FINISHED_DIR
            if clean_path.startswith("/finished/"):
                rel_path = urllib.parse.unquote(clean_path[len("/finished/"):].lstrip("/\\"))
                base_dir = FINISHED_DIR
            elif clean_path.startswith("/raw/"):
                rel_path = urllib.parse.unquote(clean_path[len("/raw/"):].lstrip("/\\"))
                base_dir = RAW_DIR
            elif clean_path.startswith("/work/"):
                rel_path = urllib.parse.unquote(clean_path[len("/work/"):].lstrip("/\\"))
                base_dir = WORK_DIR
            elif clean_path.startswith("/output/"):
                rel_path = urllib.parse.unquote(clean_path[len("/output/"):].lstrip("/\\"))
                base_dir = OUTPUT_DIR

            filepath = os.path.normpath(os.path.join(base_dir, rel_path))
            if not (os.path.exists(filepath) and os.path.isfile(filepath)):
                fname = os.path.basename(rel_path)
                for cand in [os.path.join(FINISHED_DIR, fname), os.path.join(OUTPUT_DIR, fname), os.path.join(WORK_DIR, fname), os.path.join(RAW_DIR, fname)]:
                    if os.path.exists(cand) and os.path.isfile(cand):
                        filepath = cand
                        break

            if os.path.exists(filepath) and os.path.isfile(filepath):
                self.send_response(200)
                lower = filepath.lower()
                if lower.endswith(".mp4"):
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Accept-Ranges", "bytes")
                elif lower.endswith(".webm"):
                    self.send_header("Content-Type", "video/webm")
                elif lower.endswith(".webp"):
                    self.send_header("Content-Type", "image/webp")
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
        global RUNNING_PROCESS, RUNNING_PROCESS_START_TIME, LAST_EXIT_CODE, CURRENT_JOB_ID
        import urllib.parse
        import job_options
        clean_path = self.path.split("?")[0]
        
        # Route API Calls
        if self.path.startswith("/api/status"):
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            target_job_id = query_params.get("job_id", [None])[0]

            is_running = False
            start_time_ms = None
            elapsed_sec = 0
            if RUNNING_PROCESS is not None:
                poll_res = RUNNING_PROCESS.poll()
                if poll_res is None:
                    # Current process is actively running
                    if not target_job_id or target_job_id == CURRENT_JOB_ID:
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
                            detected_stage = None
                            detected_stage_id = None
                            stage_candidates = []
                            if CURRENT_JOB_ID:
                                stage_candidates.append(os.path.join(WORK_DIR, CURRENT_JOB_ID, "stages_state.json"))
                                try:
                                    stage_candidates.append(os.path.join(get_local_work_dir(), CURRENT_JOB_ID, "stages_state.json"))
                                except Exception:
                                    pass
                            for sc in stage_candidates:
                                if os.path.exists(sc):
                                    try:
                                        with open(sc, "r", encoding="utf-8") as f_sc:
                                            stg_info = json.load(f_sc)
                                            for st_item in stg_info.get("stages", []):
                                                st_st = str(st_item.get("status", "")).strip().lower()
                                                if st_st == "failed":
                                                    detected_stage = st_item.get("label") or st_item.get("name") or st_item.get("key")
                                                    detected_stage_id = st_item.get("id")
                                                    dt = st_item.get("details") if isinstance(st_item.get("details"), dict) else {}
                                                    reason_code = st_item.get("code") or dt.get("code") or ("QA_FAILED" if "qa" in str(st_item.get("key", "")).lower() else "STAGE_FAILED")
                                                    r_msg = st_item.get("reason")
                                                    human_error = f"{detected_stage}: {r_msg}" if r_msg else f"Job failed at stage: {detected_stage}"
                                                    break
                                    except Exception:
                                        pass
                                if detected_stage:
                                    break

                            # Fallback: check job_result.json in job directory or root if stage was not caught from stages_state
                            if CURRENT_JOB_ID:
                                jr_candidates = [
                                    os.path.join(WORK_DIR, CURRENT_JOB_ID, "job_result.json"),
                                    os.path.join(BASE_DIR, "job_result.json")
                                ]
                                for jrc in jr_candidates:
                                    if os.path.exists(jrc):
                                        try:
                                            with open(jrc, "r", encoding="utf-8") as f_jr_chk:
                                                jr_data = json.load(f_jr_chk)
                                                if jr_data.get("error") or jr_data.get("reason_code") or jr_data.get("code"):
                                                    reason_code = jr_data.get("reason_code") or jr_data.get("code") or reason_code
                                                    human_error = jr_data.get("error") or human_error
                                                    detected_stage = jr_data.get("failed_stage") or jr_data.get("stage_name") or detected_stage
                                                    break
                                        except Exception:
                                            pass

                            if not detected_stage and (not reason_code or reason_code == "NONE"):
                                reason_code = "CRASH"
                                human_error = f"Process crashed with error code {poll_res}"

                        print(f"[Job Error] Reason: {reason_code} | {human_error} | Exit code: {poll_res}")

                        err_payload = {
                            "job_id": CURRENT_JOB_ID,
                            "status": "error",
                            "success": False,
                            "reason_code": reason_code,
                            "error": human_error,
                            "details": log_tail_text,
                            "exit_code": poll_res,
                            "elapsed_seconds": final_elapsed,
                            "failed_stage": detected_stage or ("startup" if final_elapsed < 2 else None),
                            "stage_index": detected_stage_id if detected_stage else None
                        }
                        try:
                            with open(JOB_RESULT_FILE, "w", encoding="utf-8") as f_err:
                                json.dump(err_payload, f_err, indent=2)
                            if CURRENT_JOB_ID:
                                with open(os.path.join(WORK_DIR, CURRENT_JOB_ID, "job_result.json"), "w", encoding="utf-8") as f_jerr:
                                    json.dump(err_payload, f_jerr, indent=2)
                        except Exception:
                            pass
            
            # Resolve job_id and job_res strictly adhering to requested target_job_id
            job_id = target_job_id or CURRENT_JOB_ID
            job_res = None
            if job_id:
                per_job_file = os.path.join(WORK_DIR, job_id, "job_result.json")
                if os.path.exists(per_job_file):
                    try:
                        with open(per_job_file, "r", encoding="utf-8") as f_jr:
                            job_res = json.load(f_jr)
                    except Exception:
                        pass

            if not job_res and not target_job_id and os.path.exists(JOB_RESULT_FILE):
                try:
                    with open(JOB_RESULT_FILE, "r", encoding="utf-8") as f_jr:
                        job_res = json.load(f_jr)
                except Exception:
                    pass

            if not job_id and job_res:
                job_id = job_res.get("job_id")

            wait_checkpoint = None
            if job_id:
                cp_file = os.path.join(WORK_DIR, job_id, "wait_checkpoint.json")
                if os.path.exists(cp_file):
                    try:
                        with open(cp_file, "r", encoding="utf-8") as f_cp:
                            wait_checkpoint = json.load(f_cp)
                    except Exception:
                        pass

            is_failed = False
            if not is_running:
                if job_res and (job_res.get("status") in ("failed", "error") or job_res.get("success") is False):
                    is_failed = True
                elif LAST_EXIT_CODE is not None and LAST_EXIT_CODE != 0:
                    is_failed = True

            is_waiting = False
            waiting_status = None
            if not is_failed:
                if is_running:
                    if wait_checkpoint and wait_checkpoint.get("status") in ("waiting_for_clips", "needs_sources", "waiting"):
                        is_waiting = True
                        waiting_status = wait_checkpoint.get("status")
                    elif job_res and job_res.get("status") in ("waiting_for_clips", "needs_sources"):
                        is_waiting = True
                        waiting_status = job_res.get("status")
                else:
                    if job_res and job_res.get("status") in ("waiting_for_clips", "needs_sources") and LAST_EXIT_CODE in (None, 0):
                        is_waiting = True
                        waiting_status = job_res.get("status")

            # Watchdog check: detect if job is stuck (no heartbeat >60s or PID dead)
            stuck_info = None
            try:
                from watchdog_service import check_job_health, detect_stale_jobs
                if job_id:
                    w_dir = os.path.join(WORK_DIR, job_id)
                    if os.path.exists(w_dir):
                        h_res = check_job_health(w_dir, max_stale_sec=60.0)
                        if not h_res["healthy"] and h_res["status"] == "stuck":
                            stuck_info = h_res
                if not stuck_info:
                    stale_list = detect_stale_jobs(WORK_DIR, max_stale_sec=60.0)
                    if stale_list:
                        stuck_info = stale_list[0]
            except Exception as e_wd:
                pass

            if is_failed:
                computed_status = "error"
            elif stuck_info:
                computed_status = "stuck"
                is_running = False
                is_waiting = False
            elif job_res and job_res.get("status") == "stuck":
                computed_status = "stuck"
                is_running = False
                is_waiting = False
            elif is_waiting:
                computed_status = waiting_status or "waiting_for_clips"
            elif is_running:
                computed_status = "running"
            elif job_res and job_res.get("status") == "completed" and job_res.get("success"):
                computed_status = "completed"
            elif LAST_EXIT_CODE is not None:
                if LAST_EXIT_CODE == 0 and job_res and job_res.get("success"):
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
                # Update stage states based on computed_status consistently
                stages_list = update_stages_list_status(stages_list, computed_status, job_res)
                if stages_file:
                    try:
                        with open(stages_file, "w", encoding="utf-8") as f_stg_w:
                            json.dump({"job_id": job_id, "stages": stages_list}, f_stg_w, indent=2)
                    except Exception:
                        pass

            # Honest server-side estimator calculation
            estimator_telemetry = None
            waiting_s = 0.0
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
                if wait_checkpoint and "wait_elapsed_sec" in wait_checkpoint:
                    waiting_s = float(wait_checkpoint.get("wait_elapsed_sec", 0.0))
                elif job_res and "waiting_seconds" in job_res:
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
                if computed_status == "stuck":
                    state_lbl = "STUCK"
                elif computed_status in ("waiting_for_clips", "needs_sources", "waiting") or is_waiting:
                    state_lbl = "WAITING"
                    if job_res and job_res.get("clips_needed"):
                        progress_val = int(round((job_res.get("clips_ready", 0) / float(max(1, job_res.get("clips_needed", 1)))) * 100))
            else:
                real_elapsed = round(time.time() - RUNNING_PROCESS_START_TIME, 1) if (is_running and RUNNING_PROCESS_START_TIME) else elapsed_sec
                if (computed_status in ("waiting_for_clips", "needs_sources", "waiting") or is_waiting) and job_res:
                    progress_val = int(round((job_res.get("clips_ready", 0) / float(max(1, job_res.get("clips_needed", 1)))) * 100))
                else:
                    progress_val = (job_res.get("progress_pct") if job_res else (100 if computed_status == "completed" else 5))
                eta_val = 0
                eta_fmt = "--:--"
                is_calc = False
                if computed_status == "stuck":
                    state_lbl = "STUCK"
                elif is_waiting or computed_status in ("waiting_for_clips", "needs_sources", "waiting"):
                    state_lbl = "WAITING"
                elif is_running:
                    state_lbl = "LIVE"
                elif computed_status == "completed":
                    state_lbl = "DONE"
                else:
                    state_lbl = "FAILED"
                current_stage_idx = (job_res.get("stage_index") if job_res else (10 if computed_status == "completed" else 1))
                current_stage_name = (job_res.get("stage_name") if job_res else "")

            if computed_status == "stuck":
                state_lbl = "STUCK"
            elif computed_status == "error" and job_res:
                if job_res.get("failed_stage"):
                    current_stage_name = job_res.get("failed_stage")
                if job_res.get("stage_index"):
                    current_stage_idx = job_res.get("stage_index")
                state_lbl = "FAILED"

            working_s = max(0.0, real_elapsed - waiting_s)

            def _fmt_hms(total_sec):
                ts = max(0, int(round(total_sec)))
                h = ts // 3600
                m = (ts % 3600) // 60
                s = ts % 60
                return f"{h}:{m:02d}:{s:02d}"

            active_pid = RUNNING_PROCESS.pid if (RUNNING_PROCESS and RUNNING_PROCESS.poll() is None) else None
            running_procs = [active_pid] if active_pid else []

            # Read deadline and planner decision telemetry
            deadline_info = {}
            if job_id:
                dl_file = os.path.join(WORK_DIR, job_id, "deadline.json")
                if os.path.exists(dl_file):
                    try:
                        with open(dl_file, "r", encoding="utf-8") as f_dl:
                            deadline_info = json.load(f_dl)
                    except Exception:
                        pass

            planner_info = {}
            if job_id:
                for p_dir in [os.path.join(WORK_DIR, job_id), os.path.join(OUTPUT_DIR, job_id)]:
                    p_file = os.path.join(p_dir, "planner_decision.json")
                    if os.path.exists(p_file):
                        try:
                            with open(p_file, "r", encoding="utf-8") as f_pd:
                                planner_info = json.load(f_pd)
                            break
                        except Exception:
                            pass

            rep_pct = float(planner_info.get("repeat_share_pct", 0.0))
            rep_str = f"{rep_pct:.1f}% repeat share" if rep_pct > 0 else "100% unique moments"

            # Reconcile ETA with monotonic deadline D
            if deadline_info and deadline_info.get("deadline_epoch") and is_running:
                dl_epoch = float(deadline_info["deadline_epoch"])
                now_epoch = time.time()
                rem_deadline_s = max(15, int(round(dl_epoch - now_epoch)))
                if progress_val < 90 and (eta_val < 25 or is_calc):
                    eta_val = rem_deadline_s
                    eta_fmt = f"{eta_val // 60:02d}:{eta_val % 60:02d}" if eta_val < 3600 else _fmt_hms(eta_val)
                    is_calc = False

            # Active job configuration descriptor for UI chip summary (Single Source of Truth)
            saved_jcfg = None
            if job_id:
                try:
                    saved_jcfg = job_options.load_or_verify_job_config(job_id)
                except Exception:
                    saved_jcfg = None

            if saved_jcfg:
                active_job_cfg = {
                    "mode": saved_jcfg.get("mode"),
                    "type": saved_jcfg.get("mode"),
                    "video_type": saved_jcfg.get("mode"),
                    "ratio": saved_jcfg.get("ratio"),
                    "aspect_ratio": saved_jcfg.get("ratio"),
                    "resolution": saved_jcfg.get("resolution"),
                    "target_seconds": saved_jcfg.get("target_seconds"),
                    "expected_total": saved_jcfg.get("target_seconds"),
                    "clip_time": saved_jcfg.get("clip_time"),
                    "clip_count": saved_jcfg.get("clip_count"),
                    "clips": saved_jcfg.get("clip_count"),
                    "teaser": saved_jcfg.get("teaser"),
                    "pace": current_cfg.get("SPEED_PROFILE", "fast"),
                    "slicing": current_cfg.get("MOMENT_CUT_MODE", "peak_viral"),
                    "layout": current_cfg.get("LAYOUT_MODE", "smart_crop"),
                    "repeat_share_pct": rep_pct
                }
            else:
                active_job_cfg = {
                    "type": planner_info.get("video_type") or current_cfg.get("VIDEO_TYPE") or current_cfg.get("type") or "compilation",
                    "video_type": planner_info.get("video_type") or current_cfg.get("VIDEO_TYPE") or "compilation",
                    "clips": planner_info.get("target_clips_count") or current_cfg.get("TARGET_CLIPS") or 6,
                    "clip_time": planner_info.get("target_clip_sec") or current_cfg.get("SHORT_CLIP_SEC") or 7.5,
                    "expected_total": planner_info.get("expected_total_sec") or (float(planner_info.get("target_clips_count") or current_cfg.get("TARGET_CLIPS") or 6) * float(planner_info.get("target_clip_sec") or current_cfg.get("SHORT_CLIP_SEC") or 7.5)),
                    "pace": current_cfg.get("SPEED_PROFILE", "fast"),
                    "slicing": current_cfg.get("MOMENT_CUT_MODE", "peak_viral"),
                    "layout": current_cfg.get("LAYOUT_MODE", "smart_crop"),
                    "repeat_share_pct": rep_pct
                }

            c_ready = 0
            c_needed = int(planner_info.get("target_clips_count") or current_cfg.get("TARGET_CLIPS") or 4)
            if job_res:
                if job_res.get("clips_ready") is not None:
                    c_ready = int(job_res["clips_ready"])
                elif job_res.get("clip_list"):
                    c_ready = len(job_res["clip_list"])
                if job_res.get("clips_needed") is not None:
                    c_needed = int(job_res["clips_needed"])

            if planner_info:
                st_card = planner_info.get("status_card_line", "")
                m_ready = re.search(r"(\d+)\s+of\s+(\d+)\s+clips\s+ready", st_card)
                if m_ready:
                    c_ready = max(c_ready, int(m_ready.group(1)))
                    c_needed = max(c_needed, int(m_ready.group(2)))
                elif planner_info.get("target_clips_count") and str(planner_info.get("strategy_used", "")).startswith("ladder_step_1"):
                    c_ready = max(c_ready, int(planner_info["target_clips_count"]))

            if stages_list:
                for st in stages_list:
                    if st.get("id") == 1:
                        ev = st.get("evidence", "")
                        m_ev = re.search(r"Reserved\s+(\d+)\s+candidate\s+clips", ev)
                        if m_ev:
                            c_ready = max(c_ready, int(m_ev.group(1)))
                    if st.get("id") in (1, 6) and "details" in st and isinstance(st["details"], dict):
                        dt = st["details"]
                        if dt.get("units_done"):
                            c_ready = max(c_ready, int(dt["units_done"]))
                        if dt.get("units_total"):
                            c_needed = max(c_needed, int(dt["units_total"]))

            # Recent log tail (last 5 non-empty lines)
            recent_logs = []
            if job_id:
                log_p = os.path.join(WORK_DIR, job_id, "job.log")
                if os.path.exists(log_p):
                    try:
                        with open(log_p, "r", encoding="utf-8", errors="ignore") as f_lg:
                            lines = [l.strip() for l in f_lg.readlines() if l.strip()]
                            recent_logs = lines[-5:]
                    except Exception:
                        pass

            # Amber prediction warning if elapsed > predicted high
            is_over_predicted = False
            prediction_warning = ""
            pred_high = float(deadline_info.get("predicted_high_sec") or 0.0)
            pred_low = float(deadline_info.get("predicted_low_sec") or 0.0)
            if pred_high > 0 and real_elapsed > pred_high and (is_running or is_waiting or computed_status == "stuck"):
                is_over_predicted = True
                low_m, low_s = int(pred_low // 60), int(pred_low % 60)
                high_m, high_s = int(pred_high // 60), int(pred_high % 60)
                expected_str = f"{low_m}–{high_m} min" if (low_m or high_m) else f"{pred_low:.0f}–{pred_high:.0f}s"
                waiting_for_detail = current_stage_name or "processing"
                if computed_status in ("waiting_for_clips", "needs_sources", "waiting") or is_waiting:
                    waiting_for_detail = f"footage ({c_ready}/{c_needed} clips ready)"
                elif computed_status == "stuck":
                    waiting_for_detail = stuck_info.get("reason") if stuck_info else "engine heartbeat"
                prediction_warning = f"Taking longer than predicted: {_fmt_hms(real_elapsed)}, expected {expected_str}. Reason: waiting for {waiting_for_detail}"

            resp_data = {
                "status": computed_status,
                "job_id": job_id,
                "clips_ready": c_ready,
                "clips_needed": c_needed,
                "plainPlanSentence": planner_info.get("plain_plan_sentence") or "",
                "isRunning": is_running,
                "isWaiting": (is_waiting or computed_status in ("waiting_for_clips", "needs_sources", "waiting")),
                "runningPid": active_pid,
                "runningProcesses": running_procs,
                "startTimeMs": start_time_ms,
                "elapsedSeconds": real_elapsed,
                "realElapsedSec": real_elapsed,
                "workingSeconds": round(working_s, 1),
                "waitingSeconds": round(waiting_s, 1),
                "workingFormatted": _fmt_hms(working_s),
                "waitingFormatted": _fmt_hms(waiting_s),
                "elapsedFormatted": _fmt_hms(real_elapsed),
                "stageIndex": current_stage_idx,
                "stageName": current_stage_name,
                "progressPct": progress_val,
                "etaSeconds": eta_val,
                "etaFormatted": eta_fmt,
                "isCalculating": is_calc,
                "stateLabel": state_lbl,
                "stuckJobInfo": stuck_info,
                "stuckReason": (stuck_info.get("reason") if stuck_info else (job_res.get("stuck_reason") if job_res else None)),
                "recentLogs": recent_logs,
                "isOverPredicted": is_over_predicted,
                "predictionWarning": prediction_warning,
                "estimator": estimator_telemetry,
                "candidateReports": (job_res.get("candidate_reports", []) if job_res else []),
                "failedStage": (job_res.get("failed_stage") if job_res else ("startup" if (LAST_EXIT_CODE not in (None, 0) and computed_status == "error") else None)),
                "exitCode": (0 if computed_status in ("waiting_for_clips", "needs_sources") else LAST_EXIT_CODE),
                "reasonCode": (job_res.get("reason_code") if job_res else ("INVALID_ARGUMENTS" if LAST_EXIT_CODE == 2 else ("CRASH" if (LAST_EXIT_CODE and LAST_EXIT_CODE != 0) else None))),
                "errorDetails": (job_res.get("details") if job_res else None),
                "jobResult": job_res,
                "job_config": active_job_cfg,
                "jobConfig": active_job_cfg,
                "stages": stages_list,
                "harvestStatus": harvest_info,
                "waitCheckpoint": wait_checkpoint,
                "failureActions": job_options.get_failure_action_options(
                    reason_code=job_res.get("reason_code", "SHORTAGE_WAIT_EXCEEDED") if job_res else "SHORTAGE_WAIT_EXCEEDED",
                    clips_ready=c_ready,
                    clips_needed=c_needed,
                    current_length_s=float(active_job_cfg.get("expected_total") or 30.0),
                    possible_length_s=round(c_ready * float(active_job_cfg.get("clip_time") or 7.5), 1),
                    reuse_share_pct=float(planner_info.get("repeat_share_pct") or 25.0)
                ),
                "shortageSentence": f"{c_ready} of {c_needed} clips ready, {max(0, c_needed - c_ready)} missing. Harvest found {wait_checkpoint.get('verified_count', 0) if wait_checkpoint else 0} new windows in {round(waiting_s / 60.0, 1) if waiting_s else 0} min.",
                "generatedFile": job_res.get("output_file") if (job_res and job_res.get("success")) else None,
                "sha256": job_res.get("sha256") if (job_res and job_res.get("success")) else None,
                "clipList": job_res.get("clip_list") if (job_res and job_res.get("success")) else [],
                "duration": job_res.get("duration") if (job_res and job_res.get("success")) else None,
                "renderTimeSec": job_res.get("render_time_sec") if (job_res and job_res.get("success")) else None,
                "planSummary": deadline_info.get("plan_summary") or planner_info.get("status_card_line") or "Plan ready",
                "predictedRange": deadline_info.get("predicted_range_str") or "about 1–2 min",
                "predictedFinishClock": deadline_info.get("finish_clock_str") or "",
                "deadlineEpoch": deadline_info.get("deadline_epoch"),
                "minFeasibleStr": deadline_info.get("min_feasible_str") or "",
                "repeatSharePct": rep_pct,
                "repeatShareStr": rep_str,
                "deadlineInfo": deadline_info,
                "plannerDecision": planner_info,
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
            CURRENT_JOB_ID = None
            if os.path.exists(JOB_RESULT_FILE):
                try: os.remove(JOB_RESULT_FILE)
                except: pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode())
            return

        elif self.path in ("/api/config", "/api/config/") or self.path.startswith("/api/config?"):
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
        elif self.path.startswith("/api/filler/status"):
            try:
                from clip_bank_filler import ClipBankFiller
                filler = ClipBankFiller()
                f_status = filler.get_status()
            except Exception as e_fill:
                f_status = {"error": str(e_fill), "chip_text": "idle", "state": "idle"}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(f_status).encode())
            return

        elif self.path.startswith("/api/preflight"):
            animal = "cat"
            format_type = "short"
            target_clips = 6
            clip_time = 7.5

            has_explicit_clips = False
            if "?" in self.path:
                q = urllib.parse.parse_qs(self.path.split("?", 1)[1])
                if "animal" in q: animal = q["animal"][0]
                if "type" in q: format_type = q["type"][0]
                elif "format" in q: format_type = q["format"][0]
                if "clips" in q:
                    try:
                        target_clips = int(q["clips"][0])
                        has_explicit_clips = True
                    except: pass
                if "clip_time" in q:
                    try: clip_time = float(q["clip_time"][0])
                    except: pass
                if "duration" in q and not has_explicit_clips:
                    try:
                        dur_min = float(q["duration"][0])
                        target_clips = max(1, int(round((dur_min * 60.0) / clip_time)))
                        has_explicit_clips = True
                    except: pass

            import job_options
            canonical_animal = job_options.ANIMAL_MAP.get(animal.lower(), "cat")
            is_comp = format_type in ["long", "compilation", "both"]
            if is_comp and not has_explicit_clips:
                target_clips = 100

            verified_windows = 0
            distinct_sources = 0
            vertical_sources = 0
            vertical_verified = 0
            landscape_sources = 0
            candidates = 0
            try:
                from clip_ledger import ClipLedger
                ledger = ClipLedger()
                pool_cap = ledger.get_pool_ready_and_capacity(canonical_animal, target_clips=target_clips, allow_reuse=False)
                verified_windows = pool_cap["verified_windows"]
                distinct_sources = pool_cap["usable_sources"]
                candidates = pool_cap["candidates"]
                
                with ledger._get_conn() as conn:
                    cur_v = conn.execute("SELECT COUNT(DISTINCT source_id) AS cnt FROM clips WHERE animal_type = ? AND orientation = 'vertical'", (canonical_animal,))
                    row_v = cur_v.fetchone()
                    vertical_sources = row_v["cnt"] if row_v else 0

                    cur_vv = conn.execute("SELECT COUNT(*) AS cnt FROM clips WHERE animal_type = ? AND orientation = 'vertical' AND is_verified = 1 AND times_used == 0 AND pending_short_id IS NULL", (canonical_animal,))
                    row_vv = cur_vv.fetchone()
                    vertical_verified = row_vv["cnt"] if row_vv else 0

                    cur_l = conn.execute("SELECT COUNT(DISTINCT source_id) AS cnt FROM clips WHERE animal_type = ? AND orientation != 'vertical'", (canonical_animal,))
                    row_l = cur_l.fetchone()
                    landscape_sources = row_l["cnt"] if row_l else 0

                    pass
                ledger_counts = pool_cap["counts"]
                ledger_tot_candidates = ledger_counts["total_rows"]
                ledger_ver_candidates = ledger_counts["verified_total"]
            except Exception:
                pool_cap = {
                    "verified_windows": 0, "usable_sources": 0, "min_sources_needed": max(1, (target_clips + 2) // 3),
                    "capacity": 0, "can_supply_target": False,
                    "warning": f"This pool can supply at most 0 clips. {target_clips} clips need at least {max(1, (target_clips + 2) // 3)} sources.",
                    "options": ["harvest_first", "cancel"]
                }
                vertical_sources = 0
                vertical_verified = 0
                landscape_sources = 0
                ledger_tot_candidates = 0
                ledger_ver_candidates = 0

            min_sources_needed = pool_cap["min_sources_needed"]
            sources_shortfall = max(0, min_sources_needed - distinct_sources)
            clips_shortfall = max(0, target_clips - verified_windows)

            from harvest_worker import get_harvest_status
            h_stat = get_harvest_status()
            h_analyzed = h_stat.get("windows_analyzed", 0)
            h_verified = h_stat.get("windows_verified", 0)

            # Pass rate of last analyzed windows (Requirement 2: e.g. "3 of 13 passed")
            if h_analyzed > 0:
                pass_rate_text = f"{h_verified} of {h_analyzed} passed"
                pass_rate = h_verified / float(h_analyzed)
            elif ledger_tot_candidates > 0 and ledger_ver_candidates > 0:
                pass_rate_text = f"{ledger_ver_candidates} of {ledger_tot_candidates} passed"
                pass_rate = ledger_ver_candidates / float(ledger_tot_candidates)
            else:
                pass_rate_text = "0 of 0 passed"
                pass_rate = 0.0

            # Est. Harvest Time: compute from MEASURED history (seconds per analyzed window and pass rate), show range, or "Estimate: not enough data yet"
            sec_per_win = h_stat.get("sec_per_window", 0.0)
            if sec_per_win > 0.0 and pass_rate > 0.0 and clips_shortfall > 0:
                needed_analyses = clips_shortfall / pass_rate
                est_sec_needed = needed_analyses * sec_per_win
                low_sec = max(5, int(round(est_sec_needed * 0.8)))
                high_sec = max(low_sec + 5, int(round(est_sec_needed * 1.3)))
                est_harvest_time_text = f"~{low_sec}s - {high_sec}s (estimate)"
                est_harvest_time_sec = int(round(est_sec_needed))
            else:
                est_harvest_time_text = "Estimate: not enough data yet"
                est_harvest_time_sec = 0

            # Last harvest text (Requirement 2)
            last_act = h_stat.get("last_activity_time", 0)
            if last_act and last_act > 0:
                import datetime
                dt_str = datetime.datetime.fromtimestamp(last_act).strftime("%H:%M:%S")
                last_harvest_text = f"Last harvest: {dt_str}, {h_stat.get('sources_scanned', 0)} sources scanned, {h_stat.get('windows_verified', 0)} windows verified"
            else:
                last_harvest_text = "Last harvest: none yet, 0 sources scanned, 0 windows verified"

            capacity = pool_cap["capacity"]
            is_ready = pool_cap["can_supply_target"]
            status_code = "ready" if is_ready else ("needs_sources" if sources_shortfall > 0 else "needs_harvest")
            prompt_msg = pool_cap["warning"] if pool_cap["warning"] else f"Pool: {verified_windows} of {target_clips} ready. About {min_sources_needed} sources needed."
            suggestion_text = "Try a short video of 6 clips after the first harvest" if capacity == 0 else ""

            resp = {
                "animal": canonical_animal,
                "format": format_type,
                "needed_clips": target_clips,
                "clip_time": clip_time,
                "verified_windows": verified_windows,
                "candidates": candidates,
                "usable_sources": distinct_sources,
                "min_sources_needed": min_sources_needed,
                "usable_sources_text": f"{distinct_sources} of {min_sources_needed} needed",
                "vertical_sources": vertical_sources,
                "vertical_verified": vertical_verified,
                "vertical_sources_text": f"{vertical_sources} ({vertical_verified} verified windows yet)",
                "landscape_sources": landscape_sources,
                "pass_rate_text": pass_rate_text,
                "capacity": capacity,
                "can_supply_target": is_ready,
                "warning": pool_cap["warning"],
                "options": pool_cap["options"],
                "shortfall": clips_shortfall,
                "sources_shortfall": sources_shortfall,
                "estimated_harvest_time_sec": est_harvest_time_sec,
                "estimated_harvest_time_text": est_harvest_time_text,
                "last_harvest_text": last_harvest_text,
                "suggestion_text": suggestion_text,
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

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/report.pdf"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                candidates = [
                    os.path.join(OUTPUT_DIR, job_id, f"{job_id}_report.pdf"),
                    os.path.join(OUTPUT_DIR, job_id, "report.pdf"),
                    os.path.join(FINISHED_DIR, f"{job_id}_report.pdf"),
                ]
                pdf_path = next((p for p in candidates if os.path.exists(p)), None)
                if not pdf_path:
                    from report_generator import generate_job_report
                    generate_job_report(job_id)
                    pdf_path = next((p for p in candidates if os.path.exists(p)), None)

                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as f_pdf:
                        pdf_bytes = f_pdf.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Disposition", f'attachment; filename="{job_id}_report.pdf"')
                    self.send_header("Content-Length", str(len(pdf_bytes)))
                    self.end_headers()
                    self.wfile.write(pdf_bytes)
                else:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Report PDF not found"}).encode())
            except Exception as e_pdf:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_pdf)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/report"):
            parts = clean_path.split("/")
            job_id = parts[3]
            fmt = "json"
            if "format=html" in self.path or "text/html" in self.headers.get("Accept", ""):
                fmt = "html"
            try:
                if fmt == "html":
                    candidates = [
                        os.path.join(OUTPUT_DIR, job_id, f"{job_id}_report.html"),
                        os.path.join(OUTPUT_DIR, job_id, "report.html"),
                        os.path.join(FINISHED_DIR, f"{job_id}_report.html"),
                    ]
                    html_path = next((p for p in candidates if os.path.exists(p)), None)
                    if not html_path:
                        from report_generator import generate_job_report
                        generate_job_report(job_id)
                        html_path = next((p for p in candidates if os.path.exists(p)), None)

                    if html_path and os.path.exists(html_path):
                        with open(html_path, "r", encoding="utf-8") as f_h:
                            html_content = f_h.read()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.end_headers()
                        self.wfile.write(html_content.encode("utf-8"))
                    else:
                        self.send_response(404)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "Report HTML not found"}).encode())
                else:
                    candidates = [
                        os.path.join(OUTPUT_DIR, job_id, f"{job_id}_report.json"),
                        os.path.join(OUTPUT_DIR, job_id, "report.json"),
                        os.path.join(FINISHED_DIR, f"{job_id}_report.json"),
                    ]
                    json_path = next((p for p in candidates if os.path.exists(p)), None)
                    if not json_path:
                        from report_generator import generate_job_report
                        generate_job_report(job_id)
                        json_path = next((p for p in candidates if os.path.exists(p)), None)

                    if json_path and os.path.exists(json_path):
                        with open(json_path, "r", encoding="utf-8") as f_j:
                            rep_data = json.load(f_j)
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps(rep_data).encode("utf-8"))
                    else:
                        self.send_response(404)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "Report JSON not found"}).encode())
            except Exception as e_rep:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_rep)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/deliverables"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                import deliverables_manager
                ddata = deliverables_manager.discover_job_deliverables(job_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(ddata).encode("utf-8"))
            except Exception as e_deliv:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_deliv)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/download-pack"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                import deliverables_manager
                mem_zip, zip_filename = deliverables_manager.create_non_video_download_pack(job_id)
                zip_bytes = mem_zip.getvalue()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{zip_filename}"')
                self.send_header("Content-Length", str(len(zip_bytes)))
                self.end_headers()
                self.wfile.write(zip_bytes)
            except Exception as e_pk:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_pk)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and "/download/" in clean_path:
            parts = clean_path.split("/")
            job_id = parts[3]
            subpath = urllib.parse.unquote(clean_path.split(f"/api/jobs/{job_id}/download/")[1])
            try:
                import deliverables_manager
                target_file = deliverables_manager.resolve_safe_job_file(job_id, subpath)
                file_size = os.path.getsize(target_file)
                lower_f = os.path.basename(target_file).lower()
                ctype = mimetypes.guess_type(target_file)[0] or "application/octet-stream"

                range_hdr = self.headers.get("Range")
                if range_hdr and lower_f.endswith(".mp4") and "bytes=" in range_hdr:
                    bytes_range = range_hdr.split("=")[1].strip()
                    r_parts = bytes_range.split("-")
                    start = int(r_parts[0]) if r_parts[0] else 0
                    end = int(r_parts[1]) if len(r_parts) > 1 and r_parts[1] else file_size - 1
                    if end >= file_size: end = file_size - 1
                    length = end - start + 1

                    self.send_response(206)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                    self.send_header("Content-Length", str(length))
                    self.end_headers()

                    with open(target_file, "rb") as f_chunk:
                        f_chunk.seek(start)
                        rem = length
                        while rem > 0:
                            chunk = f_chunk.read(min(64 * 1024, rem))
                            if not chunk: break
                            self.wfile.write(chunk)
                            rem -= len(chunk)
                    return

                # Full file download
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(file_size))
                self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(target_file)}"')
                self.end_headers()
                with open(target_file, "rb") as f_dl:
                    while True:
                        chunk = f_dl.read(64 * 1024)
                        if not chunk: break
                        self.wfile.write(chunk)
            except PermissionError as e_perm:
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_perm)}).encode())
            except FileNotFoundError as e_nf:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_nf)}).encode())
            except Exception as e_gen:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_gen)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/thumbnails"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                import thumbnail_maker
                meta_p = os.path.join(OUTPUT_DIR, job_id, "thumbnails", "thumbnail_meta.json")
                rep_p = os.path.join(OUTPUT_DIR, job_id, "thumbnail_report.json")
                tmeta = None

                # Section 6 Scope Check: Long videos only. Answer "not available for Shorts"
                is_supported, reason = thumbnail_maker.is_thumbnail_supported_for_job(job_id)
                if not is_supported:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "available": False,
                        "skipped": True,
                        "error": "not available for Shorts",
                        "reason": reason
                    }).encode("utf-8"))
                    return

                if os.path.exists(meta_p):
                    try:
                        with open(meta_p, "r", encoding="utf-8") as f_tm:
                            tmeta = json.load(f_tm)
                            if not tmeta.get("candidates") or len(tmeta.get("candidates", [])) < 6:
                                tmeta = None
                    except Exception:
                        tmeta = None

                if not tmeta:
                    tmeta = thumbnail_maker.generate_job_thumbnails(job_id)

                if isinstance(tmeta, dict):
                    if os.path.exists(rep_p):
                        try:
                            with open(rep_p, "r", encoding="utf-8") as f_rep:
                                tmeta["report"] = json.load(f_rep)
                        except Exception:
                            pass
                    tmeta["thumbnail_url"] = f"/output/{job_id}/thumbnail.jpg"

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(tmeta, default=str).encode("utf-8"))
            except Exception as e_th:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_th)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/thumbnails/copy-path"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                thumb_path = os.path.abspath(os.path.join(OUTPUT_DIR, job_id, "thumbnail.jpg"))
                exists = os.path.exists(thumb_path)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "exists": exists,
                    "path": thumb_path,
                    "relative_path": f"output/{job_id}/thumbnail.jpg"
                }).encode("utf-8"))
            except Exception as e_cp:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_cp)}).encode("utf-8"))
            return

        elif clean_path.startswith("/api/thumbnail-analytics"):
            try:
                import thumbnail_maker
                rec = thumbnail_maker.get_thumbnail_learning_recommendation()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(rec).encode("utf-8"))
            except Exception as e_ta:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e_ta)}).encode())
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

        elif self.path.startswith("/api/config/platform-limits"):
            pl_path = os.path.join(BASE_DIR, "config", "platform_limits.json")
            if os.path.exists(pl_path):
                with open(pl_path, "r", encoding="utf-8") as fpl:
                    data = json.load(fpl)
            else:
                data = {}
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

        elif self.path.startswith("/api/cleanup/preview"):
            try:
                from safe_cleanup import SafeCleanupManager
                mgr = SafeCleanupManager(base_dir=BASE_DIR, current_job_id=CURRENT_JOB_ID)
                preview_data = mgr.scan_candidates()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, **preview_data}).encode("utf-8"))
            except Exception as e_cp:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_cp)}).encode("utf-8"))
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
            mp4_candidates = []
            seen_mp4 = set()
            if os.path.exists(finished_dir):
                for f in sorted(os.listdir(finished_dir), key=lambda x: os.path.getmtime(os.path.join(finished_dir, x)) if os.path.exists(os.path.join(finished_dir, x)) else 0, reverse=True):
                    if f.endswith(".mp4"):
                        mp4_candidates.append((f, os.path.join(finished_dir, f), f"/finished/{f}"))
                        seen_mp4.add(f)
            if os.path.exists(OUTPUT_DIR):
                for sub in sorted(os.listdir(OUTPUT_DIR), key=lambda x: os.path.getmtime(os.path.join(OUTPUT_DIR, x)) if os.path.exists(os.path.join(OUTPUT_DIR, x)) else 0, reverse=True):
                    sub_p = os.path.join(OUTPUT_DIR, sub)
                    if os.path.isdir(sub_p):
                        for f in os.listdir(sub_p):
                            if f.endswith(".mp4") and f not in seen_mp4:
                                mp4_candidates.append((f, os.path.join(sub_p, f), f"/output/{sub}/{f}"))
                                seen_mp4.add(f)

            for f, path, video_web_url in mp4_candidates:
                size = os.path.getsize(path) if os.path.exists(path) else 0
                clean_id = f.replace(".mp4", "")
                thumb_name = f.replace(".mp4", "_thumb.jpg")
                thumb_webp = f.replace(".mp4", "_thumb.webp")
                thumb_url = None
                p_dir = os.path.dirname(path)
                if os.path.exists(os.path.join(p_dir, thumb_webp)):
                    thumb_url = f"/finished/{thumb_webp}" if p_dir == finished_dir else f"/output/{os.path.basename(p_dir)}/{thumb_webp}"
                elif os.path.exists(os.path.join(finished_dir, thumb_webp)):
                    thumb_url = f"/finished/{thumb_webp}"
                elif os.path.exists(os.path.join(p_dir, thumb_name)):
                    thumb_url = f"/finished/{thumb_name}" if p_dir == finished_dir else f"/output/{os.path.basename(p_dir)}/{thumb_name}"
                elif os.path.exists(os.path.join(p_dir, f.replace(".mp4", "_thumb.png"))):
                    thumb_url = f"/finished/{f.replace('.mp4', '_thumb.png')}"
                else:
                    # Generate real cached WebP frame from video at 2s (avoid contact sheets / stock photos)
                    try:
                        import cv2
                        gen_thumb_path = os.path.join(p_dir, thumb_webp)
                        cap = cv2.VideoCapture(path)
                        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                        cap.set(cv2.CAP_PROP_POS_FRAMES, int(fps * 2))
                        ret, frame = cap.read()
                        cap.release()
                        if ret and frame is not None:
                            cv2.imwrite(gen_thumb_path, frame)
                            if os.path.exists(gen_thumb_path) and os.path.getsize(gen_thumb_path) > 0:
                                thumb_url = f"/finished/{thumb_webp}" if p_dir == finished_dir else f"/output/{os.path.basename(p_dir)}/{thumb_webp}"
                    except Exception:
                        pass
                if not thumb_url:
                    thumb_url = f"/finished/{thumb_webp}"
                mtime = os.path.getmtime(path) if os.path.exists(path) else 0
                date_str = ""

                clean_id = f.replace(".mp4", "")
                mapping_p = os.path.join(finished_dir, f.replace(".mp4", "_mapping.json"))
                if not os.path.exists(mapping_p):
                    alt_mp1 = os.path.join(OUTPUT_DIR, clean_id, f"{clean_id}_mapping.json")
                    if os.path.exists(alt_mp1):
                        mapping_p = alt_mp1
                    else:
                        alt_mp2 = os.path.join(WORK_DIR, clean_id, f"{clean_id}_mapping.json")
                        if os.path.exists(alt_mp2):
                            mapping_p = alt_mp2

                is_169 = ("_long" in f.lower() or "16-9" in f.lower() or "landscape" in f.lower())
                expected_dur = None
                real_dur = None
                clip_cnt = None
                cfg_line = None
                is_test = False
                cat_vtype = "auto"
                ar_from_map = None
                mapping_data = None
                rep_pct = None
                rep_str = None
                stream_w = None
                stream_h = None
                qa_verdict = "NOT RUN"
                overall_passed = False
                quality_score = None
                gates_dict = {}

                if os.path.exists(mapping_p):
                    try:
                        with open(mapping_p, "r", encoding="utf-8") as fm:
                            mapping_data = json.load(fm)
                            expected_dur = mapping_data.get("expected_duration_s") or mapping_data.get("expected_duration")
                            real_dur = mapping_data.get("real_duration_s") or mapping_data.get("total_duration")
                            clip_cnt = mapping_data.get("clip_count")
                            cfg_line = mapping_data.get("config_line")
                            is_test = mapping_data.get("is_test", False)
                            cat_vtype = mapping_data.get("cat_video_type", "auto")
                            ar_from_map = mapping_data.get("aspect_ratio")
                            if "repeat_share_pct" in mapping_data and mapping_data["repeat_share_pct"] is not None:
                                rep_pct = float(mapping_data["repeat_share_pct"])
                                rep_str = mapping_data.get("repeat_share_str")
                    except Exception:
                        pass

                # Load QA Report as single source of truth for specs, verdict, and repeat
                qa_report_candidates = [
                    os.path.join(finished_dir, f"{clean_id}_qa_report.json"),
                    os.path.join(OUTPUT_DIR, clean_id, f"{clean_id}_qa_report.json"),
                    os.path.join(OUTPUT_DIR, clean_id, "qa_report.json"),
                    os.path.join(WORK_DIR, clean_id, f"{clean_id}_qa_report.json"),
                    os.path.join(WORK_DIR, clean_id, "qa_report.json")
                ]
                qa_data = None
                for qp in qa_report_candidates:
                    if os.path.exists(qp):
                        try:
                            with open(qp, "r", encoding="utf-8") as fq:
                                qa_data = json.load(fq)
                                break
                        except Exception:
                            pass

                if qa_data:
                    s_specs = qa_data.get("stream_specs", {})
                    stream_w = s_specs.get("width")
                    stream_h = s_specs.get("height")
                    qa_verdict = qa_data.get("verdict", "NOT RUN")
                    overall_passed = bool(qa_data.get("overall_passed", False))
                    gates_dict = qa_data.get("gates", {})
                    if "repeat_share_pct" in qa_data and qa_data["repeat_share_pct"] is not None:
                        rep_pct = float(qa_data["repeat_share_pct"])
                        rep_str = qa_data.get("repeat_share_str")
                    if "peak_quality_gate" in qa_data and isinstance(qa_data["peak_quality_gate"], dict):
                        quality_score = qa_data["peak_quality_gate"].get("overall_score") or quality_score

                # Check executive report.json for additional verification
                report_candidates = [
                    os.path.join(finished_dir, f"{clean_id}_report.json"),
                    os.path.join(OUTPUT_DIR, clean_id, f"{clean_id}_report.json"),
                    os.path.join(OUTPUT_DIR, clean_id, "report.json")
                ]
                for rp in report_candidates:
                    if os.path.exists(rp):
                        try:
                            with open(rp, "r", encoding="utf-8") as fr:
                                rep_obj = json.load(fr)
                                sum_obj = rep_obj.get("summary", {})
                                if rep_pct is None and "repeat_share_pct" in sum_obj:
                                    rep_pct = float(sum_obj["repeat_share_pct"])
                                if "qa_verdict" in sum_obj:
                                    qa_verdict = sum_obj["qa_verdict"]
                                break
                        except Exception:
                            pass

                # If repeat share not explicitly found, compute from mapping clips using canonical function
                if rep_pct is None:
                    try:
                        import qa_check
                        rep_pct, rep_str = qa_check.calculate_repeat_share(mapping_data)
                    except Exception:
                        rep_pct = 0.0
                        rep_str = "0% repeat (100% unique moments)"
                elif rep_str is None:
                    rep_str = f"{rep_pct:.1f}% repeat moments" if rep_pct > 0 else "0% repeat (100% unique moments)"

                if not is_test:
                    clean_id_lower = str(clean_id).lower()
                    is_test = bool(
                        clean_id_lower.startswith("job_real_contract") or
                        clean_id_lower.startswith("test_") or
                        "contract" in clean_id_lower or
                        "test" in clean_id_lower or
                        "acceptance" in clean_id_lower or
                        "sandbox" in clean_id_lower
                    )

                if (real_dur is None or stream_w is None or stream_h is None) and os.path.exists(path):
                    try:
                        import cv2
                        cap = cv2.VideoCapture(path)
                        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                        fcnt = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                        if fps > 0 and fcnt > 0 and real_dur is None:
                            real_dur = round(fcnt / fps, 2)
                        if stream_w is None or stream_h is None:
                            pw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                            ph = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                            if pw > 0 and ph > 0:
                                stream_w = pw
                                stream_h = ph
                        cap.release()
                    except Exception:
                        pass

                is_comp = False
                if cfg_line and "mode=compilation" in cfg_line:
                    is_comp = True
                elif (real_dur and real_dur >= 60.0) or (expected_dur and expected_dur >= 60.0) or (clip_cnt and clip_cnt > 4):
                    is_comp = True
                elif "_long" in f.lower() or "compilation" in f.lower():
                    is_comp = True

                dur_s = int(round(real_dur)) if real_dur else 0
                dur_tag = f"{dur_s//60}:{dur_s%60:02d}" if (0 < dur_s < 3600) else (f"{dur_s//3600}:{(dur_s%3600)//60:02d}:{dur_s%60:02d}" if dur_s >= 3600 else "--:--")

                # Duration variance and contract check
                dur_var_s = round(real_dur - expected_dur, 1) if (real_dur is not None and expected_dur is not None) else 0.0
                dur_diff_tag = ""
                if expected_dur and abs(dur_var_s) > 1.0:
                    sign = "+" if dur_var_s > 0 else ""
                    dur_diff_tag = f" ({sign}{int(round(dur_var_s))}s)"
                elif expected_dur and abs(dur_var_s) <= 1.0:
                    dur_diff_tag = " (OK)"

                # Unified timestamp parsing (stored UTC, rendered Asia/Colombo)
                created_utc_iso = None
                timestamp_utc = None
                if qa_data and qa_data.get("_generated_at_utc"):
                    created_utc_iso = qa_data.get("_generated_at_utc")
                if not created_utc_iso and 'rep_obj' in locals() and rep_obj and rep_obj.get("_generated_at_utc"):
                    created_utc_iso = rep_obj.get("_generated_at_utc")

                if created_utc_iso:
                    try:
                        from datetime import datetime, timezone, timedelta
                        dt_utc = datetime.fromisoformat(created_utc_iso.replace("Z", "+00:00"))
                        timestamp_utc = dt_utc.timestamp()
                    except Exception:
                        pass

                if timestamp_utc is None:
                    timestamp_utc = mtime if mtime > 0 else time.time()

                from datetime import datetime, timezone, timedelta
                tz_colombo = timezone(timedelta(hours=5, minutes=30))
                dt_colombo = datetime.fromtimestamp(timestamp_utc, tz_colombo)
                date_str = dt_colombo.strftime("%b %d, %Y • %H:%M")
                created_utc_iso = datetime.fromtimestamp(timestamp_utc, timezone.utc).isoformat()

                # Derive aspect ratio strictly from real probed video dimensions
                if stream_w and stream_h:
                    if stream_w > stream_h:
                        aspect_ratio_val = "16:9"
                    elif stream_h > stream_w:
                        aspect_ratio_val = "9:16"
                    else:
                        aspect_ratio_val = "1:1"
                else:
                    aspect_ratio_val = ar_from_map or ("16:9" if is_169 else "9:16")

                if aspect_ratio_val == "16:9":
                    format_lbl = "16:9 Long video" if (is_comp or (real_dur and real_dur >= 60.0)) else "16:9 Short"
                    final_w = stream_w or 1920
                    final_h = stream_h or 1080
                elif aspect_ratio_val == "1:1":
                    format_lbl = "1:1 Square"
                    final_w = stream_w or 1080
                    final_h = stream_h or 1080
                else:
                    format_lbl = "9:16 Compilation" if (is_comp or (real_dur and real_dur >= 60.0)) else "9:16 Short"
                    final_w = stream_w or 1080
                    final_h = stream_h or 1920

                # Enforce even dimensions
                final_w = int(final_w // 2) * 2
                final_h = int(final_h // 2) * 2

                v_match = re.search(r'_v(\d+)$', clean_id)
                if v_match:
                    base_root = re.sub(r'_v\d+$', '', clean_id)
                    ver_num = int(v_match.group(1))
                    ver_str = f"v{ver_num}"
                else:
                    base_root = clean_id
                    ver_num = 1
                    ver_str = "v1"

                import thumbnail_maker
                thumb_allowed, _ = thumbnail_maker.is_thumbnail_supported_for_job(clean_id)
                files.append({
                    "name": f,
                    "job_id": clean_id,
                    "base_root": base_root,
                    "version": ver_str,
                    "version_num": ver_num,
                    "sizeBytes": size,
                    "type": "video",
                    "url": video_web_url,
                    "thumbnail": thumb_url,
                    "thumbnail_available": thumb_allowed,
                    "is_short": (not thumb_allowed),
                    "is169": (aspect_ratio_val == "16:9"),
                    "aspectRatio": aspect_ratio_val,
                    "cat_video_type": cat_vtype,
                    "is_test": is_test,
                    "duration": real_dur,
                    "duration_str": dur_tag,
                    "duration_diff_str": dur_diff_tag,
                    "duration_variance_s": dur_var_s,
                    "expected_duration_s": expected_dur,
                    "clip_count": clip_cnt,
                    "config_line": cfg_line,
                    "is_compilation": is_comp,
                    "format_label": format_lbl,
                    "mtime": mtime,
                    "timestamp_utc": timestamp_utc,
                    "created_utc": created_utc_iso,
                    "created_date_str": date_str,
                    "width": final_w,
                    "height": final_h,
                    "repeat_share_pct": rep_pct,
                    "repeat_share_str": rep_str,
                    "verdict": qa_verdict,
                    "attention_items": (qa_data.get("unified_verdict") or {}).get("attention_items", []) if qa_data else [],
                    "overall_passed": overall_passed,
                    "quality_score": quality_score,
                    "gates": gates_dict
                })

            if os.path.exists(finished_dir):
                for f in os.listdir(finished_dir):
                    if f.endswith(".txt"):
                        path = os.path.join(finished_dir, f)
                        size = os.path.getsize(path) if os.path.exists(path) else 0
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
            
            test_videos = [v for v in video_files if v.get("is_test")]
            real_videos = [v for v in video_files if not v.get("is_test")]

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "files": files,
                "total_count": len(video_files),
                "real_count": len(real_videos),
                "test_count": len(test_videos)
            }).encode())
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


        elif (self.path.startswith("/finished/") or 
              self.path.startswith("/raw/") or 
              self.path.startswith("/work/") or 
              self.path.startswith("/output/")):
            # Serve media and artifacts from finished, raw, work, or output with full Range support
            clean_path = self.path.split("?")[0].split("#")[0]
            rel_path = ""
            base_dir = FINISHED_DIR
            if clean_path.startswith("/finished/"):
                rel_path = urllib.parse.unquote(clean_path[len("/finished/"):].lstrip("/\\"))
                base_dir = FINISHED_DIR
            elif clean_path.startswith("/raw/"):
                rel_path = urllib.parse.unquote(clean_path[len("/raw/"):].lstrip("/\\"))
                base_dir = RAW_DIR
            elif clean_path.startswith("/work/"):
                rel_path = urllib.parse.unquote(clean_path[len("/work/"):].lstrip("/\\"))
                base_dir = WORK_DIR
            elif clean_path.startswith("/output/"):
                rel_path = urllib.parse.unquote(clean_path[len("/output/"):].lstrip("/\\"))
                base_dir = OUTPUT_DIR

            filepath = os.path.normpath(os.path.join(base_dir, rel_path))

            # Fallback search across directories if primary path doesn't exist
            if not (os.path.exists(filepath) and os.path.isfile(filepath)):
                fname = os.path.basename(rel_path)
                candidates = [
                    os.path.join(FINISHED_DIR, fname),
                    os.path.join(OUTPUT_DIR, fname),
                    os.path.join(WORK_DIR, fname),
                    os.path.join(RAW_DIR, fname),
                ]
                for candidate_root in (OUTPUT_DIR, WORK_DIR):
                    if os.path.exists(candidate_root):
                        try:
                            for sub in os.listdir(candidate_root):
                                cand_sub = os.path.join(candidate_root, sub, fname)
                                candidates.append(cand_sub)
                        except Exception:
                            pass
                for cand in candidates:
                    if os.path.exists(cand) and os.path.isfile(cand):
                        filepath = cand
                        break

            if os.path.exists(filepath) and os.path.isfile(filepath):
                file_size = os.path.getsize(filepath)
                lower = filepath.lower()
                content_type = "application/octet-stream"
                if lower.endswith(".mp4"):
                    content_type = "video/mp4"
                elif lower.endswith(".webm"):
                    content_type = "video/webm"
                elif lower.endswith(".mov"):
                    content_type = "video/quicktime"
                elif lower.endswith(".webp"):
                    content_type = "image/webp"
                elif lower.endswith(".jpg") or lower.endswith(".jpeg"):
                    content_type = "image/jpeg"
                elif lower.endswith(".png"):
                    content_type = "image/png"
                elif lower.endswith(".gif"):
                    content_type = "image/gif"
                elif lower.endswith(".svg"):
                    content_type = "image/svg+xml"
                elif lower.endswith(".json"):
                    content_type = "application/json"
                elif lower.endswith(".txt") or lower.endswith(".log"):
                    content_type = "text/plain; charset=utf-8"
                elif lower.endswith(".pdf"):
                    content_type = "application/pdf"

                range_header = self.headers.get("Range")
                if range_header and lower.endswith((".mp4", ".webm", ".mov")) and "bytes=" in range_header:
                    try:
                        bytes_range = range_header.split("=")[1].strip()
                        parts = bytes_range.split("-")
                        if not parts[0]:
                            suffix_len = int(parts[1]) if len(parts) > 1 and parts[1] else 0
                            start = max(0, file_size - suffix_len)
                            end = file_size - 1
                        else:
                            start = int(parts[0])
                            end = int(parts[1]) if (len(parts) > 1 and parts[1]) else file_size - 1

                        if start >= file_size or start > end:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{file_size}")
                            self.send_header("Accept-Ranges", "bytes")
                            self.end_headers()
                            return

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
                    except (BrokenPipeError, ConnectionResetError, OSError):
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
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                except Exception:
                    pass
                return
            else:
                if clean_path.endswith((".webp", ".png", ".jpg", ".jpeg")):
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    blank_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82'
                    self.send_header("Content-Length", str(len(blank_png)))
                    self.end_headers()
                    try:
                        self.wfile.write(blank_png)
                    except Exception:
                        pass
                    return
                self.send_error(404, "File not found")
                return

        if clean_path in ("/api/stop", "/api/force-stop", "/api/cleanup-stuck-job") or clean_path.startswith("/api/cleanup-stuck-job"):
            return self.do_POST()

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
        import urllib.parse
        clean_path = self.path.split("?")[0]
        
        if clean_path == "/api/server/restart":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "message": "Server restarting"}).encode())
            def _restart():
                time.sleep(0.5)
                os._exit(0)
            threading.Thread(target=_restart, daemon=True).start()
            return

        content_length = int(self.headers.get('Content-Length', 0) or 0)

        # Handle binary streaming uploads directly from self.rfile
        if self.path.startswith("/api/upload"):
            try:
                filename = ""
                if "filename=" in self.path:
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

        elif self.path.startswith("/api/settings/metadata-mode"):
            try:
                body = json.loads(post_data) if post_data else {}
                mode = body.get("upload_metadata_mode", body.get("mode", "full"))
                cfg = load_config()
                cfg["UPLOAD_METADATA_MODE"] = mode
                save_config(cfg)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "upload_metadata_mode": mode}).encode())
            except Exception as e_mm:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_mm)}).encode())
            return

        elif self.path.startswith("/api/cleanup/preview"):
            try:
                from safe_cleanup import SafeCleanupManager
                mgr = SafeCleanupManager(base_dir=BASE_DIR, current_job_id=CURRENT_JOB_ID)
                preview_data = mgr.scan_candidates()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, **preview_data}).encode("utf-8"))
            except Exception as e_cp:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_cp)}).encode("utf-8"))
            return

        elif self.path.startswith("/api/cleanup/execute"):
            try:
                from safe_cleanup import SafeCleanupManager
                body = json.loads(post_data) if post_data else {}
                selected_groups = body.get("selected_groups", [])
                dry_run = bool(body.get("dry_run", False))
                use_recycle_bin = bool(body.get("use_recycle_bin", True))
                confirmed = bool(body.get("confirmed", False))
                mgr = SafeCleanupManager(base_dir=BASE_DIR, current_job_id=CURRENT_JOB_ID)
                res_exec = mgr.execute_cleanup(
                    selected_groups=selected_groups,
                    dry_run=dry_run,
                    use_recycle_bin=use_recycle_bin,
                    confirmed=confirmed
                )
                status_code = 200 if res_exec.get("success") else 400
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res_exec).encode("utf-8"))
            except Exception as e_ce:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_ce)}).encode("utf-8"))
            return

        elif self.path.startswith("/api/delete-file"):
            try:
                params = json.loads(post_data) if post_data else {}
                filename = params.get("filename", "")
                if not filename and "file=" in self.path:
                    import urllib.parse
                    filename = urllib.parse.unquote(self.path.split("file=")[1].split("&")[0])
                elif not filename and "filename=" in self.path:
                    import urllib.parse
                    filename = urllib.parse.unquote(self.path.split("filename=")[1].split("&")[0])
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
        elif clean_path == "/api/filler/toggle":
            try:
                from clip_bank_filler import ClipBankFiller
                filler = ClipBankFiller()
                is_p = filler.toggle_pause()
                f_status = filler.get_status()
                resp_bytes = json.dumps({"success": True, "paused": is_p, "status": f_status}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
            except Exception as e_ft:
                err_b = json.dumps({"success": False, "error": str(e_ft)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_b)))
                self.end_headers()
                self.wfile.write(err_b)
        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/open-folder"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                target_dir = os.path.join(OUTPUT_DIR, job_id)
                if not os.path.exists(target_dir):
                    target_dir = FINISHED_DIR
                target_dir = os.path.normpath(os.path.abspath(target_dir))
                subprocess.Popen(["explorer.exe", target_dir])
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "path": target_dir}).encode())
            except Exception as e_of:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_of)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/thumbnails/render"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                params = json.loads(post_data) if post_data else {}
                import thumbnail_maker
                cand_path = params.get("candidate_frame_path", "")
                cand_idx = int(params.get("candidate_index", 0) or 0)
                if not cand_path or not os.path.exists(cand_path):
                    thumb_dir = os.path.join(OUTPUT_DIR, job_id, "thumbnails")
                    if os.path.exists(thumb_dir):
                        c_files = sorted([os.path.join(thumb_dir, f) for f in os.listdir(thumb_dir) if f.startswith("cand_frame_") and f.endswith(".jpg")])
                        if c_files and 0 <= cand_idx < len(c_files):
                            cand_path = c_files[cand_idx]
                        elif c_files:
                            cand_path = c_files[0]
                template = params.get("template", "subject_right_text_left")
                hook_text = params.get("hook_text", "FUNNY CAT MOMENTS")
                preset = params.get("color_preset", "high_contrast_yellow")
                badge_text = params.get("duration_badge_text", "20 MIN")
                res = thumbnail_maker.render_thumbnail_preview(
                    job_id=job_id,
                    candidate_frame_path=cand_path,
                    template=template,
                    hook_text=hook_text,
                    color_preset=preset,
                    duration_badge_text=badge_text
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res, default=str).encode())
            except Exception as e_ren:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_ren)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/thumbnails/save"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                params = json.loads(post_data) if post_data else {}
                import thumbnail_maker
                cand_path = params.get("candidate_frame_path", "")
                cand_idx = int(params.get("candidate_index", 0) or 0)
                if not cand_path or not os.path.exists(cand_path):
                    thumb_dir = os.path.join(OUTPUT_DIR, job_id, "thumbnails")
                    if os.path.exists(thumb_dir):
                        c_files = sorted([os.path.join(thumb_dir, f) for f in os.listdir(thumb_dir) if f.startswith("cand_frame_") and f.endswith(".jpg")])
                        if c_files and 0 <= cand_idx < len(c_files):
                            cand_path = c_files[cand_idx]
                        elif c_files:
                            cand_path = c_files[0]
                template = params.get("template", "subject_right_text_left")
                hook_text = params.get("hook_text", "FUNNY CAT MOMENTS")
                preset = params.get("color_preset", "high_contrast_yellow")
                badge_text = params.get("duration_badge_text", "20 MIN")
                res = thumbnail_maker.save_custom_thumbnail(
                    job_id=job_id,
                    candidate_frame_path=cand_path,
                    template=template,
                    hook_text=hook_text,
                    color_preset=preset,
                    duration_badge_text=badge_text
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res, default=str).encode())
            except Exception as e_sav:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_sav)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and (clean_path.endswith("/thumbnail/set-active") or clean_path.endswith("/thumbnails/use-this")):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                params = json.loads(post_data) if post_data else {}
                cand_idx = int(params.get("candidate_index", params.get("index", 0)) or 0)
                import thumbnail_maker
                res = thumbnail_maker.set_active_thumbnail_candidate(job_id, cand_idx)
                self.send_response(200 if res.get("success") else 400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res, default=str).encode())
            except Exception as e_sa:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_sa)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/thumbnails/fresh"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                params = json.loads(post_data) if post_data else {}
                exclude_ts = params.get("exclude_timestamps", [])
                import thumbnail_maker
                res = thumbnail_maker.generate_job_thumbnails(job_id, exclude_timestamps=exclude_ts)
                self.send_response(200 if res.get("success") else 400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res, default=str).encode())
            except Exception as e_fr:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_fr)}).encode())
            return

        elif clean_path.startswith("/api/jobs/") and clean_path.endswith("/thumbnail/upload-youtube"):
            parts = clean_path.split("/")
            job_id = parts[3]
            try:
                params = json.loads(post_data) if post_data else {}
                video_id = params.get("video_id")
                import thumbnail_maker
                res = thumbnail_maker.upload_thumbnail_to_youtube(job_id, video_id=video_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res, default=str).encode())
            except Exception as e_up:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "status_line": f"Upload failure: {str(e_up)}"}).encode())
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
                from safe_cleanup import SafeCleanupManager, CANDIDATE_GROUPS
                body = json.loads(post_data) if post_data else {}
                selected_groups = body.get("selected_groups") or list(CANDIDATE_GROUPS.keys())
                dry_run = bool(body.get("dry_run", False))
                use_recycle_bin = bool(body.get("use_recycle_bin", True))
                confirmed = bool(body.get("confirmed", True))
                mgr = SafeCleanupManager(base_dir=BASE_DIR, current_job_id=CURRENT_JOB_ID)
                res_exec = mgr.execute_cleanup(
                    selected_groups=selected_groups,
                    dry_run=dry_run,
                    use_recycle_bin=use_recycle_bin,
                    confirmed=confirmed
                )
                removed_files = [r["rel_path"] for r in res_exec.get("removed_paths", [])]
                freed_bytes = res_exec.get("freed_bytes", 0)
                freed_mb = res_exec.get("freed_mb", 0.0)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "removed_count": len(removed_files),
                    "freed_bytes": freed_bytes,
                    "freed_mb": freed_mb,
                    "removed_files": removed_files,
                    "drive_trash_notice": res_exec.get("drive_trash_notice", ""),
                    "log_path": res_exec.get("log_path", ""),
                    "message": res_exec.get("message", f"Safely cleaned {len(removed_files)} items ({freed_mb} MB). Finished production videos and bank clips are strictly protected.")
                }).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
            return

        elif self.path.startswith("/api/clear-error") or self.path.startswith("/api/dismiss-error"):
            LAST_EXIT_CODE = None
            CURRENT_JOB_ID = None
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
            from engine_lock import get_active_engine_lock
            active_lock = get_active_engine_lock()
            if is_running or active_lock:
                active_job_id = CURRENT_JOB_ID or (active_lock.get("job_id") if active_lock else "unknown")
                active_pid = RUNNING_PROCESS.pid if (RUNNING_PROCESS and RUNNING_PROCESS.poll() is None) else (active_lock.get("pid") if active_lock else "unknown")
                self.send_response(409)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": f"An engine process is already running for job {active_job_id} (PID {active_pid}). Only one engine run is allowed at a time.",
                    "reason_code": "ENGINE_ALREADY_RUNNING",
                    "job_id": active_job_id,
                    "pid": active_pid
                }).encode())
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
            cfg["ANIMAL_MODE"] = norm_cfg.get("animal_mode") or norm_cfg.get("mode", "cat")
            cfg["ASPECT_RATIO"] = norm_cfg["aspect_ratio"]
            cfg["VIDEO_CAT_TYPE"] = norm_cfg["video_cat_type"]
            save_config(cfg)

            # Generate unique job_id (timestamp + uuid)
            ts_str = time.strftime('%Y%m%d_%H%M%S')
            CURRENT_JOB_ID = f"lionreel_{norm_cfg.get('animal_mode') or norm_cfg.get('mode', 'cat')}_{ts_str}_{uuid.uuid4().hex[:8]}"

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
            try:
                with open(os.path.join(work_job_dir, "job_result.json"), "w", encoding="utf-8") as f_job_init:
                    json.dump({
                        "job_id": CURRENT_JOB_ID,
                        "status": "running",
                        "success": None,
                        "stage_index": 1,
                        "stage_name": "Collect candidate moments from ledger",
                        "progress_pct": 0,
                        "elapsed_seconds": 0
                    }, f_job_init, indent=2)
            except Exception:
                pass

            # Write immutable job configuration snapshot
            import job_options
            job_options.load_or_verify_job_config(CURRENT_JOB_ID, norm_cfg)

            # Pre-compute and persist initial predicted time and deadline (Section 1)
            try:
                from stage_estimator import StageEstimator
                from clip_ledger import ClipLedger
                _est = StageEstimator()
                _ledger = ClipLedger()
                _bank_ready = _ledger.get_pool_ready_and_capacity(norm_cfg.get("animal_mode") or norm_cfg.get("mode", "cat")).get("ready", 0)
                _tgt_clips = int(norm_cfg.get("clips") or 6)
                _tgt_clip_sec = float(norm_cfg.get("clip_time") or 7.5)
                _contract_sec = float(norm_cfg.get("target_duration_s") or (_tgt_clips * _tgt_clip_sec))
                _est.compute_predicted_time_and_deadline(
                    target_clips_count=_tgt_clips,
                    target_clip_sec=_tgt_clip_sec,
                    contract_total_sec=_contract_sec,
                    bank_verified_count=_bank_ready,
                    start_epoch=time.time(),
                    job_id=CURRENT_JOB_ID,
                    work_dir=work_job_dir
                )
            except Exception as e_dl:
                print(f"Notice: initial deadline calculation: {e_dl}")

            # Copy active draft EDL into the new job directory only if explicitly requested
            draft_edl = os.path.join(WORK_DIR, "active_draft", "edl.json")
            job_edl = os.path.join(work_job_dir, "edl.json")
            if os.path.exists(draft_edl) and (cfg.get("use_draft") or cfg.get("from_draft") or cfg.get("render_draft")):
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
                local_venv_py = lion_paths.venv_python()
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
            from watchdog_service import terminate_process_tree, cleanup_stuck_job
            from engine_lock import get_active_engine_lock, release_engine_lock

            active_lock = get_active_engine_lock()
            target_pid = None
            if RUNNING_PROCESS is not None and RUNNING_PROCESS.poll() is None:
                target_pid = RUNNING_PROCESS.pid
            elif active_lock and active_lock.get("pid"):
                target_pid = active_lock.get("pid")

            stopped = True
            stop_msg = "No process active"
            if target_pid:
                stopped, stop_msg = terminate_process_tree(target_pid, timeout_sec=5.0)

            if not stopped:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "message": f"Process {target_pid} did not terminate within 5s: {stop_msg}",
                    "force_stop_available": True,
                    "pid": target_pid,
                    "job_id": CURRENT_JOB_ID or (active_lock.get("job_id") if active_lock else None)
                }).encode())
                return

            RUNNING_PROCESS = None
            RUNNING_PROCESS_START_TIME = None

            job_to_clean = CURRENT_JOB_ID or (active_lock.get("job_id") if active_lock else None)
            cleanup_info = None
            if job_to_clean:
                cleanup_info = cleanup_stuck_job(job_to_clean, stop_process=False)
                CURRENT_JOB_ID = None
            else:
                release_engine_lock("unknown")

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
            self.wfile.write(json.dumps({
                "success": True,
                "message": "Process stopped successfully",
                "cleanup": cleanup_info
            }).encode())
            return

        elif self.path.startswith("/api/force-stop"):
            from watchdog_service import terminate_process_tree, cleanup_stuck_job
            from engine_lock import get_active_engine_lock, release_engine_lock

            active_lock = get_active_engine_lock()
            target_pid = None
            if RUNNING_PROCESS is not None:
                target_pid = RUNNING_PROCESS.pid
            elif active_lock and active_lock.get("pid"):
                target_pid = active_lock.get("pid")

            if target_pid:
                terminate_process_tree(target_pid, timeout_sec=1.0)

            RUNNING_PROCESS = None
            RUNNING_PROCESS_START_TIME = None

            job_to_clean = CURRENT_JOB_ID or (active_lock.get("job_id") if active_lock else None)
            cleanup_info = None
            if job_to_clean:
                cleanup_info = cleanup_stuck_job(job_to_clean, stop_process=False)
                CURRENT_JOB_ID = None
            else:
                release_engine_lock("unknown")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "message": "Process forcibly stopped",
                "cleanup": cleanup_info
            }).encode())
            return

        elif self.path.startswith("/api/cleanup-stuck-job"):
            from watchdog_service import cleanup_stuck_job, detect_stale_jobs
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            target_job = query_params.get("job_id", [None])[0]
            if not target_job and post_data:
                try:
                    payload = json.loads(post_data)
                    target_job = payload.get("job_id")
                except Exception:
                    pass

            cleaned = []
            if target_job:
                c_res = cleanup_stuck_job(target_job)
                cleaned.append(c_res)
            else:
                stale_list = detect_stale_jobs(WORK_DIR, max_stale_sec=60.0)
                for sj in stale_list:
                    c_res = cleanup_stuck_job(sj["job_id"])
                    cleaned.append(c_res)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "cleaned_jobs": cleaned,
                "count": len(cleaned)
            }).encode())
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

                    local_venv_py = lion_paths.venv_python()
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

                elif action in ("find_new_footage_now", "harvest_and_resume", "keep_searching", "keep_waiting"):
                    from harvest_worker import trigger_background_harvest_if_needed
                    trigger_background_harvest_if_needed(animal_mode="cat", target_clips_needed=60)
                    if target_job:
                        jres_path = os.path.join(WORK_DIR, target_job, "job_result.json")
                        waiting_payload = {
                            "job_id": target_job,
                            "status": "waiting_for_clips",
                            "waiting": True,
                            "message": "Finding new footage in background"
                        }
                        for jp in [JOB_RESULT_FILE, jres_path]:
                            try:
                                with open(jp, "w", encoding="utf-8") as f_w:
                                    json.dump(waiting_payload, f_w, indent=2)
                            except Exception:
                                pass
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "action": "find_new_footage_now", "status": "waiting_for_clips"}).encode())
                    return

                elif action in ("resume_when_ready", "wait_background"):
                    if target_job:
                        jres_path = os.path.join(WORK_DIR, target_job, "job_result.json")
                        waiting_payload = {
                            "job_id": target_job,
                            "status": "waiting_for_clips",
                            "waiting": True,
                            "message": "Waiting for footage in background"
                        }
                        for jp in [JOB_RESULT_FILE, jres_path]:
                            try:
                                with open(jp, "w", encoding="utf-8") as f_w:
                                    json.dump(waiting_payload, f_w, indent=2)
                            except Exception:
                                pass
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "action": "resume_when_ready", "status": "waiting_for_clips"}).encode())
                    return

                elif action in ("allow_reuse_old_footage", "allow_reuse"):
                    local_venv_py = lion_paths.venv_python()
                    py_exe = local_venv_py if os.path.exists(local_venv_py) else (sys.executable or "python")
                    job_log_file = os.path.join(WORK_DIR, target_job, "job.log") if target_job else LOG_FILE
                    log_fd = open(job_log_file, "a", encoding="utf-8", errors="ignore")
                    import job_options
                    try:
                        job_cfg = job_options.load_or_verify_job_config(target_job)
                    except Exception:
                        job_cfg = {"mode": "cat", "type": "short", "layout": "smart_crop"}
                    job_cfg["allow_reuse"] = True
                    job_options.save_job_config(target_job, job_cfg)
                    RUNNING_PROCESS_START_TIME = time.time()
                    cli_args = job_options.build_cli_args(job_cfg, target_job, RUNNING_PROCESS_START_TIME)
                    if "--allow-reuse" not in cli_args:
                        cli_args.append("--allow-reuse")
                    cmd = [py_exe, "-u", "lion_automate_v97.py"] + cli_args
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
                    self.wfile.write(json.dumps({"success": True, "job_id": target_job, "action": "allow_reuse"}).encode())
                    return

                elif action == "cancel":
                    if RUNNING_PROCESS:
                        try:
                            if os.name == 'nt':
                                subprocess.run(["taskkill", "/F", "/T", "/PID", str(RUNNING_PROCESS.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
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

        elif self.path.startswith("/api/harvest/stop") or self.path.startswith("/api/harvest-stop"):
            try:
                from harvest_worker import stop_harvest_worker
                stop_harvest_worker()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": "Harvest stopped"}).encode())
                return
            except Exception as e_hstop:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e_hstop)}).encode())
                return

        elif self.path.startswith("/api/create-shortcut"):
            if os.name != 'nt':
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "Creating desktop shortcuts is only supported on Windows. Since this is running in the cloud (Linux/Codespaces), please bookmark this webpage in your browser instead!"}).encode())
                return
            try:
                params = json.loads(post_data) if post_data else {}
                hotkey = params.get("hotkey", "CTRL+ALT+L")
                
                from scripts.create_desktop_shortcut import create_shortcut
                success, msg = create_shortcut(hotkey=hotkey)
                
                if success:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "message": msg}).encode())
                else:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": msg}).encode())
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
                    python_exe = lion_paths.venv_python()
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
