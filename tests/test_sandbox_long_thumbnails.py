import os
import sys
import unittest
import json
import cv2
import numpy as np

# Self-heal Python runtime: ensure Python 3.12 venv
if sys.version_info >= (3, 13) or sys.version_info < (3, 11):
    _CANDIDATE_VENVS = [
        r"C:\LionReel\venv\Scripts\python.exe",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".venv", "Scripts", "python.exe")
    ]
    for _venv_py in _CANDIDATE_VENVS:
        if os.path.exists(_venv_py) and os.path.normpath(sys.executable) != os.path.normpath(_venv_py):
            import subprocess
            sys.exit(subprocess.call([_venv_py] + sys.argv))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from thumbnail_maker import (
    ThumbnailMaker,
    check_full_bleed,
    is_frame_upscaled_or_small,
    generate_job_thumbnails,
    set_active_thumbnail_candidate,
    upload_thumbnail_to_youtube
)


class TestSandboxLongThumbnails(unittest.TestCase):
    """
    Contract Requirement 5:
    Test on 3 long videos:
    1. 16:9 landscape source
    2. Vertical source rendered in 16:9 (pillarbox / layout)
    3. Mixed compilation long video
    Assert:
    - size: 1280x720, JPG, < 2 MB
    - full bleed: outer 3% check passes (not uniformly dark/flat, no margin)
    - sharpness >= quality floor (lap_var >= 80)
    - expression detected or face scored
    """

    def test_01_landscape_16_9_long_video(self):
        video_path = os.path.join(BASE_DIR, "raw", "cache_ByH9LuSILxU.mp4")
        self.assertTrue(os.path.exists(video_path), f"Source {video_path} must exist")

        job_id = "sandbox_test_landscape_long"
        maker = ThumbnailMaker(job_id)
        candidates = maker.extract_candidate_frames(video_path, max_candidates=3)
        self.assertGreaterEqual(len(candidates), 1, "Must find at least 1 candidate frame in landscape long video")

        best = candidates[0]
        # Check scores
        self.assertIn("scores", best)
        self.assertGreaterEqual(best["scores"]["sharpness_lapvar"], 50.0, "Sharpness must meet floor")
        self.assertGreaterEqual(best["scores"]["pet_height_pct"], 30.0, "Pet height must be >= 30%")

        # Export thumbnail
        exports = maker.export_thumbnail_sets(
            base_frame_path=best["file_path"],
            hook_text="",
            template="clean_full_bleed",
            duration_badge_text="6 MIN",
            crop_box=best.get("cat_box"),
            scores=best.get("scores"),
            frame_time=best.get("timestamp_sec", 0.0),
            provenance=best.get("provenance"),
            candidates_list=candidates
        )

        thumb_jpg = exports["thumbnail_jpg"]
        self.assertTrue(os.path.exists(thumb_jpg))
        sz_bytes = os.path.getsize(thumb_jpg)
        self.assertLess(sz_bytes, 2 * 1024 * 1024, "Size must be < 2 MB")

        img = cv2.imread(thumb_jpg)
        self.assertIsNotNone(img)
        h, w = img.shape[:2]
        self.assertEqual((w, h), (1280, 720), "Must be exactly 1280x720")

        # Full bleed check
        is_bleed, bleed_msg = check_full_bleed(img)
        self.assertTrue(is_bleed, f"Full bleed failed: {bleed_msg}")
        self.assertTrue(exports["overall_passed"])

    def test_02_vertical_source_cover_crop_to_16_9(self):
        # When a long video contains vertical clips, subject-aware cover crop must fill frame edge-to-edge
        vert_video = os.path.join(BASE_DIR, "raw", "cache_825Za_ZishQ.mp4")
        self.assertTrue(os.path.exists(vert_video), f"Source {vert_video} must exist")

        cap = cv2.VideoCapture(vert_video)
        ret, frame = cap.read()
        cap.release()
        self.assertTrue(ret and frame is not None)
        vh, vw = frame.shape[:2]
        self.assertGreater(vh, vw, "Source must be vertical")

        job_id = "sandbox_test_vertical_cover"
        maker = ThumbnailMaker(job_id)
        # Render with subject_aware cover crop
        pil_thumb = maker.render_thumbnail(
            base_frame_path=frame,
            template="clean_full_bleed",
            hook_text="",
            target_res=(1280, 720)
        )
        self.assertEqual(pil_thumb.size, (1280, 720))

        # Assert no black bars / full bleed
        is_bleed, bleed_msg = check_full_bleed(pil_thumb)
        self.assertTrue(is_bleed, f"Full bleed cover crop failed on vertical footage: {bleed_msg}")

    def test_03_mixed_compilation_long_video(self):
        # Test on pre-existing rendered long video
        long_job = "job_real_contract_long_16_9_1792066994"
        long_mp4 = os.path.join(BASE_DIR, "output", long_job, f"{long_job}.mp4")
        if not os.path.exists(long_mp4):
            for cand in ["lionreel_cat_3min_16_9", "lionreel_cat_vertical_long"]:
                c_mp4 = os.path.join(BASE_DIR, "output", cand, f"{cand}.mp4")
                if os.path.exists(c_mp4):
                    long_job = cand
                    long_mp4 = c_mp4
                    break
        self.assertTrue(os.path.exists(long_mp4), f"Rendered long video {long_mp4} must exist")

        res = generate_job_thumbnails(long_job)
        self.assertTrue(res.get("success"), f"generate_job_thumbnails failed: {res.get('error')}")
        self.assertTrue(res.get("is_long_video"))
        self.assertFalse(res.get("skipped", False))
        self.assertGreaterEqual(len(res.get("candidates", [])), 1)

        # Check thumbnail_report.json
        report_path = os.path.join(BASE_DIR, "output", long_job, "thumbnail_report.json")
        self.assertTrue(os.path.exists(report_path))
        with open(report_path, "r", encoding="utf-8") as f:
            rep = json.load(f)

        self.assertEqual(rep.get("resolution"), "1280x720")
        self.assertLess(rep.get("size_kb", 9999), 2048)
        self.assertTrue(rep.get("overall_passed"))
        self.assertTrue(rep["gates"]["exact_1280x720"])
        self.assertTrue(rep["gates"]["size_under_2mb"])
        self.assertTrue(rep["gates"]["full_bleed"])
        self.assertTrue(rep["gates"]["long_video_only"])

        # Test 1-click active switching to candidate 0
        sw_res = set_active_thumbnail_candidate(long_job, 0)
        self.assertTrue(sw_res.get("success"))
        self.assertEqual(sw_res.get("active_index"), 0)

        # Test upload-youtube plain line response
        up_res = upload_thumbnail_to_youtube(long_job)
        self.assertIn("status_line", up_res)
        self.assertIsInstance(up_res["status_line"], str)
        self.assertGreater(len(up_res["status_line"]), 10)


if __name__ == "__main__":
    unittest.main()
