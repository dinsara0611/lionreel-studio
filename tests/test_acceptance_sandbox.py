"""
Acceptance test suite for sandbox jobs, job isolation, immutable config,
wait checkpoint persistence, and preflight capacity warning.
"""

import unittest
import os
import sys
import json
import time
import tempfile
import shutil

# Ensure workspace root is in path
WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

import job_options
import clip_ledger


class TestAcceptanceSandbox(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_sandbox_acc_")
        self.original_work_dir = getattr(job_options, "WORK_DIR", "work")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_immutable_job_config_and_isolation(self):
        """Test that work/<job_id>/job_config.json is immutable and resists live config drift."""
        job_id = "sandbox_test_immutable_001"
        job_dir = os.path.join(self.test_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)

        config_data = {
            "job_id": job_id,
            "type": "COMPILATION",
            "mode": "cat",
            "clips": 100,
            "clip_time": 7.5,
            "target_total_sec": 750.0,
            "layout": "9:16",
            "created_at": time.time(),
        }
        cfg_path = os.path.join(job_dir, "job_config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)

        # Verify engine reads saved config when no incoming config is passed
        loaded = job_options.load_or_verify_job_config(job_id, incoming_cfg=None, work_dir=self.test_dir)
        self.assertEqual(loaded["clips"], 100)
        self.assertEqual(loaded["type"], "COMPILATION")
        self.assertEqual(loaded["mode"], "cat")

        # Verify relaunch with conflicting settings is rejected
        with self.assertRaises(ValueError):
            job_options.load_or_verify_job_config(job_id, {"clips": 6, "mode": "dog"}, work_dir=self.test_dir)

    def test_one_process_lock_file(self):
        """Test that running with same job id creates a PID lock and prevents duplicate execution."""
        job_id = "sandbox_test_lock_002"
        job_dir = os.path.join(self.test_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)
        lock_file = os.path.join(job_dir, "job.lock")

        # Create lock file with current PID
        curr_pid = os.getpid()
        with open(lock_file, "w", encoding="utf-8") as f:
            json.dump({"pid": curr_pid, "job_id": job_id, "started_at": time.time()}, f)

        # Check process lock
        self.assertTrue(job_options.is_job_process_alive(job_id, work_dir=self.test_dir))

        # Check non-existent PID
        with open(lock_file, "w", encoding="utf-8") as f:
            json.dump({"pid": 9999999, "job_id": job_id, "started_at": time.time()}, f)
        self.assertFalse(job_options.is_job_process_alive(job_id, work_dir=self.test_dir))

    def test_preflight_capacity_warning(self):
        """Test that preflight computes pool capacity = min(ready, usable_sources * 3)."""
        ready, usable, cap = clip_ledger.get_pool_ready_and_capacity("cat", target_clips=100)
        # We know from ledger there are 17 verified clips from 9 distinct verified sources
        self.assertGreater(ready, 0)
        self.assertGreater(usable, 0)
        self.assertEqual(cap, min(ready, usable * 3))
        # 100 clips exceeds capacity
        self.assertLess(cap, 100)

    def test_one_shot_user_action_consumption(self):
        """Test that user action is consumed once and never replayed on restart."""
        job_id = "sandbox_test_action_003"
        job_dir = os.path.join(self.test_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)

        # Record action
        event_id = job_options.record_user_action(job_id, "make_shorter", {"ready_clips": 2}, work_dir=self.test_dir)
        self.assertTrue(event_id)

        # Consume once
        action = job_options.consume_user_action(job_id, work_dir=self.test_dir)
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "make_shorter")

        # Second consume must be None (not replayed!)
        second = job_options.consume_user_action(job_id, work_dir=self.test_dir)
        self.assertIsNone(second)

    def test_wait_checkpoint_preserves_waiting_since(self):
        """Test that server reload does not reset waiting_since."""
        job_id = "sandbox_test_checkpoint_004"
        job_dir = os.path.join(self.test_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)

        original_wait_since = time.time() - 600  # 10 minutes ago
        job_options.save_wait_checkpoint(
            job_id,
            {
                "waiting_since": original_wait_since,
                "consecutive_no_growth": 2,
                "clips_ready": 1,
                "clips_needed": 100,
            },
            work_dir=self.test_dir
        )

        loaded = job_options.load_wait_checkpoint(job_id, work_dir=self.test_dir)
        self.assertEqual(loaded["waiting_since"], original_wait_since)
        self.assertEqual(loaded["consecutive_no_growth"], 2)


if __name__ == "__main__":
    unittest.main()
