"""
test_stage_timer_exclusive_and_shares.py
=========================================
Unit tests for true timing math and monotonic stage timer:
1. Exact user numbers: Stage A wall 38.0s with nested tracking 36.68s gives parent exclusive 1.32s, never 5.66s.
2. Every table row is exclusive time (parent row never includes children).
3. The rows sum EXACTLY to the subtotal (within rounding tolerance, sum of exclusive times = subtotal).
4. Shares are calculated against wall clock and sum to exactly 100.0% with the explicit unaccounted row.
5. Fails if shares exceed 100%.
"""

import os
import sys
import unittest
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from stage_timer import StageTimer

class TestStageTimerExclusiveAndShares(unittest.TestCase):

    def test_user_exact_numbers_parent_exclusive(self):
        """
        User's exact scenario:
        Stage A wall 38.0s with nested tracking 36.68s must give parent exclusive 1.32s.
        Rows must sum exactly to subtotal.
        Shares must not exceed 100%.
        """
        timer = StageTimer("test_user_exact")
        # Mock stages data directly to test calculation and table formatting
        timer._perf_start = 1000.0
        timer._perf_end = 1040.0 # 40.0s total wall time
        timer._wall_start_epoch = 1700000000.0
        timer._wall_end_epoch = 1700000040.0
        timer._is_finished = True

        # Parent: stage_a (wall duration 38.0s, child tracking 36.68s)
        # Child: tracking (duration 36.68s)
        timer.stages = {
            "stage_a": {
                "duration_sec": 38.0,
                "exclusive_sec": 1.32, # 38.0 - 36.68
                "start_epoch": timer._wall_start_epoch + 1.0,
                "end_epoch": timer._wall_start_epoch + 39.0,
                "count": 1,
                "parent": None,
                "orig_perf": 1001.0
            },
            "tracking": {
                "duration_sec": 36.68,
                "exclusive_sec": 36.68,
                "start_epoch": timer._wall_start_epoch + 2.0,
                "end_epoch": timer._wall_start_epoch + 38.68,
                "count": 1,
                "parent": "stage_a",
                "orig_perf": 1002.0
            }
        }

        summary = timer.get_summary()
        self.assertAlmostEqual(summary["stages"]["stage_a"]["exclusive_sec"], 1.32, places=2)
        self.assertAlmostEqual(summary["stages"]["tracking"]["exclusive_sec"], 36.68, places=2)

        # Subtotal must be exactly 1.32 + 36.68 = 38.0s
        self.assertAlmostEqual(summary["sum_stages_sec"], 38.0, places=2)

        # Unaccounted must be 40.0 - 38.0 = 2.0s
        self.assertAlmostEqual(summary["unaccounted_sec"], 2.0, places=2)

        # Table check: rows displayed in table must sum to subtotal
        table_text = timer.format_table()
        lines = table_text.splitlines()

        # Parse table lines
        row_durations = []
        row_shares = []
        in_body = False
        subtotal_val = None
        unaccounted_val = None
        subtotal_share = None
        unaccounted_share = None

        for line in lines:
            if "STAGE" in line and "TIME (s)" in line:
                in_body = True
                continue
            if in_body and line.startswith("---"):
                continue
            if in_body and "SUBTOTAL" in line:
                parts = [p.strip() for p in line.split("|")]
                subtotal_val = float(parts[1])
                subtotal_share = float(parts[3].replace("%", ""))
                continue
            if in_body and "UNACCOUNTED" in line:
                parts = [p.strip() for p in line.split("|")]
                unaccounted_val = float(parts[1])
                unaccounted_share = float(parts[3].replace("%", ""))
                continue
            if in_body and "TOTAL WALL CLOCK" in line:
                in_body = False
                continue
            if in_body and "|" in line:
                parts = [p.strip() for p in line.split("|")]
                dur = float(parts[1])
                share = float(parts[3].replace("%", ""))
                row_durations.append(dur)
                row_shares.append(share)

        # 1. Rows sum must equal subtotal exactly
        rows_sum = sum(row_durations)
        self.assertAlmostEqual(rows_sum, subtotal_val, places=2,
            msg=f"Rows sum {rows_sum}s does not match subtotal {subtotal_val}s")

        # 2. Shares sum must equal subtotal share
        shares_sum = sum(row_shares)
        self.assertAlmostEqual(shares_sum, subtotal_share, places=1,
            msg=f"Shares sum {shares_sum}% does not match subtotal share {subtotal_share}%")

        # 3. Total shares (subtotal + unaccounted) must be exactly 100.0%
        total_share = subtotal_share + unaccounted_share
        self.assertAlmostEqual(total_share, 100.0, places=1,
            msg=f"Total shares {total_share}% exceeds or does not equal 100.0%")
        self.assertLessEqual(total_share, 100.05, "Total shares must NEVER exceed 100%")

    def test_nested_stages_live_execution(self):
        """
        Verify live start_stage/stop_stage nested calls correctly deduct child duration from parent exclusive time.
        """
        timer = StageTimer("test_live_nesting")
        timer.start_stage("parent_stage")
        time.sleep(0.05) # Parent slice 1: ~50ms
        timer.start_stage("child_stage")
        time.sleep(0.08) # Child slice: ~80ms
        timer.stop_stage("child_stage")
        time.sleep(0.03) # Parent slice 2: ~30ms
        timer.stop_stage("parent_stage")
        timer.finish_job()

        summary = timer.get_summary()
        parent_dur = summary["stages"]["parent_stage"]["duration_sec"]
        parent_excl = summary["stages"]["parent_stage"]["exclusive_sec"]
        child_dur = summary["stages"]["child_stage"]["duration_sec"]
        child_excl = summary["stages"]["child_stage"]["exclusive_sec"]

        # Parent total duration must be approx 0.05 + 0.08 + 0.03 = ~0.16s
        self.assertGreater(parent_dur, 0.14)
        # Child total duration must be approx 0.08s
        self.assertGreater(child_dur, 0.07)
        # Parent exclusive duration must be approx 0.05 + 0.03 = ~0.08s (never including child 0.08s)
        self.assertAlmostEqual(parent_excl, parent_dur - child_dur, delta=0.015)

        # Sum of exclusive times must equal sum_stages_sec (within 1 ms rounding)
        self.assertAlmostEqual(summary["sum_stages_sec"], parent_excl + child_excl, delta=0.002)

if __name__ == "__main__":
    unittest.main()
