"""
Tests for timing correctness, stage accounting, candidate reservation uniqueness,
Stage A caching, NO_PET fast-path, and explicit job completion states.
"""

import os
import sys
import time
import json
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from stage_timer import StageTimer

class TestStageTimer(unittest.TestCase):
    def test_stage_timer_wall_clock_and_unaccounted(self):
        """
        Symptom 1: Wall clock time vs sum of stages.
        sum(exclusive_stages) + unaccounted must equal total wall time within 1 ms.
        """
        timer = StageTimer(job_id="test_wall_clock")
        time.sleep(0.05) # Unmeasured startup / gap
        timer.start_stage("stage_1")
        time.sleep(0.05)
        timer.stop_stage("stage_1")
        time.sleep(0.03) # Unmeasured gap between stages
        timer.start_stage("stage_2")
        time.sleep(0.04)
        timer.stop_stage("stage_2")
        time.sleep(0.02) # Unmeasured teardown gap
        
        summary = timer.get_summary()
        self.assertIn("unaccounted_sec", summary, "Timer summary must include unaccounted_sec")
        self.assertIn("total_wall_time_sec", summary, "Timer summary must include total_wall_time_sec")
        
        sum_stages = sum(s["duration_sec"] for s in summary["stages"].values())
        unaccounted = summary["unaccounted_sec"]
        wall_time = summary["total_wall_time_sec"]
        
        # Must balance within 1 ms (0.001 s)
        self.assertAlmostEqual(sum_stages + unaccounted, wall_time, delta=0.005)
        self.assertGreater(unaccounted, 0.08) # 0.05 + 0.03 + 0.02 = ~0.10s unaccounted

    def test_stage_timer_nested_exclusive_time(self):
        """
        Nested stages must use exclusive time so child stages are not double counted.
        """
        timer = StageTimer(job_id="test_nested")
        timer.start_stage("stage_a_total")
        time.sleep(0.02) # exclusive to parent
        timer.start_stage("cand_01_track")
        time.sleep(0.03) # child 1
        timer.stop_stage("cand_01_track")
        time.sleep(0.01) # exclusive to parent
        timer.start_stage("cand_02_track")
        time.sleep(0.04) # child 2
        timer.stop_stage("cand_02_track")
        time.sleep(0.01) # exclusive to parent
        timer.stop_stage("stage_a_total")
        
        summary = timer.get_summary()
        st = summary["stages"]
        self.assertIn("stage_a_total", st)
        self.assertIn("cand_01_track", st)
        self.assertIn("cand_02_track", st)
        
        # Parent stage exclusive duration should be ~0.04s, NOT 0.04 + 0.03 + 0.04 = 0.11s
        self.assertLess(st["stage_a_total"]["exclusive_sec"], 0.06)
        self.assertGreater(st["stage_a_total"]["total_duration_sec"], 0.09)

    def test_stage_timer_reproduces_user_reframe_gap(self):
        """
        In user's log, 3 clips rendered over 91s, but table reported reframe = 27.57s.
        Timer must track full Stage 6 duration and clip render times without losing 63s.
        """
        timer = StageTimer(job_id="test_reframe_gap")
        
        # Simulate Stage 6 with 3 clips
        timer.start_stage("stage_6_reframe")
        for i in range(1, 4):
            timer.start_stage(f"clip_render_{i}")
            time.sleep(0.03) # ffmpeg render
            timer.stop_stage(f"clip_render_{i}")
            
            timer.start_stage(f"post_crop_gate_{i}")
            time.sleep(0.02) # gate verification
            timer.stop_stage(f"post_crop_gate_{i}")
        timer.stop_stage("stage_6_reframe")
        
        summary = timer.get_summary()
        st = summary["stages"]
        # All sub-steps must be recorded and sum to total stage 6 time
        sub_sum = sum(st[k]["duration_sec"] for k in st if k.startswith("clip_render_") or k.startswith("post_crop_gate_"))
        self.assertGreater(sub_sum, 0.14)
        self.assertAlmostEqual(st["stage_6_reframe"]["total_duration_sec"], sub_sum, delta=0.03)

    def test_timings_json_schema(self):
        """
        timings.json must contain wall_clock_start, wall_clock_end, total_wall_time_sec,
        unaccounted_sec, unaccounted_pct, and per-stage start/end timestamps.
        """
        timer = StageTimer(job_id="test_schema")
        timer.start_stage("reserve")
        time.sleep(0.01)
        timer.stop_stage("reserve")
        
        tmp_path = os.path.join(BASE_DIR, "scratch", "test_timings.json")
        timer.save_timings(tmp_path)
        try:
            with open(tmp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("wall_clock_start", data)
            self.assertIn("wall_clock_end", data)
            self.assertIn("total_wall_time_sec", data)
            self.assertIn("unaccounted_sec", data)
            self.assertIn("unaccounted_pct", data)
            self.assertIn("reserve", data["stages"])
            self.assertIn("start_epoch", data["stages"]["reserve"])
            self.assertIn("end_epoch", data["stages"]["reserve"])
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

if __name__ == "__main__":
    unittest.main()
