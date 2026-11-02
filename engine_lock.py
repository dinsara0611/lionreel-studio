"""
LIONREEL STUDIO — ENGINE LOCK
Enforces a single engine process per job and one global engine run at a time.
Prevents duplicate concurrent engine launches and manages lock lifecycle.
"""

import os
import sys
import json
import time
import ctypes

GLOBAL_LOCK_PATH = os.path.join("C:\\", "LionReel", "data", "global_engine.lock")

def is_pid_alive(pid: int) -> bool:
    """Checks if a process with given PID is currently alive on the system."""
    if pid is None or pid <= 0:
        return False
    if sys.platform == "win32":
        # Windows API OpenProcess check
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        SYNCHRONIZE = 0x00100000
        try:
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, int(pid))
            if handle != 0:
                # Process exists, check exit code
                exit_code = ctypes.c_ulong()
                ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                ctypes.windll.kernel32.CloseHandle(handle)
                # STILL_ACTIVE is 259
                return exit_code.value == 259
        except Exception:
            pass
        # Fallback to os.kill
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except (ProcessLookupError, OSError):
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except (ProcessLookupError, OSError):
            return False

def _read_lock_file(path: str) -> dict:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _write_lock_file(path: str, data: dict):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temp_path = path + f".tmp.{os.getpid()}"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    # Atomic replace
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
    os.replace(temp_path, path)

def get_global_lock_path(lock_dir: str = None) -> str:
    if lock_dir:
        return os.path.join(lock_dir, "global_engine.lock")
    return GLOBAL_LOCK_PATH

def get_job_lock_path(job_id: str, lock_dir: str = None, job_dir: str = None) -> str:
    if job_dir:
        return os.path.join(job_dir, "engine.lock")
    if lock_dir:
        return os.path.join(lock_dir, f"{job_id}.lock")
    return os.path.join("C:\\", "LionReel", "work", job_id, "engine.lock")

def acquire_engine_lock(job_id: str, pid: int = None, lock_dir: str = None, job_dir: str = None) -> tuple:
    """
    Acquires global engine lock and per-job lock.
    Returns (success: bool, message: str).
    """
    if pid is None:
        pid = os.getpid()

    now_epoch = time.time()
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    global_path = get_global_lock_path(lock_dir)
    job_path = get_job_lock_path(job_id, lock_dir=lock_dir, job_dir=job_dir)

    # 1. Check existing global lock
    existing_global = _read_lock_file(global_path)
    if existing_global:
        locked_pid = existing_global.get("pid")
        locked_job = existing_global.get("job_id")
        
        # If the locked process is the current process, allow re-entry
        if locked_pid == pid and locked_job == job_id:
            pass
        elif locked_pid and is_pid_alive(locked_pid):
            if locked_job == job_id:
                return False, f"Job {job_id} is already running (PID {locked_pid}). Second start refused."
            return False, f"An engine process is already running for job {locked_job} (PID {locked_pid}). Only one engine run is allowed at a time."
        else:
            # Stale lock: process is no longer running
            try:
                os.remove(global_path)
            except Exception:
                pass

    # 2. Check existing job lock
    existing_job = _read_lock_file(job_path)
    if existing_job:
        locked_pid = existing_job.get("pid")
        if locked_pid == pid:
            pass
        elif locked_pid and is_pid_alive(locked_pid):
            return False, f"Job {job_id} is already running (PID {locked_pid}). Second start refused."
        else:
            try:
                os.remove(job_path)
            except Exception:
                pass

    # 3. Write new locks
    lock_data = {
        "job_id": job_id,
        "pid": pid,
        "start_epoch": now_epoch,
        "start_time": now_str
    }

    try:
        _write_lock_file(global_path, lock_data)
        _write_lock_file(job_path, lock_data)
        return True, f"Engine lock acquired successfully for {job_id} (PID {pid})."
    except Exception as e:
        return False, f"Failed to acquire engine lock: {e}"

def release_engine_lock(job_id: str, pid: int = None, lock_dir: str = None, job_dir: str = None) -> bool:
    """
    Releases global engine lock and per-job lock.
    """
    global_path = get_global_lock_path(lock_dir)
    job_path = get_job_lock_path(job_id, lock_dir=lock_dir, job_dir=job_dir)

    # Global lock release if it belongs to this job
    existing_global = _read_lock_file(global_path)
    if existing_global and existing_global.get("job_id") == job_id:
        try:
            os.remove(global_path)
        except Exception:
            pass

    # Job lock release
    if os.path.exists(job_path):
        try:
            os.remove(job_path)
        except Exception:
            pass

    return True

def get_active_engine_lock(lock_dir: str = None) -> dict:
    """Returns details of currently active engine lock if alive, else None."""
    global_path = get_global_lock_path(lock_dir)
    lock_data = _read_lock_file(global_path)
    if not lock_data:
        return None
    pid = lock_data.get("pid")
    if pid and is_pid_alive(pid):
        return lock_data
    return None
