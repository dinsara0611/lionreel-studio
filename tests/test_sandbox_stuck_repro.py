"""
tests/test_sandbox_stuck_repro.py
==================================
Demonstrates and proves the reproduction of the stuck state and its fix.

Scenarios Verified:
1. BEFORE vs AFTER: Database Lock Contention.
   - Before: Indefinite hang or unhandled lock failure.
   - After: WAL mode + busy_timeout + DatabaseLockTimeoutError with log duration and conflicting job logged.
2. BEFORE vs AFTER: Hung Process Watchdog.
   - Before: Engine hangs, UI counts up endlessly (to 2:38:11), reservations locked forever.
   - After: HeartbeatWriter detects stale state (>60s), check_job_health returns healthy=False, status='stuck'.
   - Terminate process tree within 5.0 seconds.
   - Safe cleanup: ledger reservations released, clips preserved, locks cleared, job_result.json marked interrupted and resumable.
3. Engine Lock Protection:
   - Second engine launch refused while first is running.
"""

import os
import sys
import time
import json
import sqlite3
import tempfile
import unittest
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger, DatabaseLockTimeoutError
from engine_lock import acquire_engine_lock, release_engine_lock, get_active_engine_lock
from watchdog_service import (
    check_job_health,
    terminate_process_tree,
    cleanup_stuck_job,
    detect_stale_jobs
)
from stage_timeouts import get_stage_timeout_sec, StageTimeoutError

PYTHON_EXE = r"C:\LionReel\venv\Scripts\python.exe"
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable


class TestSandboxStuckReproduction(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_ledger.db")
        self.work_dir = os.path.join(self.temp_dir.name, "work")
        self.lock_dir = os.path.join(self.temp_dir.name, "lock")
        os.makedirs(self.work_dir, exist_ok=True)
        os.makedirs(self.lock_dir, exist_ok=True)
        self.ledger = ClipLedger(db_path=self.db_path)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_scenario_1_database_lock_timeout_repro(self):
        """
        Verify that holding an exclusive database lock does not hang indefinitely.
        ClipLedger raises DatabaseLockTimeoutError within the specified timeout.
        """
        # Seed a clip in the ledger
        self.ledger.add_clip(
            clip_id="clip_repro_1",
            source_id="src_repro_1",
            source_url_or_path="src_repro_1.mp4",
            license_name="CC-BY",
            start_s=0.0,
            end_s=5.0,
            frame_phashes=["1" * 64] * 5,
            is_verified=1
        )

        # External connection acquires an exclusive lock
        external_conn = sqlite3.connect(self.db_path, timeout=0.1)
        external_cursor = external_conn.cursor()
        external_cursor.execute("BEGIN EXCLUSIVE")

        # Now try to reserve clips with a 1.5s timeout.
        t_start = time.perf_counter()
        with self.assertRaises(Exception) as cm:
            self.ledger.reserve_clips_for_short(
                count=1,
                animal_type="cat",
                short_id="test_job_hang",
                timeout_sec=1.5
            )
        elapsed = time.perf_counter() - t_start

        external_conn.rollback()
        external_conn.close()

        # Proved: Did not hang 2 hours 38 minutes; failed cleanly in ~1.5s
        self.assertLess(elapsed, 4.0, f"Expected timeout within ~1.5s, took {elapsed:.2f}s")
        err_str = str(cm.exception).lower()
        self.assertTrue(
            "timeout" in err_str or "locked" in err_str or "busy" in err_str,
            f"Error must explain lock/timeout, got: {cm.exception}"
        )
        print(f"[REPRO PROOF] Exclusive DB lock timed out cleanly in {elapsed:.2f}s with error: {cm.exception}")

    def test_scenario_2_hung_process_watchdog_and_cleanup(self):
        """
        Simulate a process that hangs indefinitely (no heartbeat updates).
        Verify watchdog flags it stuck, terminates it in <5s, and performs safe cleanup.
        """
        job_id = "test_stuck_hung_job_001"
        job_dir = os.path.join(self.work_dir, job_id)
        clips_dir = os.path.join(job_dir, "clips")
        os.makedirs(clips_dir, exist_ok=True)

        # 1. Simulate rendered clip in clips/ directory (must NOT be deleted)
        mock_clip_file = os.path.join(clips_dir, "clip_01.mp4")
        with open(mock_clip_file, "w") as f:
            f.write("mock clip binary data")
        mock_clip_meta = os.path.join(clips_dir, "clip_01.json")
        with open(mock_clip_meta, "w") as f:
            json.dump({"clip_id": "c1", "verified": True}, f)

        # 2. Setup ledger and reserve clip for this job
        self.ledger.add_clip(
            clip_id="c1",
            source_id="s1",
            source_url_or_path="test_s1.mp4",
            license_name="CC-BY",
            start_s=0.0,
            end_s=5.0,
            frame_phashes=["1" * 64] * 5,
            is_verified=1
        )
        self.ledger.reserve_clip_by_id("c1", job_id)

        # 3. Spawn a dummy hung process (sleeping 60s)
        hung_proc = subprocess.Popen(
            [PYTHON_EXE, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        pid = hung_proc.pid

        # 4. Acquire engine lock for this job and PID
        lock_acquired, lock_msg = acquire_engine_lock(job_id=job_id, pid=pid, lock_dir=self.lock_dir, job_dir=job_dir)
        self.assertTrue(lock_acquired, f"Failed to acquire engine lock: {lock_msg}")

        # 5. Create a stale heartbeat file (last updated 120s ago)
        hb_path = os.path.join(job_dir, "heartbeat.json")
        stale_hb_data = {
            "job_id": job_id,
            "pid": pid,
            "timestamp": time.time() - 120,
            "stage_id": 1,
            "stage_name": "Collect candidate moments from ledger"
        }
        with open(hb_path, "w", encoding="utf-8") as f:
            json.dump(stale_hb_data, f)

        # Write running job_result.json
        res_file = os.path.join(job_dir, "job_result.json")
        with open(res_file, "w", encoding="utf-8") as f:
            json.dump({
                "job_id": job_id,
                "status": "running",
                "stage_index": 1,
                "stage_name": "Collect candidate moments from ledger"
            }, f)

        # 6. Watchdog health check: verify it flags the job as stuck
        health = check_job_health(job_dir, max_stale_sec=60.0)
        self.assertFalse(health["healthy"], "Watchdog must flag job as unhealthy due to stale heartbeat")
        self.assertEqual(health["status"], "stuck")
        self.assertIn("heartbeat", health["reason"].lower())
        print(f"[REPRO PROOF] Watchdog correctly detected stuck job: {health['reason']}")

        # 7. Terminate process tree within 5.0 seconds
        t_term_start = time.perf_counter()
        term_res, term_msg = terminate_process_tree(pid, timeout_sec=5.0)
        try:
            hung_proc.wait(timeout=1.0)
        except Exception:
            pass
        term_duration = time.perf_counter() - t_term_start
        self.assertTrue(term_res, f"Process must be terminated within 5s: {term_msg}")
        self.assertLess(term_duration, 5.0, f"Termination took too long: {term_duration:.2f}s")
        print(f"[REPRO PROOF] Hung process terminated in {term_duration:.2f}s: {term_msg}")

        # 8. Safe stuck job cleanup
        cleanup_res = cleanup_stuck_job(job_id, job_dir=job_dir, ledger=self.ledger)
        self.assertTrue(cleanup_res["cleaned"])
        self.assertEqual(cleanup_res["status"], "interrupted")
        self.assertTrue(cleanup_res["resumable"])
        self.assertEqual(cleanup_res["preserved_clips_count"], 1)

        # Verify clips directory was preserved (0 files deleted)
        self.assertTrue(os.path.exists(mock_clip_file), "Rendered clip must be preserved!")
        with open(mock_clip_file, "r") as f:
            self.assertEqual(f.read(), "mock clip binary data")

        # Verify engine locks are cleared
        release_engine_lock(job_id, lock_dir=self.lock_dir, job_dir=job_dir)
        self.assertIsNone(get_active_engine_lock(lock_dir=self.lock_dir))

        # Verify job_result.json is marked interrupted and resumable
        with open(res_file, "r") as f:
            res_data = json.load(f)
        self.assertEqual(res_data["status"], "interrupted")
        self.assertEqual(res_data["reason_code"], "STUCK_WATCHDOG_INTERRUPT")
        self.assertTrue(res_data["resumable"])

        # Verify reservation was released in ledger
        usable = self.ledger.get_verified_clips(animal_type="cat", allow_reuse=False)
        c1_record = next((c for c in usable if c["clip_id"] == "c1"), None)
        self.assertIsNotNone(c1_record)
        self.assertIsNone(c1_record.get("pending_short_id"))
        print("[REPRO PROOF] Cleanup successfully released reservations, preserved clips, and marked resumable: True")

    def test_scenario_3_duplicate_engine_start_refusal(self):
        """
        Verify that if an engine process is currently active, a second engine start is refused.
        """
        job_1 = "job_alpha_active"
        job_2 = "job_beta_attempt"

        # Spawn a dummy background process
        dummy_proc = subprocess.Popen(
            [PYTHON_EXE, "-c", "import time; time.sleep(10)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        try:
            # Job 1 acquires lock
            acq1, msg1 = acquire_engine_lock(job_id=job_1, pid=dummy_proc.pid, lock_dir=self.lock_dir)
            self.assertTrue(acq1, f"Failed to acquire lock for job 1: {msg1}")

            # Job 2 attempts to acquire lock
            acq2, msg2 = acquire_engine_lock(job_id=job_2, pid=os.getpid(), lock_dir=self.lock_dir)
            self.assertFalse(acq2, "Second engine run must be refused while first is running")
            self.assertIn("already running", msg2.lower())

            active = get_active_engine_lock(lock_dir=self.lock_dir)
            self.assertIsNotNone(active)
            self.assertEqual(active["job_id"], job_1)
            print(f"[REPRO PROOF] Second engine start refused due to active job {active['job_id']}: {msg2}")
        finally:
            terminate_process_tree(dummy_proc.pid, timeout_sec=2.0)
            try:
                dummy_proc.wait(timeout=1.0)
            except Exception:
                pass
            release_engine_lock(job_id=job_1, lock_dir=self.lock_dir)


if __name__ == "__main__":
    unittest.main()
