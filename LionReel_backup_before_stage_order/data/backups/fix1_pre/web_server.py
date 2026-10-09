import os
import sys
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
    "TARGET_CLIPS": "6",
    "SHORT_CLIP_SEC": "5.5",
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
                    RUNNING_PROCESS = None
                    RUNNING_PROCESS_START_TIME = None
            
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
            elif job_res and job_res.get("status") == "completed" and job_res.get("success"):
                computed_status = "completed"
            elif job_res and (job_res.get("status") == "error" or job_res.get("success") is False):
                computed_status = "error"
            elif LAST_EXIT_CODE is not None:
                if LAST_EXIT_CODE == 0 and job_res and job_res.get("success"):
                    computed_status = "completed"
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

            resp_data = {
                "status": computed_status,
                "job_id": job_id,
                "isRunning": is_running,
                "startTimeMs": start_time_ms,
                "elapsedSeconds": elapsed_sec,
                "stageIndex": (job_res.get("stage_index") if job_res else (10 if computed_status == "completed" else 1)),
                "stageName": (job_res.get("stage_name") if job_res else ""),
                "progressPct": (job_res.get("progress_pct") if job_res else (100 if computed_status == "completed" else 5)),
                "candidateReports": (job_res.get("candidate_reports", []) if job_res else []),
                "failedStage": (job_res.get("failed_stage") if job_res else None),
                "exitCode": LAST_EXIT_CODE,
                "jobResult": job_res,
                "harvestStatus": harvest_info,
                "generatedFile": job_res.get("output_file") if (job_res and job_res.get("success")) else None,
                "sha256": job_res.get("sha256") if (job_res and job_res.get("success")) else None,
                "clipList": job_res.get("clip_list") if (job_res and job_res.get("success")) else [],
                "duration": job_res.get("duration") if (job_res and job_res.get("success")) else None,
                "renderTimeSec": job_res.get("render_time_sec") if (job_res and job_res.get("success")) else None,
                "error": job_res.get("error") if (job_res and not job_res.get("success")) else (
                    f"Process exited with error code {LAST_EXIT_CODE}" if LAST_EXIT_CODE not in (None, 0) else None
                )
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(json.dumps(resp_data).encode())
            return

        elif self.path.startswith("/api/harvest-status"):
            try:
                from harvest_worker import get_harvest_status
                h_data = get_harvest_status()
            except Exception as e_h:
                h_data = {"is_harvesting": False, "error": str(e_h)}
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

            # Locate per-job log file first, fall back to global LOG_FILE
            log_paths = []
            if target_job_id:
                log_paths.append(os.path.join(WORK_DIR, target_job_id, "job.log"))
                log_paths.append(os.path.join(OUTPUT_DIR, target_job_id, f"{target_job_id}.log"))
                log_paths.append(os.path.join(FINISHED_DIR, f"{target_job_id}.log"))
            log_paths.append(os.path.join(BASE_DIR, LOG_FILE))

            active_log_file = None
            for lp in log_paths:
                if os.path.exists(lp) and os.path.getsize(lp) > 0:
                    active_log_file = lp
                    break
            if not active_log_file:
                active_log_file = os.path.join(BASE_DIR, LOG_FILE)

            logs_text = ""
            new_offset = offset
            lines_list = []
            last_seq = req_seq

            if os.path.exists(active_log_file):
                try:
                    with open(active_log_file, "r", encoding="utf-8", errors="ignore") as f:
                        all_lines = f.readlines()
                    
                    # Parse lines and extract real [SEQ:N] if present
                    for line_idx, line_str in enumerate(all_lines, 1):
                        clean_str = line_str.rstrip("\r\n")
                        seq_match = re.search(r'\[SEQ:(\d+)\]', clean_str)
                        cur_seq = int(seq_match.group(1)) if seq_match else line_idx
                        # Only return lines beyond the requested sequence
                        if cur_seq > req_seq:
                            lines_list.append({"seq": cur_seq, "text": clean_str})
                            last_seq = max(last_seq, cur_seq)

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
                        files.append({
                            "name": f,
                            "sizeBytes": size,
                            "type": "video",
                            "url": f"/finished/{f}",
                            "thumbnail": thumb_url,
                            "is169": is_169,
                            "aspectRatio": "16:9" if is_169 else "9:16"
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


        elif self.path.startswith("/finished/"):
            # Serve files from finished directory directly
            clean_path = self.path.split("?")[0].split("#")[0]
            filename = urllib.parse.unquote(clean_path.replace("/finished/", ""))
            filepath = os.path.join(FINISHED_DIR, filename)
            if os.path.exists(filepath):
                file_size = os.path.getsize(filepath)
                lower = filename.lower()
                content_type = "text/plain"
                if lower.endswith(".mp4"):
                    content_type = "video/mp4"
                elif lower.endswith(".jpg") or lower.endswith(".jpeg"):
                    content_type = "image/jpeg"
                elif lower.endswith(".png"):
                    content_type = "image/png"
                elif lower.endswith(".json"):
                    content_type = "application/json"

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
        global RUNNING_PROCESS, RUNNING_PROCESS_START_TIME, LAST_EXIT_CODE
        
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
            global CURRENT_JOB_ID
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

            animal_mode = "cat"
            use_cache = False
            layout_mode = "smart_crop"
            if post_data:
                try:
                    cfg = json.loads(post_data)
                    animal_mode = cfg.get("ANIMAL_MODE") or cfg.get("VIDEO_MODE") or "cat"
                    use_cache = bool(cfg.get("USE_CACHE", False))
                    layout_mode = cfg.get("LAYOUT_MODE", "smart_crop")
                    save_config(cfg)
                except Exception as e_cfg:
                    print(f"Error saving config before start: {e_cfg}")

            # Generate unique job_id (timestamp + uuid)
            ts_str = time.strftime('%Y%m%d_%H%M%S')
            CURRENT_JOB_ID = f"lionreel_{animal_mode}_{ts_str}_{uuid.uuid4().hex[:8]}"

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

            launch_banner = f"=== Launching LionReel Automation Script (Job: {CURRENT_JOB_ID}) ===\n"

            # Clear and initialize log file
            try:
                with open(job_log_file, "w", encoding="utf-8") as f_jlog:
                    f_jlog.write(launch_banner)
            except Exception:
                pass

            # Spawn Python script using absolute path to virtual environment
            try:
                python_exe = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
                if not os.path.exists(python_exe):
                    python_exe = sys.executable or "python"
                
                script_to_run = "lion_automate_v97.py"
                if not os.path.exists(os.path.join(BASE_DIR, script_to_run)):
                    script_to_run = "lion_automate.py"
                
                cmd = [python_exe, "-u", script_to_run, "--job-id", CURRENT_JOB_ID]
                if use_cache:
                    cmd.append("--use-cache")
                if layout_mode:
                    cmd.extend(["--layout", layout_mode])

                # Run script in background and redirect output to per-job log file
                log_fd = open(job_log_file, "a", encoding="utf-8", errors="ignore")
                RUNNING_PROCESS_START_TIME = time.time()
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
    allow_reuse_address = True

if __name__ == "__main__":
    # Ensure raw and finished folders exist
    os.makedirs(FINISHED_DIR, exist_ok=True)
    os.makedirs(RAW_DIR, exist_ok=True)
    
    server = ThreadedTCPServer(("", PORT), DashboardHandler)
    print(f"============================================================")
    print(f"  LionReel GUI Dashboard Server launched successfully! 🦁")
    print(f"  --> Open: http://localhost:{PORT} in your web browser")
    print(f"============================================================")
    
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

    threading.Thread(target=open_browser_delayed, args=(PORT,), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()
        server.server_close()
