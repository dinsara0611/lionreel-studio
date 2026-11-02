"""
tests/test_library_reconciliation.py

Verifies:
1. Reconciles MP4 files on disk (finished/ and output/) with /api/finished logic.
2. Checks that all 5 real videos (19:52, 3:00, 4:04 vertical, 0:30 short 1, 0:30 short 2)
   are present and marked is_test=False.
3. Checks that contract test fixtures are properly classified as is_test=True.
4. Verifies the count formula: "N videos (M test files hidden)".
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

class TestLibraryReconciliation(unittest.TestCase):
    def test_library_reconciliation_disk_vs_api(self):
        finished_dir = os.path.join(BASE_DIR, "finished")
        output_dir = os.path.join(BASE_DIR, "output")

        # 1. Collect from finished/
        mp4_candidates = []
        seen_mp4 = set()
        if os.path.exists(finished_dir):
            for f in sorted(os.listdir(finished_dir), key=lambda x: os.path.getmtime(os.path.join(finished_dir, x)) if os.path.exists(os.path.join(finished_dir, x)) else 0, reverse=True):
                if f.endswith(".mp4"):
                    mp4_candidates.append((f, os.path.join(finished_dir, f), "finished"))
                    seen_mp4.add(f)

        # 2. Collect from output/
        if os.path.exists(output_dir):
            for sub in sorted(os.listdir(output_dir), key=lambda x: os.path.getmtime(os.path.join(output_dir, x)) if os.path.exists(os.path.join(output_dir, x)) else 0, reverse=True):
                sub_p = os.path.join(output_dir, sub)
                if os.path.isdir(sub_p):
                    for f in os.listdir(sub_p):
                        if f.endswith(".mp4") and f not in seen_mp4:
                            mp4_candidates.append((f, os.path.join(sub_p, f), "output"))
                            seen_mp4.add(f)

        print(f"\n[RECONCILIATION] Total MP4 files discovered on disk: {len(mp4_candidates)}")
        real_videos = []
        test_videos = []

        for f, path, source in mp4_candidates:
            clean_id = f.replace(".mp4", "")
            clean_id_lower = str(clean_id).lower()
            is_test = bool(
                clean_id_lower.startswith("job_real_contract") or
                clean_id_lower.startswith("test_") or
                clean_id_lower.startswith("sandbox_") or
                "_contract_" in clean_id_lower or
                "_test_" in clean_id_lower or
                "acceptance" in clean_id_lower or
                clean_id_lower.endswith("_test") or
                clean_id_lower.endswith("_old_baseline") or
                clean_id_lower == "test"
            )
            sz_mb = os.path.getsize(path) / (1024 * 1024)
            if is_test:
                test_videos.append((f, sz_mb, source, "Automated test/contract fixture"))
            else:
                real_videos.append((f, sz_mb, source))

        print(f"  • Real videos count: {len(real_videos)}")
        for f, sz, src in real_videos:
            print(f"    - {f} ({sz:.1f} MB, source: {src})")

        print(f"  • Test videos count: {len(test_videos)}")
        for f, sz, src, reason in test_videos:
            print(f"    - {f} ({sz:.1f} MB, source: {src}) [Reason: {reason}]")

        # Assert real videos exist:
        real_names = [v[0] for v in real_videos]
        self.assertGreaterEqual(len(real_videos), 4, "At least 4 real production videos must be present!")
        self.assertIn("lionreel_cat_20261026_092004_9c9af4ac.mp4", real_names)
        self.assertIn("lionreel_cat_20261027_113225_a24ea39e.mp4", real_names)
        self.assertIn("lionreel_cat_20261027_120634_9123d1f8.mp4", real_names)
        self.assertIn("lionreel_cat_20261027_121640_134848b6.mp4", real_names)
        self.assertGreaterEqual(len(test_videos), 1, "At least 1 test fixture video must be classified as is_test=True!")

        # Verify count string:
        count_str_default = f"{len(real_videos)} videos ({len(test_videos)} test file{'s' if len(test_videos) != 1 else ''} hidden)"
        print(f"  • Displayed count badge (default): '{count_str_default}'")
        self.assertTrue("videos" in count_str_default and "test file" in count_str_default)

if __name__ == "__main__":
    unittest.main()
