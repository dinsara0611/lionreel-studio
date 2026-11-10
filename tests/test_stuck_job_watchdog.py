import unittest
import os
import sys
import json
import time
import tempfile
import sqlite3
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import clip_ledger
from clip_ledger import ClipLedger

class TestStuckJobWatchdog(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="lionreel_test_stuck_")
        self.db_path = os.path.join(self.test_dir, "test_clip_ledger.db")
        self.ledger = ClipLedger(db_path=self.db_path)

    def tearDown(self):
        import shutil
        try:
            shutil.rmtree(self.test_dir)
        except Exception:
            pass

    def test_01_ledger_call_timeout_fails_with_reason(self):
        """
        Task 2: When SQLite is locked by another transaction, ledger operations
        must not hang indefinitely. They must use busy_timeout and if exceeded,
        raise an informative DatabaseLockTimeoutError with the blocking detail.
        """
        # Hold an exclusive lock on the database using a separate connection
        lock_conn = sqlite3.connect(self.db_path, timeout=0.1)
        lock_conn.execute("BEGIN EXCLUSIVE")

        try:
            start_t = time.time()
            # Attempting an operation on our ledger instance with a small timeout (e.g. 1.0s)
            with self.assertRaises(Exception) as ctx:
                self.ledger.reserve_clips_for_short(
                    count=4,
                    animal_type="cat",
                    short_id="test_lock_job",
                    timeout_sec=1.5
                )
            dur = time.time() - start_t
            self.assertLess(dur, 4.0, "Locked ledger call must timeout quickly, never hang indefinitely")
            err_msg = str(ctx.exception)
            self.assertTrue(
                "locked" in err_msg.lower() or "timeout" in err_msg.lower() or "busy" in err_msg.lower(),
                f"Error must explain database lock/timeout, got: {err_msg}"
            )
        finally:
            lock_conn.rollback()
            lock_conn.close()

    def test_02_watchdog_detects_missing_heartbeat_after_60s(self):
        """
        Task 3: If an engine job's heartbeat is older than 60s, the watchdog must
        mark the job as 'stuck' with the exact stage and reason, and release reservations.
        """
        from watchdog_service import check_job_health
        job_dir = os.path.join(self.test_dir, "stuck_job_test")
        os.makedirs(job_dir, exist_ok=True)

        # Write a stale heartbeat (timestamp 75 seconds in the past)
        hb_file = os.path.join(job_dir, "heartbeat.json")
        with open(hb_file, "w", encoding="utf-8") as f:
            json.dump({
                "job_id": "stuck_job_test",
                "stage_id": 1,
                "stage_name": "Collect candidate moments from ledger",
                "timestamp": time.time() - 75.0,
                "pid": 999999
            }, f)

        # Write running job_result
        jr_file = os.path.join(job_dir, "job_result.json")
        with open(jr_file, "w", encoding="utf-8") as f:
            json.dump({
                "job_id": "stuck_job_test",
                "status": "running",
                "stage_index": 1,
                "stage_name": "Collect candidate moments from ledger"
            }, f)

        health = check_job_health(job_dir, max_stale_sec=60.0)
        self.assertFalse(health["healthy"], "Job with stale heartbeat (>60s) must be flagged unhealthy")
        self.assertEqual(health["status"], "stuck")
        self.assertIn("heartbeat", health["reason"].lower())

    def test_03_second_engine_start_refused(self):
        """
        Task 4: A second start of an engine job while another is active must be refused
        immediately with a clear, plain message and no duplicate execution.
        """
        from engine_lock import acquire_engine_lock, release_engine_lock
        lock_dir = os.path.join(self.test_dir, "engine_lock_test")
        os.makedirs(lock_dir, exist_ok=True)

        # First acquisition succeeds
        acq1, msg1 = acquire_engine_lock("job_alpha", lock_dir=lock_dir)
        self.assertTrue(acq1, "First engine lock acquisition must succeed")

        try:
            # Second acquisition for another job or same job fails
            acq2, msg2 = acquire_engine_lock("job_beta", lock_dir=lock_dir)
            self.assertFalse(acq2, "Second engine acquisition must be refused")
            self.assertIn("already running", msg2.lower())
        finally:
            release_engine_lock("job_alpha", lock_dir=lock_dir)

    def test_04_stale_job_cleanup_keeps_rendered_clips_and_releases_reservations(self):
        """
        Task 4: Stale job cleanup marks the job interrupted/resumable, releases ledger
        reservations, but retains any already rendered clips in clips/.
        """
        from watchdog_service import cleanup_stuck_job
        job_dir = os.path.join(self.test_dir, "cleanup_test_job")
        os.makedirs(os.path.join(job_dir, "clips"), exist_ok=True)

        # Add a dummy rendered clip
        with open(os.path.join(job_dir, "clips", "clip_1.mp4"), "w") as f:
            f.write("dummy_video_bytes")
        with open(os.path.join(job_dir, "clips", "clip_1.json"), "w") as f:
            json.dump({"clip_id": "c1", "verified": True}, f)

        # Write running state
        with open(os.path.join(job_dir, "job_result.json"), "w") as f:
            json.dump({"job_id": "cleanup_test_job", "status": "running"}, f)

        # Reserve clip in ledger
        self.ledger.add_clip(
            clip_id="c1",
            source_id="s1",
            source_url_or_path="test_s1.mp4",
            license_name="CC-BY",
            start_s=0.0,
            end_s=5.0,
            frame_phashes=["1"*64]*5,
            is_verified=1
        )
        self.ledger.reserve_clip_by_id("c1", "cleanup_test_job")

        # Run cleanup
        res = cleanup_stuck_job("cleanup_test_job", job_dir=job_dir, ledger=self.ledger)
        self.assertTrue(res["cleaned"])
        self.assertEqual(res["status"], "interrupted")
        self.assertTrue(res["resumable"])
        self.assertEqual(res["preserved_clips_count"], 1)

        # Verify reservation was released in ledger
        usable = self.ledger.get_verified_clips(animal_type="cat", allow_reuse=False)
        c1_record = next((c for c in usable if c["clip_id"] == "c1"), None)
        self.assertIsNotNone(c1_record)
        self.assertIsNone(c1_record.get("pending_short_id"))

    def test_05_stage_max_timeout_enforced(self):
        """
        Task 2: Every stage has a defined maximum execution timeout based on earlier job measurements.
        If a stage exceeds its timeout, it terminates with STAGE_TIMEOUT and the exact call.
        """
        from stage_timeouts import get_stage_timeout_sec, check_stage_timeout
        # Stage 1 max timeout is configured
        t1 = get_stage_timeout_sec(stage_id=1, video_type="short")
        self.assertGreaterEqual(t1, 30.0)
        self.assertLessEqual(t1, 300.0)

        # Test timeout detection
        is_exceeded, reason = check_stage_timeout(stage_id=1, elapsed_sec=350.0, video_type="short")
        self.assertTrue(is_exceeded)
    def test_06_stop_ends_process_tree_within_5s(self):
        """
        Task 5: Stop command must end the engine process tree within 5 s,
        release reservations, and report status.
        """
        from watchdog_service import terminate_process_tree
        # Spawn a dummy long-running python process
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        pid = proc.pid
        self.assertTrue(proc.poll() is None, "Subprocess must be initially running")

        start_t = time.time()
        success, msg = terminate_process_tree(pid, timeout_sec=5.0)
        dur = time.time() - start_t

        self.assertTrue(success, f"Process tree termination must succeed: {msg}")
        self.assertLess(dur, 5.0, "Process tree termination must complete within 5 seconds")

    def test_07_subprocess_timeout_raises_clear_error(self):
        """
        Task 2: Subprocess timeout helper raises SubprocessTimeoutError with exact call,
        timeout duration, and stage details.
        """
        from stage_timeouts import run_subprocess_with_timeout, SubprocessTimeoutError
        cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
        with self.assertRaises(SubprocessTimeoutError) as ctx:
            run_subprocess_with_timeout(cmd, timeout_sec=0.5, stage_name="Collect candidate moments from ledger", waited_for="candidate clip extraction")
        err = str(ctx.exception)
        self.assertIn("Collect candidate moments from ledger", err)
        self.assertIn("0.5", err)
        self.assertIn("candidate clip extraction", err)

    def test_08_detect_stale_jobs_returns_summary(self):
        """
        Task 4: On app start, detect leftover processes and stale jobs (no heartbeat),
        and show them in one line ('1 stuck job from HH:MM. Clean up').
        """
        from watchdog_service import detect_stale_jobs
        work_dir = os.path.join(self.test_dir, "work_test")
        job_dir = os.path.join(work_dir, "lionreel_cat_20261031_153841_bcad3a4f")
        os.makedirs(job_dir, exist_ok=True)

        with open(os.path.join(job_dir, "heartbeat.json"), "w") as f:
            json.dump({
                "job_id": "lionreel_cat_20261031_153841_bcad3a4f",
                "stage_id": 1,
                "stage_name": "Collect candidate moments from ledger",
                "timestamp": time.time() - 120.0,
                "pid": 999999
            }, f)

        with open(os.path.join(job_dir, "job_result.json"), "w") as f:
            json.dump({
                "job_id": "lionreel_cat_20261031_153841_bcad3a4f",
                "status": "running",
                "stage_index": 1,
                "stage_name": "Collect candidate moments from ledger"
            }, f)

        stuck_list = detect_stale_jobs(work_root=work_dir, max_stale_sec=60.0)
        self.assertEqual(len(stuck_list), 1)
        self.assertEqual(stuck_list[0]["time_str"], "15:38")
        self.assertEqual(stuck_list[0]["summary_line"], "1 stuck job from 15:38. Clean up")

if __name__ == "__main__":
    unittest.main()
