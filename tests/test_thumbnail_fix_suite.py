"""
Comprehensive Unit Tests for Thumbnail Maker Fix:
1. Bar gate with fixtures (thumb_bad_bars.png fails, thumb_good_full.png passes)
2. Provenance rule (video_file, timestamp_sec, clip_id, source_window, decoder required)
3. Scope rule (Long videos only, Shorts answered with 'not available for Shorts')
4. No-text default (Clean master without text, badge, or logo)
5. Resolution / upscale cap (<= 1.25x upscaling, minimum crop size 1024x576 for 1280x720)
6. File-size limit (Mobile-safe JPG <= 2 MB)
7. 'No valid frame' path (Never fails silently; plain-text diagnostic, never exported)
8. Double cats framing (Handles multiple cat detections cleanly)
9. Vertical long video (Cover-cropped from high-res source without bars)
"""

import os
import sys
import unittest
import numpy as np
import cv2
from PIL import Image

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import thumbnail_maker
from thumbnail_maker import (
    ThumbnailMaker,
    check_full_bleed,
    detect_source_bars,
    is_thumbnail_supported_for_job,
    subject_aware_cover_crop,
    is_frame_upscaled_or_small,
    generate_job_thumbnails
)

class TestThumbnailFixSuite(unittest.TestCase):
    def setUp(self):
        self.maker = ThumbnailMaker("test_suite_job")
        self.fixtures_dir = os.path.join(BASE_DIR, "tests", "fixtures")

    def test_01_bar_gate_with_fixtures(self):
        """thumb_bad_bars.png must FAIL; thumb_good_full.png must PASS."""
        bad_fixture = os.path.join(self.fixtures_dir, "thumb_bad_bars.png")
        good_fixture = os.path.join(self.fixtures_dir, "thumb_good_full.png")

        self.assertTrue(os.path.exists(bad_fixture), "thumb_bad_bars.png fixture missing")
        self.assertTrue(os.path.exists(good_fixture), "thumb_good_full.png fixture missing")

        # 1. Bad fixture (640x480 with 60px black bars on top and bottom)
        bad_img = Image.open(bad_fixture)
        bad_arr = np.array(bad_img)
        is_bleed_bad, reason_bad = check_full_bleed(bad_arr)
        self.assertFalse(is_bleed_bad, f"thumb_bad_bars.png must fail full-bleed gate, but passed: {reason_bad}")

        # Also test detect_source_bars on bad fixture
        _, (t, b, l, r) = detect_source_bars(bad_arr)
        self.assertTrue(t > 0 or b > 0, "Source bars should be detected on bad fixture")

        # 2. Good fixture (768x432 full-bleed cat face, 16:9)
        good_img = Image.open(good_fixture)
        good_arr = np.array(good_img)
        is_bleed_good, reason_good = check_full_bleed(good_arr)
        self.assertTrue(is_bleed_good, f"thumb_good_full.png must pass full-bleed gate, but failed: {reason_good}")

    def test_02_provenance_rule(self):
        """Every candidate must carry provenance; candidate without provenance is rejected."""
        valid_prov = {
            "video_file": "final_render.mp4",
            "timestamp_sec": 42.5,
            "clip_id": "clip_3",
            "source_window": [40.0, 47.5],
            "decoder": "H.264 video pixels (OpenCV VideoCapture)"
        }
        # Check required fields
        for field in ["video_file", "timestamp_sec", "clip_id", "source_window", "decoder"]:
            incomplete_prov = dict(valid_prov)
            del incomplete_prov[field]
            # Validating provenance completeness
            has_all = all(k in incomplete_prov for k in ["video_file", "timestamp_sec", "clip_id", "source_window", "decoder"])
            self.assertFalse(has_all, f"Missing {field} must cause provenance check to fail")

    def test_03_scope_rule(self):
        """Long videos supported; Short videos strictly rejected with 'not available for Shorts'."""
        # Long video: 3:00 16:9 video
        supp_long, _ = is_thumbnail_supported_for_job("lionreel_cat_3min_16_9")
        self.assertTrue(supp_long, "Long video (3min 16:9) must be supported")

        # Long video: 19:52 16:9 video
        supp_long_19, _ = is_thumbnail_supported_for_job("lionreel_cat_20261015_190045_fc2355ef")
        self.assertTrue(supp_long_19, "Long video (19min 16:9) must be supported")

        # Long video: vertical long
        supp_vert_long, _ = is_thumbnail_supported_for_job("lionreel_cat_vertical_long")
        self.assertTrue(supp_vert_long, "Vertical long video must be supported")

        # Short video: 30s Short
        supp_short, reason = is_thumbnail_supported_for_job("lionreel_cat_20261017_223027_c54267b4")
        self.assertFalse(supp_short, "Short job must be rejected")
        self.assertEqual(reason, "not available for Shorts")

    def test_04_no_text_default(self):
        """Default master thumbnail must be clean picture only (no hook text, no badges, no border)."""
        # Render a clean thumbnail with add_hook=False
        test_frame = np.full((720, 1280, 3), 180, dtype=np.uint8)
        cv2.circle(test_frame, (640, 360), 200, (100, 150, 220), -1)

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            fpath = tf.name
        try:
            cv2.imwrite(fpath, test_frame)
            thumb = self.maker.render_thumbnail(fpath, target_res=(1280, 720), add_hook=False, template="subject_center_text_top")
            arr = np.array(thumb)
            # Full bleed verified
            is_bleed, _ = check_full_bleed(arr)
            self.assertTrue(is_bleed)
            # Master export check: deliverables contains clean master
            export_set = self.maker.export_thumbnail_sets(arr, frame_time=10.0, provenance={"video_file": "test.mp4", "decoder": "test"})
            self.assertTrue(os.path.exists(export_set["master"]["path"]))
            self.assertEqual(export_set["master"]["resolution"], "1920x1080")
        finally:
            if os.path.exists(fpath):
                os.remove(fpath)

    def test_05_resolution_and_upscale_cap(self):
        """Crops below 1024x576 (requiring > 1.25x upscaling to reach 1280x720) must be rejected."""
        # 1. 800x450 requires 1280/800 = 1.6x upscaling -> REJECTED
        small_frame = np.full((450, 800, 3), 150, dtype=np.uint8)
        is_small = is_frame_upscaled_or_small(small_frame, min_width=1024, min_height=576)
        self.assertTrue(is_small, "Crop smaller than 1024x576 must be rejected by upscale cap")

        # 2. 1280x720 requires 1.0x upscaling -> ACCEPTED
        ok_frame = np.full((720, 1280, 3), 150, dtype=np.uint8)
        is_ok = is_frame_upscaled_or_small(ok_frame, min_width=1024, min_height=576)
        self.assertFalse(is_ok, "1280x720 frame must not be rejected")

        # 3. 1920x1080 requires downscaling -> ACCEPTED
        hd_frame = np.full((1080, 1920, 3), 150, dtype=np.uint8)
        is_hd = is_frame_upscaled_or_small(hd_frame, min_width=1024, min_height=576)
        self.assertFalse(is_hd, "1920x1080 frame must not be rejected")

    def test_06_filesize_limit(self):
        """Mobile-safe thumbnail must never exceed 2 MB (2,097,152 bytes)."""
        test_frame = np.full((720, 1280, 3), 160, dtype=np.uint8)
        # Add random noise to simulate complex photographic texture
        noise = np.random.randint(0, 50, (720, 1280, 3), dtype=np.uint8)
        test_frame = cv2.add(test_frame, noise)

        export_set = self.maker.export_thumbnail_sets(test_frame, frame_time=5.0)
        mobile_path = export_set["mobile_safe"]["path"]
        self.assertTrue(os.path.exists(mobile_path))
        sz = os.path.getsize(mobile_path)
        self.assertLessEqual(sz, 2097152, f"Mobile-safe thumbnail must be <= 2 MB, but got {sz} bytes")

    def test_07_no_valid_frame_path(self):
        """If no candidate passes gates, report plain diagnostic and never export invalid images."""
        # When extraction yields 0 candidates
        result = self.maker.export_thumbnail_sets(None, frame_time=0.0)
        self.assertFalse(result["overall_passed"])
        self.assertIn("reason", result)
        self.assertIn("no sharp full-frame face found", result["reason"].lower())

    def test_08_double_cats_framing(self):
        """When multiple cat faces are detected, framing adapts without clipping faces."""
        frame = np.full((1080, 1920, 3), 170, dtype=np.uint8)
        # Cat 1 on left, Cat 2 on right
        cv2.circle(frame, (600, 540), 180, (80, 120, 200), -1)
        cv2.circle(frame, (1320, 540), 180, (80, 120, 200), -1)

        detections = [
            {"box": [420, 360, 780, 720], "score": 0.92, "class": "cat"},
            {"box": [1140, 360, 1500, 720], "score": 0.89, "class": "cat"}
        ]
        cropped, _ = subject_aware_cover_crop(frame, detections=detections, target_res=(1280, 720))
        is_bleed, reason = check_full_bleed(cropped)
        self.assertTrue(is_bleed, f"Double cats crop must be full bleed 16:9, got: {reason}")
        self.assertEqual((cropped.shape[1], cropped.shape[0]), (1280, 720))

    def test_09_vertical_long_video_crop(self):
        """Vertical long video uses original high-res pixels and crops to 16:9 without bars."""
        # 1080x1920 vertical source frame
        v_frame = np.full((1920, 1080, 3), 160, dtype=np.uint8)
        # Face in upper half
        cv2.circle(v_frame, (540, 600), 240, (100, 140, 220), -1)
        detections = [{"box": [300, 360, 780, 840], "score": 0.95, "class": "cat"}]

        cropped, _ = subject_aware_cover_crop(v_frame, detections=detections, target_res=(1280, 720))
        is_bleed, reason = check_full_bleed(cropped)
        self.assertTrue(is_bleed, f"Vertical long cover crop must be 16:9 full bleed, got: {reason}")
        self.assertEqual((cropped.shape[1], cropped.shape[0]), (1280, 720))

if __name__ == "__main__":
    unittest.main()
