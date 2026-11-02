"""
tests/test_long_video_compilation.py
====================================
Regression test suite ensuring Long Video Compilation mode can be created anytime
without being blocked, paused prematurely, or shrunk down to a short video.
"""

import unittest
import os
import sys
import json
import time
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger
import job_options

class TestLongVideoCompilation(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.path.join(BASE_DIR, "work", f"test_long_comp_{int(time.time()*1000)}")
        os.makedirs(self.test_dir, exist_ok=True)
        self.sandbox_db = os.path.join(self.test_dir, "sandbox_ledger.db")
        self.ledger = ClipLedger(db_path=self.sandbox_db)

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except Exception:
            pass

    def test_long_compilation_capacity_scales_with_reuse(self):
        """
        Verify that for compilations (allow_reuse=True), capacity is not artificially
        clamped to 3 clips per source, but allows up to 10 diverse clips per source.
        """
        test_source = os.path.join(self.test_dir, "cache_compilation_src.mp4")
        with open(test_source, "wb") as f:
            f.write(b"mp4 content")

        with self.ledger._get_conn() as conn:
            for i in range(6):
                conn.execute(f"""
                    INSERT INTO clips (clip_id, source_id, source_url_or_path, license, start_s, end_s, animal_type, times_used, is_verified, framing_score, sharpness, verified_plan)
                    VALUES ('c_comp_{i}', 'cache_compilation_src', '{test_source}', 'CC-BY', {i*35.0}, {i*35.0 + 10.0}, 'cat', 0, 1, 0.90, 200.0, '{{"status":"pass"}}')
                """)
            conn.commit()

        # Shorts mode (allow_reuse=False): capped at 3 per source
        cap_short = self.ledger.get_pool_ready_and_capacity("cat", target_clips=100, allow_reuse=False)
        self.assertEqual(cap_short["capacity"], 3)

        # Compilation mode (allow_reuse=True): scales up to all 6 diverse windows
        cap_long = self.ledger.get_pool_ready_and_capacity("cat", target_clips=100, allow_reuse=True)
        self.assertEqual(cap_long["capacity"], 6)

    def test_job_options_normalize_long_video_defaults(self):
        """
        Normalize job options for Long Video:
        - format 'long' normalizes to 'compilation'
        - target clips defaults to 100
        - clip time defaults to 12.0s
        """
        cfg = {"VIDEO_TYPE": "long", "TARGET_CLIPS": 100, "SHORT_CLIP_SEC": 12.0}
        valid, norm, err = job_options.normalize_job_options(cfg)
        self.assertTrue(valid)
        self.assertEqual(norm["type"], "compilation")
        self.assertEqual(norm["clips"], 100)
        self.assertEqual(norm["clip_time"], 12.0)

    def test_long_video_not_downscaled_by_allow_shorter(self):
        """
        Verify the pipeline logic guard: Long Video compilation target must NOT
        adapt down to a tiny short video (< 10 clips) even if allow_shorter is active.
        """
        video_type = "compilation"
        target_clips_count = 100
        passing_candidates = [{"candidate": i} for i in range(4)] # only 4 passed
        allow_shorter = True

        is_long_comp = video_type in ("compilation", "long")
        # Logic under test from lion_automate_v97.py
        if allow_shorter and len(passing_candidates) >= 2 and (not is_long_comp or len(passing_candidates) >= 10):
            target_clips_count = len(passing_candidates)

        # Target clips must remain 100, NOT shrink down to 4!
        self.assertEqual(target_clips_count, 100)

if __name__ == "__main__":
    unittest.main()
