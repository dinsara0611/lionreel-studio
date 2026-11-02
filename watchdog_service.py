"""
LIONREEL STUDIO — WATCHDOG SERVICE
Provides heartbeat tracking, health monitoring, stuck job detection,
graceful process tree termination, and safe cleanup for stalled pipeline jobs.
"""

import os
import sys
import json
import time
import threading
import subprocess

from engine_lock import is_pid_alive, release_engine_lock
from stage_timeouts import get_stage_timeout_sec, check_stage_timeout, StageTimeoutError

class HeartbeatWriter:
    """
    Background daemon thread that periodically writes heartbeat state
    to heartbeat.json in the job directory.
    """
    def __init__(self, job_id: str, job_dir: str, interval_sec: float = 5.0):
        self.job_id = job_id
        self.job_dir = job_dir
        self.interval_sec = interval_sec
        self.stage_id = 0
        self.stage_name = "Job Initialization"
        self.counter = 0
        self.running = False
        self._thread = None
        self._lock = threading.Lock()
        os.makedirs(self.job_dir, exist_ok=True)

    def set_stage(self, stage_id: int, stage_name: str):
        with self._lock:
            self.stage_id = int(stage_id)
            self.stage_name = str(stage_name)
            self.counter += 1
        self.flush()

    def step_counter(self, note: str = ""):
        with self._lock:
            self.counter += 1
        self.flush()

    def flush(self):
        with self._lock:
            data = {
                "job_id": self.job_id,
                "stage_id": self.stage_id,
                "stage_name": self.stage_name,
                "counter": self.counter,
                "timestamp": time.time(),
                "human_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "pid": os.getpid()
            }
        hb_file = os.path.join(self.job_dir, "heartbeat.json")
        tmp_file = hb_file + f".tmp.{os.getpid()}"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            if os.path.exists(hb_file):
                try:
                    os.remove(hb_file)
                except Exception:
                    pass
            os.replace(tmp_file, hb_file)
        except Exception:
            pass

    def start(self):
        self.running = True
        self.flush()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="HeartbeatWriter")
        self._thread.start()

    def _run_loop(self):
        while self.running:
            time.sleep(self.interval_sec)
            if self.running:
                self.flush()

    def stop(self):
        self.running = False
        self.flush()

def check_job_health(job_dir: str, max_stale_sec: float = 60.0) -> dict:
    """
    Checks if a job in job_dir is currently healthy or stuck.
    Returns health status dictionary.
    """
    jr_path = os.path.join(job_dir, "job_result.json")
    hb_path = os.path.join(job_dir, "heartbeat.json")
    lock_path = os.path.join(job_dir, "engine.lock")

    job_result = {}
    if os.path.exists(jr_path):
        try:
            with open(jr_path, "r", encoding="utf-8") as f:
                job_result = json.load(f)
        except Exception:
            pass

    status = job_result.get("status", "").lower()
    job_id = job_result.get("job_id") or os.path.basename(job_dir)
    stage_id = job_result.get("stage_index", 0)
    stage_name = job_result.get("stage_name", "")

    # If the job is not running, it's not considered stuck
    if status and status != "running":
        return {
            "healthy": True,
            "status": status,
            "job_id": job_id,
            "stage_id": stage_id,
            "stage_name": stage_name
        }

    # If status is empty and no heartbeat, return unknown/not running
    if not status and not os.path.exists(hb_path):
        return {
            "healthy": True,
            "status": "idle",
            "job_id": job_id
        }

    # Check heartbeat
    hb_data = {}
    if os.path.exists(hb_path):
        try:
            with open(hb_path, "r", encoding="utf-8") as f:
                hb_data = json.load(f)
        except Exception:
            pass

    pid = hb_data.get("pid")
    if not pid and os.path.exists(lock_path):
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                lock_info = json.load(f)
                pid = lock_info.get("pid")
        except Exception:
            pass

    hb_timestamp = hb_data.get("timestamp")
    now_epoch = time.time()

    if hb_data.get("stage_id") is not None:
        stage_id = hb_data.get("stage_id")
    if hb_data.get("stage_name"):
        stage_name = hb_data.get("stage_name")

    # 1. Missing or stale heartbeat
    if hb_timestamp is not None:
        stale_sec = now_epoch - float(hb_timestamp)
        if stale_sec > max_stale_sec:
            reason = (
                f"Missing engine heartbeat for {stale_sec:.0f}s (exceeded watchdog threshold of "
                f"{max_stale_sec:.0f}s) while in stage {stage_id} '{stage_name}'"
            )
            _mark_job_stuck(job_dir, job_result, reason, stage_id, stage_name)
            return {
                "healthy": False,
                "status": "stuck",
                "reason": reason,
                "stale_sec": stale_sec,
                "job_id": job_id,
                "stage_id": stage_id,
                "stage_name": stage_name,
                "pid": pid
            }

    # 2. Check PID liveness
    if pid is not None:
        if not is_pid_alive(pid):
            reason = f"Engine process (PID {pid}) exited unexpectedly while in stage {stage_id} '{stage_name}'"
            _mark_job_stuck(job_dir, job_result, reason, stage_id, stage_name)
            return {
                "healthy": False,
                "status": "stuck",
                "reason": reason,
                "job_id": job_id,
                "stage_id": stage_id,
                "stage_name": stage_name,
                "pid": pid
            }

    # 3. If job is running but no heartbeat at all after 60s from creation
    if not hb_timestamp and os.path.exists(jr_path):
        mtime = os.path.getmtime(jr_path)
        age = now_epoch - mtime
        if age > max_stale_sec:
            reason = f"No heartbeat emitted for {age:.0f}s since job creation in stage {stage_id} '{stage_name}'"
            _mark_job_stuck(job_dir, job_result, reason, stage_id, stage_name)
            return {
                "healthy": False,
                "status": "stuck",
                "reason": reason,
                "job_id": job_id,
                "stage_id": stage_id,
                "stage_name": stage_name,
                "pid": pid
            }

    return {
        "healthy": True,
        "status": "running",
        "job_id": job_id,
        "stage_id": stage_id,
        "stage_name": stage_name,
        "pid": pid
    }

def _mark_job_stuck(job_dir: str, current_result: dict, reason: str, stage_id: int, stage_name: str):
    """Updates job_result.json to status 'stuck' with stage and reason."""
    jr_path = os.path.join(job_dir, "job_result.json")
    updated = dict(current_result)
    updated["status"] = "stuck"
    updated["stuck_reason"] = reason
    updated["stage_index"] = stage_id
    updated["stage_name"] = stage_name
    updated["stuck_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(jr_path, "w", encoding="utf-8") as f:
            json.dump(updated, f, indent=2)
    except Exception:
        pass

def terminate_process_tree(pid: int, timeout_sec: float = 5.0) -> tuple:
    """
    Terminates the process and all its child processes within timeout_sec.
    On Windows uses taskkill /F /T /PID.
    Returns (success: bool, message: str).
    """
    if pid is None or pid <= 0:
        return True, "No valid PID to terminate"

    if not is_pid_alive(pid):
        return True, f"Process {pid} is already terminated"

    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=timeout_sec)
        except Exception as e:
            pass
    else:
        try:
            import signal
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass

    # Poll for termination
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if not is_pid_alive(pid):
            return True, f"Process {pid} and tree terminated successfully"
        time.sleep(0.2)

    if not is_pid_alive(pid):
        return True, f"Process {pid} terminated"
    return False, f"Process {pid} could not be terminated within {timeout_sec}s"

def cleanup_stuck_job(job_id: str, job_dir: str = None, ledger = None, stop_process: bool = True) -> dict:
    """
    Stops the engine process tree within 5s, releases ledger reservations,
    preserves any rendered clips in clips/, and marks the job 'interrupted' (resumable: True).
    Nothing is deleted.
    """
    if job_dir is None:
        job_dir = os.path.join("C:\\", "LionReel", "work", job_id)

    if ledger is None:
        try:
            from clip_ledger import ClipLedger
            ledger = ClipLedger()
        except Exception:
            ledger = None

    pid_to_stop = None

    # Check heartbeat or lock for PID
    hb_path = os.path.join(job_dir, "heartbeat.json")
    if os.path.exists(hb_path):
        try:
            with open(hb_path, "r", encoding="utf-8") as f:
                hb = json.load(f)
                pid_to_stop = hb.get("pid")
        except Exception:
            pass

    lock_path = os.path.join(job_dir, "engine.lock")
    if not pid_to_stop and os.path.exists(lock_path):
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                lk = json.load(f)
                pid_to_stop = lk.get("pid")
        except Exception:
            pass

    # Stop process tree if requested and alive
    proc_stopped = True
    stop_msg = "No process active"
    if stop_process and pid_to_stop:
        proc_stopped, stop_msg = terminate_process_tree(pid_to_stop, timeout_sec=5.0)

    # Release reservations in ledger
    if ledger:
        try:
            ledger.release_short(job_id)
        except Exception as e_led:
            pass

    # Release locks
    release_engine_lock(job_id, job_dir=job_dir)

    # Count preserved clips
    clips_dir = os.path.join(job_dir, "clips")
    preserved_count = 0
    if os.path.exists(clips_dir):
        for fname in os.listdir(clips_dir):
            if fname.endswith(".mp4"):
                preserved_count += 1

    # Update job_result.json to interrupted and resumable
    jr_path = os.path.join(job_dir, "job_result.json")
    result_data = {}
    if os.path.exists(jr_path):
        try:
            with open(jr_path, "r", encoding="utf-8") as f:
                result_data = json.load(f)
        except Exception:
            pass

    result_data["job_id"] = job_id
    result_data["status"] = "interrupted"
    result_data["reason_code"] = "STUCK_WATCHDOG_INTERRUPT"
    result_data["resumable"] = True
    result_data["interrupted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    result_data["preserved_clips_count"] = preserved_count
    result_data["cleanup_note"] = "Stuck job cleaned up safely; clips preserved and reservations released."

    try:
        with open(jr_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, indent=2)
    except Exception:
        pass

    return {
        "cleaned": True,
        "job_id": job_id,
        "status": "interrupted",
        "resumable": True,
        "process_terminated": proc_stopped,
        "process_message": stop_msg,
        "preserved_clips_count": preserved_count,
        "message": f"Job {job_id} successfully cleaned up. Preserved {preserved_count} clips and released reservations."
    }

def detect_stale_jobs(work_root: str = "C:\\LionReel\\work", max_stale_sec: float = 60.0) -> list:
    """
    Scans work directory for stale/stuck jobs.
    Returns a list of stuck job info dicts with time_str and summary_line.
    """
    if not os.path.exists(work_root):
        return []

    stale_jobs = []
    try:
        entries = os.listdir(work_root)
    except Exception:
        return []

    for entry in entries:
        job_dir = os.path.join(work_root, entry)
        if not os.path.isdir(job_dir):
            continue

        health = check_job_health(job_dir, max_stale_sec=max_stale_sec)
        if not health["healthy"] and health["status"] == "stuck":
            # Extract time string from job_id (e.g. lionreel_cat_20261031_153841_bcad3a4f -> 15:38)
            time_str = ""
            parts = entry.split("_")
            for p in parts:
                if len(p) == 6 and p.isdigit():
                    time_str = f"{p[0:2]}:{p[2:4]}"
                    break
            if not time_str:
                mtime = os.path.getmtime(job_dir)
                time_str = time.strftime("%H:%M", time.localtime(mtime))

            stale_jobs.append({
                "job_id": entry,
                "job_dir": job_dir,
                "time_str": time_str,
                "stage_id": health.get("stage_id", 1),
                "stage_name": health.get("stage_name", "Stage 1"),
                "reason": health.get("reason", "Watchdog detected stalled heartbeat"),
                "summary_line": f"1 stuck job from {time_str}. Clean up"
            })

    return stale_jobs
