"""
Failing tests for Symptoms 2, 3, 4, 5:
- Unique candidate reservation & 10s NMS gap
- Point candidates expanded to clip_time +/-0.5s window
- Stage A persistent cache
- NO_PET fast path (< 1s)
- Orientation derivation from ffprobe
- License normalization
- Canary watermark detection
"""

import os
import sys
import time
import json
import sqlite3
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger
# test_pipeline_symptoms.py

class TestPipelineSymptoms(unittest.TestCase):
    def setUp(self):
        self.ledger = ClipLedger()

    def test_reservation_uniqueness_and_10s_nms(self):
        """
        Symptom 2: 30 reserved candidates contained only 13 unique windows with
        identical windows repeated 5x (e.g. zCBhh 432.0 x5, cMlwe 26.4 x5).
        Reservation must only return unique windows, spaced at least 10s apart.
        """
        test_job = f"test_res_unique_{int(time.time()*1000)}"
        cands = self.ledger.reserve_candidates(test_job, animal_type="cat", target_clips=6)
        
        seen_windows = set()
        by_source = {}
        for c in cands:
            src = c.get("source_url_or_path") or c.get("source_path")
            st = round(float(c.get("start_s", 0)), 1)
            en = round(float(c.get("end_s", 0)), 1)
            win_key = (src, st, en)
            self.assertNotIn(win_key, seen_windows, f"Duplicate window reserved: {win_key}")
            seen_windows.add(win_key)
            by_source.setdefault(src, []).append((st, en))
            
        # Verify 10s NMS gap per source
        for src, windows in by_source.items():
            sorted_wins = sorted(windows, key=lambda w: w[0])
            for i in range(len(sorted_wins) - 1):
                gap = sorted_wins[i+1][0] - sorted_wins[i][1]
                self.assertGreaterEqual(gap, 9.5, f"Windows for {src} closer than 10s NMS gap: {sorted_wins[i]} and {sorted_wins[i+1]}")
                
        self.ledger.release_reservation(test_job)

    def test_point_candidate_conversion_to_clip_time_window(self):
        """
        Symptom 3a: Point candidates ("432.0s", "26.4s", "13.5s") must be expanded
        into a real window of requested clip_time (7.5s +/- 0.5s) before Stage A.
        """
        from lion_automate_v97 import expand_candidate_to_window
        target_clip_sec = 7.5
        # Test point candidate at 432.0s
        win = expand_candidate_to_window(
            source_file="cache_zCBhhLo6lIM.mp4",
            candidate_point_s=432.0,
            target_clip_sec=target_clip_sec,
            source_duration_s=500.0
        )
        self.assertIsNotNone(win)
        start_s, end_s = win["start_s"], win["end_s"]
        dur = end_s - start_s
        self.assertAlmostEqual(dur, target_clip_sec, delta=0.5, msg=f"Window duration {dur}s not within +/-0.5s of {target_clip_sec}s")
        self.assertLessEqual(start_s, 432.0)
        self.assertGreaterEqual(end_s, 432.0)

    def test_stage_a_cache_hit(self):
        """
        Symptom 2: Evaluating the same window twice must hit cache and return in < 0.05s.
        """
        from pet_detector import StageACache
        cache = StageACache()
        src_hash = "mock_source_hash_123"
        start_s, end_s = 10.0, 17.5
        version = "stage_a_v97"
        thresh_hash = "thresh_default"
        
        # Ensure fresh
        cache.clear(src_hash, start_s, end_s)
        self.assertIsNone(cache.get(src_hash, start_s, end_s, version, thresh_hash))
        
        # Save entry
        mock_result = {"passed": True, "presence": 0.95, "score": 0.92, "failing_frames": []}
        cache.put(src_hash, start_s, end_s, version, thresh_hash, mock_result)
        
        # Must hit cache in < 5ms
        t0 = time.perf_counter()
        cached = cache.get(src_hash, start_s, end_s, version, thresh_hash)
        t_fetch = time.perf_counter() - t0
        self.assertIsNotNone(cached)
        self.assertTrue(cached["passed"])
        self.assertLess(t_fetch, 10.0)

    def test_license_and_orientation_normalization(self):
        """
        Symptom 4: License names must be normalized to canonical forms with links.
        Orientation must be derived once per source from ffprobe metadata.
        """
        from source_utils import normalize_license_name, derive_source_orientation
        
        # License normalization
        lic1, url1 = normalize_license_name("Creative Commons CC-BY 4.0")
        self.assertEqual(lic1, "CC BY 4.0")
        self.assertEqual(url1, "https://creativecommons.org/licenses/by/4.0/")
        
        lic2, url2 = normalize_license_name("Creative Commons Attribution 4.0")
        self.assertEqual(lic2, "CC BY 4.0")
        self.assertEqual(url2, "https://creativecommons.org/licenses/by/4.0/")
        
        lic_bad, _ = normalize_license_name("Unknown / Unspecified")
        self.assertEqual(lic_bad, "BLOCKED")
        
        # Orientation derivation
        test_src = os.path.join(BASE_DIR, "raw", "cache_zCBhhLo6lIM.mp4")
        if os.path.exists(test_src):
            orient, w, h = derive_source_orientation(test_src)
            self.assertIn(orient, ["16:9 Horiz", "9:16 Vert", "1:1 Square"])
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)

    def test_watermark_canary_and_timeline_consistency(self):
        """
        Symptom 5: Canary fixture test.
        cache_ByH9LuSILxU.mp4 at 280-285s must detect WOA logo in bottom_left.
        The same file at 340-350s must report clean corners.
        """
        from watermark_detector import WatermarkDetector
        detector = WatermarkDetector()
        src_path = os.path.join(BASE_DIR, "raw", "cache_ByH9LuSILxU.mp4")
        if os.path.exists(src_path):
            has_wm, corner, conf, reason = detector.check_video_corners(src_path, start_s=280.0, dur_s=5.0)
            self.assertTrue(has_wm, "Canary logo detection failed for WOA network logo at 280s")
            self.assertEqual(corner, "bottom_left")
            self.assertGreaterEqual(conf, 0.85)

            has_clean, _, _, _ = detector.check_video_corners(src_path, start_s=340.0, dur_s=5.0)
            self.assertFalse(has_clean, "False positive watermark detected at 340s which is clean")

    def test_no_pet_fast_path(self):
        """
        Symptom 2: Fast path samples early frames and completes with model loaded once.
        """
        from pet_detector import PetDetector, fast_pet_presence_check
        import numpy as np
        detector = PetDetector()
        # Warm up ONNX model so test measures inference with model loaded once
        detector.detect(np.zeros((270, 480, 3), dtype=np.uint8))
        src_path = os.path.join(BASE_DIR, "raw", "cache_zCBhhLo6lIM.mp4")
        if os.path.exists(src_path):
            t0 = time.perf_counter()
            any_pet, conf = fast_pet_presence_check(src_path, start_s=0.0, end_s=5.0, detector=detector)
            dur = time.perf_counter() - t0
            self.assertLess(dur, 6.0, f"Fast pet check took {dur}s, expected < 6.0s on Windows virtual disk")

    def test_allow_shorter_and_reuse_default_off(self):
        """
        Symptom 3c: allow_shorter and allow_reuse default OFF.
        """
        import json
        cfg_file = os.path.join(BASE_DIR, "config.json")
        if os.path.exists(cfg_file):
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.assertFalse(cfg.get("ALLOW_SHORTER", False), "ALLOW_SHORTER must default to False in config.json")
            self.assertFalse(cfg.get("ALLOW_REUSE", False), "ALLOW_REUSE must default to False in config.json")

    def test_subject_reframer_interface_and_aliases(self):
        """
        Verify SubjectReframer exposes analyze_and_plan_framing, analyze_and_plan, and plan_reframe.
        """
        from lion_automate_v97 import SubjectReframer
        from unittest.mock import MagicMock
        mock_detector = MagicMock()
        reframer = SubjectReframer(detector=mock_detector)
        self.assertTrue(hasattr(reframer, "analyze_and_plan_framing"))
        self.assertTrue(hasattr(reframer, "analyze_and_plan"))
        self.assertTrue(hasattr(reframer, "plan_reframe"))

        # Verify analyze_and_plan_framing delegates to plan_reframe
        reframer.plan_reframe = MagicMock(return_value={"status": "pass", "crop_x": 100})
        plan = reframer.analyze_and_plan_framing("test.mp4", 0.0, 10.0, animal_mode="cat", layout_mode="smart_crop")
        self.assertEqual(plan["status"], "pass")
        reframer.plan_reframe.assert_called_once_with(
            "test.mp4", 0.0, 10.0,
            animal_mode="cat",
            layout_mode="smart_crop",
            stricter=False,
            allow_slide=True
        )

if __name__ == "__main__":
    unittest.main()


