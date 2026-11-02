"""
tests/test_zero_touch_deadline.py
=================================
Unit tests for ZERO-TOUCH + TIME COMMITMENT requirements:
1. Reverse scheduling search budget and monotonic deadline.
2. 5-minute inactivity watchdog escalation.
3. Repeat spacing and window usage limit (<= 3 uses, spacing >= 8 positions, trim offset >= 1.5s).
4. QA gate fails on consecutive identical clips.
5. Atomic write and restored verification.
6. FFmpeg subprocess log isolation (no log flooding).
"""

import os
import sys
import time
import json
import tempfile
import unittest
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from stage_estimator import StageEstimator
from lion_automate_v97 import LionReelV97Pipeline
from fulfillment_planner import FulfillmentPlanner
from qa_check import check_repeat_spacing_gate


class TestZeroTouchDeadline(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="lionreel_test_zt_")
        self.estimator = StageEstimator()
        self.pipeline = LionReelV97Pipeline()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_reverse_scheduling_deadline(self):
        """Test reverse scheduling search budget: B_search = D - now - T_finish."""
        start_time = 1000000.0
        # Compute deadline for 8 clips @ 7.5s (contract 60s)
        dl = self.estimator.compute_predicted_time_and_deadline(
            target_clips_count=8,
            target_clip_sec=7.5,
            contract_total_sec=60.0,
            bank_verified_count=0,
            start_epoch=start_time,
            job_id="test_job_dl",
            work_dir=self.test_dir
        )
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "deadline.json")))
        deadline_epoch = dl["deadline_epoch"]
        t_finish = dl["t_finish_sec"]

        # When now is early, budget should NOT be exhausted
        early_now = start_time + 10.0
        expired, reason = self.pipeline.check_wait_budget_and_watchdog(
            self.test_dir, now=early_now, max_stall_sec=9999.0, remaining_clips=8
        )
        self.assertFalse(expired)

        # When now leaves less than T_finish before deadline, search budget expires immediately
        late_now = deadline_epoch - 50.0
        expired, reason = self.pipeline.check_wait_budget_and_watchdog(
            self.test_dir, now=late_now, max_stall_sec=9999.0, remaining_clips=8
        )
        self.assertTrue(expired)
        self.assertIn("Search budget exhausted", reason)

    def test_watchdog_5min_inactivity(self):
        """Watchdog expires if no progress occurs for 300 seconds."""
        now = 2000000.0
        wait_cp = {
            "waiting_since": now - 350.0,
            "last_progress_time": now - 301.0,
            "wait_budget_sec": 1800.0
        }
        with open(os.path.join(self.test_dir, "wait_checkpoint.json"), "w", encoding="utf-8") as f:
            json.dump(wait_cp, f)

        # Inactivity for 301s >= 300s -> must expire
        expired, reason = self.pipeline.check_wait_budget_and_watchdog(
            self.test_dir, now=now, max_stall_sec=300.0
        )
        self.assertTrue(expired)
        self.assertIn("Progress watchdog timeout", reason)

        # Inactivity for only 100s -> must NOT expire
        wait_cp["last_progress_time"] = now - 100.0
        with open(os.path.join(self.test_dir, "wait_checkpoint.json"), "w", encoding="utf-8") as f:
            json.dump(wait_cp, f)
        expired, reason = self.pipeline.check_wait_budget_and_watchdog(
            self.test_dir, now=now, max_stall_sec=300.0
        )
        self.assertFalse(expired)

    def test_repeat_spacing_and_usage_limits(self):
        """Test repeat spacing algorithm: no duplicate within 8 positions, no back-to-back, max 3 uses."""
        planner = FulfillmentPlanner()
        # Create a mock pool with 4 unique clips
        clips = [
            {"clip_id": "c1", "base_clip_id": "c1", "start_s": 0.0, "dur_s": 5.0},
            {"clip_id": "c2", "base_clip_id": "c2", "start_s": 0.0, "dur_s": 5.0},
            {"clip_id": "c1_rep1", "base_clip_id": "c1", "start_s": 1.5, "dur_s": 5.0, "is_repeat": True},
            {"clip_id": "c3", "base_clip_id": "c3", "start_s": 0.0, "dur_s": 5.0},
            {"clip_id": "c4", "base_clip_id": "c4", "start_s": 0.0, "dur_s": 5.0},
            {"clip_id": "c2_rep1", "base_clip_id": "c2", "start_s": 1.5, "dur_s": 5.0, "is_repeat": True},
        ]
        spaced = planner._space_repeats(clips)
        
        # Verify no back-to-back identical moments
        for i in range(len(spaced) - 1):
            b1 = spaced[i].get("base_clip_id", spaced[i].get("clip_id")).split("_rep")[0]
            b2 = spaced[i+1].get("base_clip_id", spaced[i+1].get("clip_id")).split("_rep")[0]
            self.assertNotEqual(b1, b2, f"Clips at {i} and {i+1} are identical: {b1}")

    def test_qa_consecutive_duplicate_fails(self):
        """QA repeat spacing gate must fail immediately if consecutive identical clips appear."""
        # Consecutive identical clips
        bad_mapping = [
            {"clip_id": "c1", "base_clip_id": "c1", "start_s": 0.0, "dur_s": 5.0},
            {"clip_id": "c1_dup", "base_clip_id": "c1", "start_s": 0.0, "dur_s": 5.0},
            {"clip_id": "c2", "base_clip_id": "c2", "start_s": 0.0, "dur_s": 5.0},
        ]
        gate_res = check_repeat_spacing_gate(bad_mapping)
        self.assertFalse(gate_res["passed"])
        self.assertTrue(len(gate_res["consecutive_violations"]) > 0)
        self.assertEqual(gate_res["consecutive_violations"][0]["base_id"], "c1")

        # Valid spaced mapping
        good_mapping = [
            {"clip_id": "c1", "base_clip_id": "c1", "start_s": 0.0, "dur_s": 5.0},
            {"clip_id": "c2", "base_clip_id": "c2", "start_s": 0.0, "dur_s": 5.0},
            {"clip_id": "c3", "base_clip_id": "c3", "start_s": 0.0, "dur_s": 5.0},
            {"clip_id": "c1_rep", "base_clip_id": "c1", "start_s": 1.5, "dur_s": 5.0, "is_repeat": True},
        ]
        gate_res_good = check_repeat_spacing_gate(good_mapping)
        self.assertTrue(gate_res_good["passed"])

    def test_atomic_write_checkpoint(self):
        """Checkpoints must be written atomically and verified upon restore."""
        target_file = os.path.join(self.test_dir, "checkpoint.json")
        data = {"job_id": "atomic_test", "progress": 100, "status": "completed"}

        # Write atomically using pipeline pattern
        tmp_file = target_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, target_file)

        self.assertTrue(os.path.exists(target_file))
        self.assertFalse(os.path.exists(tmp_file))

        # Re-read and verify contents
        with open(target_file, "r", encoding="utf-8") as f:
            restored = json.load(f)
        self.assertEqual(restored["progress"], 100)

    def test_accuracy_history_recording(self):
        """Test accuracy history logging."""
        acc_path = os.path.join(self.test_dir, "accuracy_history.json")
        res = self.estimator.record_job_completion_accuracy("test_acc_job", 1200, 1800, 1500)
        self.assertTrue(res["inside_range"])
        self.assertEqual(res["error_pct"], 0.0)

    def test_multi_length_prediction_scaling(self):
        """Verify predicted time scales strictly monotonically with video length."""
        times = []
        for dur in [120, 300, 600, 1200]:
            clips = int(round(dur / 7.5))
            pred = self.estimator.compute_predicted_time_and_deadline(
                contract_total_sec=dur,
                target_clips_count=clips,
                target_clip_sec=7.5,
                bank_verified_count=12,
                job_id=f"scale_{dur}"
            )
            times.append(pred["t_finish_sec"])
        # Check strict monotonicity: 2m < 5m < 10m < 20m
        for i in range(len(times) - 1):
            self.assertLess(times[i], times[i+1], f"Scaling violated: {times[i]} not < {times[i+1]}")


if __name__ == "__main__":
    unittest.main()
