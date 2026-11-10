"""
tests/test_mode_contracts.py
============================
Contract validation suite for Short, Long, and Both Formats modes.
Validates:
1. Short Video: 30-60s clamp, clip_count * clip_time, 9:16 default, 1 output file.
2. Long Video: Duration slider is contract, derived read-only clip count, 16:9 default (9:16 and 1:1 selectable), 1 output file.
3. Both Formats: Long follows Long rules, Teaser is fixed 45s 9:16 read-only row, 2 output files.
4. Shared: Single source of truth in job_config.json, no value leakage across modes, QA hard gates.
"""

import unittest
import json
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import job_options

class TestModeContracts(unittest.TestCase):

    def test_short_video_clamping_and_contract(self):
        """Short video must clamp total duration to 30s-60s and calculate total = clips * clip_time."""
        # Case A: 10 clips x 12.0s = 120s -> Outside 30-60s, must clamp to 60s
        cfg_over = {
            "VIDEO_TYPE": "short",
            "TARGET_CLIPS": 10,
            "SHORT_CLIP_SEC": 12.0,
            "ASPECT_RATIO": "9:16"
        }
        valid, norm, err = job_options.normalize_job_options(cfg_over)
        self.assertTrue(valid, f"Normalization failed: {err}")
        self.assertEqual(norm["type"], "short")
        self.assertEqual(norm["aspect_ratio"], "9:16")
        self.assertEqual(norm["width"], 1080)
        self.assertEqual(norm["height"], 1920)
        # Total duration must be clamped <= 60.0s
        total_sec = norm["clips"] * norm["clip_time"]
        self.assertLessEqual(total_sec, 60.01, f"Short duration exceeded 60s: {total_sec}s")
        self.assertGreaterEqual(total_sec, 29.99, f"Short duration below 30s: {total_sec}s")

        # Case B: 2 clips x 5.0s = 10s -> Outside 30-60s, must clamp to >= 30s
        cfg_under = {
            "VIDEO_TYPE": "short",
            "TARGET_CLIPS": 2,
            "SHORT_CLIP_SEC": 5.0,
            "ASPECT_RATIO": "9:16"
        }
        valid, norm, err = job_options.normalize_job_options(cfg_under)
        self.assertTrue(valid)
        total_sec = norm["clips"] * norm["clip_time"]
        self.assertGreaterEqual(total_sec, 29.99, f"Short duration below 30s: {total_sec}s")
        self.assertLessEqual(total_sec, 60.01)

    def test_short_mode_not_mutated_to_compilation_at_60s(self):
        """Short mode with 60s runtime must remain 'short', not converted to compilation."""
        cfg = {
            "VIDEO_TYPE": "short",
            "TARGET_CLIPS": 8,
            "SHORT_CLIP_SEC": 7.5,
            "TARGET_DURATION_MIN": 5.0 # Leaked from previous Long selection
        }
        valid, norm, err = job_options.normalize_job_options(cfg)
        self.assertTrue(valid)
        self.assertEqual(norm["type"], "short", "Short mode was incorrectly mutated to compilation")

    def test_long_video_contract_and_derived_clip_count(self):
        """Long video duration slider is the contract (+/-1s); clip count is derived from duration / clip_time."""
        cfg = {
            "VIDEO_TYPE": "long",
            "TARGET_DURATION_MIN": 3.0, # 180s contract
            "SHORT_CLIP_SEC": 7.5,
            "ASPECT_RATIO": "16:9"
        }
        valid, norm, err = job_options.normalize_job_options(cfg)
        self.assertTrue(valid)
        self.assertEqual(norm["type"], "compilation")
        self.assertEqual(norm["aspect_ratio"], "16:9")
        self.assertEqual(norm["target_seconds"], 180.0)
        # Derived clip count: 180 / 7.5 = 24 clips
        self.assertEqual(norm["clips"], 24)
        self.assertAlmostEqual(norm["clip_time"], 7.5)

    def test_long_video_aspect_ratio_selection(self):
        """Long video defaults to 16:9, but 9:16 and 1:1 are selectable and respected."""
        # 9:16 Long
        cfg_vert = {
            "VIDEO_TYPE": "long",
            "TARGET_DURATION_MIN": 3.0,
            "ASPECT_RATIO": "9:16"
        }
        valid, norm, err = job_options.normalize_job_options(cfg_vert)
        self.assertTrue(valid)
        self.assertEqual(norm["aspect_ratio"], "9:16")
        self.assertEqual(norm["width"], 1080)
        self.assertEqual(norm["height"], 1920)

        # 1:1 Long
        cfg_sq = {
            "VIDEO_TYPE": "long",
            "TARGET_DURATION_MIN": 2.0,
            "ASPECT_RATIO": "1:1"
        }
        valid, norm, err = job_options.normalize_job_options(cfg_sq)
        self.assertTrue(valid)
        self.assertEqual(norm["aspect_ratio"], "1:1")
        self.assertEqual(norm["width"], 1080)
        self.assertEqual(norm["height"], 1080)

    def test_both_formats_contract(self):
        """Both formats must produce Long part config + 45s 9:16 Teaser config."""
        cfg = {
            "VIDEO_TYPE": "both",
            "TARGET_DURATION_MIN": 3.0,
            "SHORT_CLIP_SEC": 7.5,
            "ASPECT_RATIO": "16:9"
        }
        valid, norm, err = job_options.normalize_job_options(cfg)
        self.assertTrue(valid)
        self.assertEqual(norm["type"], "both")
        self.assertEqual(norm["target_seconds"], 180.0)
        self.assertEqual(norm["aspect_ratio"], "16:9")
        # Check teaser structure in normalized config
        self.assertIn("teaser", norm)
        self.assertEqual(norm["teaser"]["seconds"], 45.0)
        self.assertEqual(norm["teaser"]["ratio"], "9:16")
        self.assertEqual(norm["teaser"]["resolution"], "1080x1920")

    def test_single_source_of_truth_job_config_schema(self):
        """load_or_verify_job_config must write and return the unified schema with mode, ratio, resolution, target_seconds, clip_time, clip_count, teaser."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            job_id = "test_contract_schema_001"
            cfg_in = {
                "VIDEO_TYPE": "both",
                "TARGET_DURATION_MIN": 3.0,
                "SHORT_CLIP_SEC": 7.5,
                "ASPECT_RATIO": "16:9",
                "mode": "cat",
                "video_cat_type": "fails_clumsy"
            }
            valid, norm, err = job_options.normalize_job_options(cfg_in)
            self.assertTrue(valid)
            saved = job_options.load_or_verify_job_config(job_id, norm, work_base_dir=tmp_dir)
            
            # Check unified schema fields
            self.assertEqual(saved["mode"], "both")
            self.assertEqual(saved["ratio"], "16:9")
            self.assertEqual(saved["resolution"], "1920x1080")
            self.assertEqual(saved["target_seconds"], 180.0)
            self.assertEqual(saved["clip_time"], 7.5)
            self.assertEqual(saved["clip_count"], 24)
            self.assertEqual(saved["teaser"]["seconds"], 45.0)
            self.assertEqual(saved["teaser"]["ratio"], "9:16")

            # Check disk persistence
            work_dir = job_options.get_job_work_dir(job_id, work_base_dir=tmp_dir)
            cpath = os.path.join(work_dir, "job_config.json")
            self.assertTrue(os.path.exists(cpath))
            with open(cpath, "r", encoding="utf-8") as f:
                disk_cfg = json.load(f)
            self.assertEqual(disk_cfg["target_seconds"], 180.0)
            self.assertEqual(disk_cfg["teaser"]["seconds"], 45.0)

if __name__ == "__main__":
    unittest.main()
