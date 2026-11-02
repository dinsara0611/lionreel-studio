"""
tests/test_report_fix_contract.py
==================================
Contract test suite for Production Report (PDF + HTML Viewer) overhaul.
Validates:
1. Gate crash -> NOT RUN, overall verdict CANNOT be PASSED.
2. Centering 6/16 frames -> 37.5% and FAILS the 85% gate (passed/sampled math).
3. Sharpness -> Any clip at 130.8 fails floor 150.0 (every clip, not median alone).
4. Duration -> 1191.9s vs 1200.0s (-8.1s) FAILS contract (+/- 1.0s).
5. Window with use9 (> 8) -> FAILED, names offending clips.
6. Clip count mismatch -> Planned 160 vs Delivered 73 displays red mismatch line.
7. Repeat share -> Computed from clip table (3 unique of 73 = 95.89% repeat).
8. Tags -> Whole words, never iterated single characters.
9. Consistency checker -> Scans report text for conflicting values.
10. Unified verdict logic -> PASSED, PASSED WITH WARNINGS, FAILED, NOT RUN.
"""

import os
import sys
import json
import unittest
import tempfile
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import report_generator
import qa_check


class TestReportFixContract(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="lionreel_test_report_fix_")

    def tearDown(self):
        import shutil
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_gate_crash_not_run(self):
        """A gate that crashes, is skipped or has no data must be NOT RUN and cannot be PASSED."""
        # Check qa_report or verdict engine with a crashed/skipped gate
        fake_qa = {
            "passed": True,
            "overall_status": "PASSED",
            "gates": {
                "Gate 1": {"passed": True, "status": "PASS"},
                "Gate 6b": {"passed": True, "status": "PASS", "skipped": True, "error": "Check skipped: analyze_frame_text_and_borders() got an unexpected keyword argument 'is_master_with_captions'"}
            }
        }
        verdict = report_generator.calculate_unified_verdict(fake_qa, clips_table=[])
        self.assertNotEqual(verdict["badge"], "PASSED", "Crashed or skipped gate must NOT result in PASSED")
        self.assertEqual(verdict["badge"], "NOT RUN", "Crashed gate must produce NOT RUN verdict")

    def test_centering_math_fraction(self):
        """Centering percent must equal passed_frames / sampled_frames (6/16 = 37.5%, failing 85% gate)."""
        centering_res = {
            "passed_frames": 6,
            "sampled_frames": 16,
            "detected_frames": 7
        }
        # Math verification
        pct = (centering_res["passed_frames"] / float(centering_res["sampled_frames"])) * 100.0
        self.assertAlmostEqual(pct, 37.5, delta=0.1)

        # In report generator formatting
        formatted_str = report_generator.format_centering_metric(centering_res)
        self.assertIn("37.5%", formatted_str)
        self.assertIn("6/16", formatted_str)
        self.assertNotIn("85.7%", formatted_str)

    def test_sharpness_floor_clip_failure(self):
        """Gate 9 Sharpness: floor is 150.0 for every clip. If any clip is 130.8, it must FAIL."""
        clip_sharpness_values = [613.7, 450.2, 130.8, 520.1]
        gate_res = qa_check.evaluate_sharpness_floor(clip_sharpness_values, floor=150.0)
        self.assertFalse(gate_res["passed"], "Clip with 130.8 sharpness must fail 150.0 floor")
        self.assertEqual(gate_res["min_sharpness"], 130.8)

    def test_duration_contract_plus_minus_one_second(self):
        """Gate 1B: Exact Duration contract is +/- 1.0s. 1191.9s vs 1200.0s (-8.1s) must FAIL."""
        target_s = 1200.0
        actual_s = 1191.9
        gate_eval = qa_check.evaluate_duration_contract(actual_s, target_s)
        self.assertFalse(gate_eval["passed"], "Duration diff of 8.1s must fail +/- 1.0s contract")
        self.assertAlmostEqual(gate_eval["diff"], 8.1, delta=0.05)
        self.assertEqual(gate_eval["allowed_tolerance"], 1.0)

    def test_use9_window_fails(self):
        """A window used 9 times (> 8) must trigger overall FAILED and name the offending clips."""
        clips_table = []
        for i in range(12):
            clips_table.append({
                "clip_id": f"clip_{i:03d}",
                "source_id": "src_cat_01",
                "start_s": 10.0,
                "end_s": 25.0,
                "use_count": 9 if i < 9 else 1
            })
        verdict = report_generator.calculate_unified_verdict({"passed": True, "gates": {}}, clips_table=clips_table)
        self.assertEqual(verdict["badge"], "FAILED", "Windows used > 8 times must FAIL the job")
        self.assertTrue(any("clip_" in err and "used 9 times" in err for err in verdict["critical_errors"]))

    def test_clip_count_mismatch_display(self):
        """Planned 160 clips vs delivered 73 must show a mismatch warning/error in report."""
        job_config = {"requested_clips": 160}
        planner_decision = {"planned_clips": 72}
        mapping = {"clips": [{"clip_id": f"c_{i}"} for i in range(73)]}

        mismatch_info = report_generator.get_clip_count_reconciliation(job_config, planner_decision, mapping)
        self.assertTrue(mismatch_info["has_mismatch"])
        self.assertEqual(mismatch_info["delivered_clips"], 73)
        self.assertEqual(mismatch_info["planned_clips"], 72)
        self.assertEqual(mismatch_info["target_clips"], 160)
        self.assertIn("mismatch", mismatch_info["display_status"].lower())

    def test_repeat_share_computed_from_clip_table(self):
        """Repeat share must be computed from the clip table (e.g. 3 unique windows out of 73 = 95.89% repeat)."""
        clips = []
        # 3 unique windows repeated across 73 slots
        for i in range(73):
            win_idx = i % 3
            clips.append({
                "clip_id": f"clip_{i:03d}",
                "source_id": f"src_{win_idx}",
                "start_s": float(win_idx * 15.0),
                "end_s": float((win_idx + 1) * 15.0)
            })
        stats = report_generator.calculate_clip_diversity_stats(clips)
        self.assertEqual(stats["unique_windows"], 3)
        self.assertEqual(stats["total_clips"], 73)
        self.assertAlmostEqual(stats["repeat_share_pct"], 95.89, delta=0.1)

    def test_tags_are_list_of_whole_words(self):
        """Tags in metadata must be parsed as whole words, never iterated character by character."""
        raw_metadata = {
            "tags": "catoftheyear, funnycat, kittens, viral"
        }
        parsed_tags = report_generator.format_tags_list(raw_metadata["tags"])
        self.assertEqual(parsed_tags, ["catoftheyear", "funnycat", "kittens", "viral"])
        self.assertNotIn("c", parsed_tags)
        self.assertNotIn("a", parsed_tags)

    def test_consistency_checker(self):
        """Consistency checker scans generated report text and asserts no two contradictory metrics exist."""
        report_text = (
            "Delivered Length: 1191.9s\n"
            "Clip Count: 73 Clips\n"
            "Repeat Share: 95.9%\n"
            "Duration Contract: Actual 1191.9s vs Target 1200.0s (Diff -8.1s)\n"
            "Resolution: 1920x1080 (16:9)\n"
        )
        inconsistencies = report_generator.check_report_internal_consistency(report_text, {
            "delivered_duration_s": 1191.9,
            "clip_count": 73,
            "repeat_share_pct": 95.9,
            "resolution": "1920x1080",
            "aspect_ratio": "16:9"
        })
        self.assertEqual(len(inconsistencies), 0, f"Found inconsistencies: {inconsistencies}")

        # Injected contradictory text
        bad_text = report_text + "\nTotal Clips in Table: 160 clips"
        bad_check = report_generator.check_report_internal_consistency(bad_text, {
            "delivered_duration_s": 1191.9,
            "clip_count": 73,
            "repeat_share_pct": 95.9,
            "resolution": "1920x1080",
            "aspect_ratio": "16:9"
        })
        self.assertGreater(len(bad_check), 0, "Contradictory clip counts must be detected")


if __name__ == "__main__":
    unittest.main()
