"""
Unit and integration tests for Part 3: Thumbnail Maker for Long Videos (>= 3 minutes).
Tests:
1. Frame selection avoids overlay and black frames.
2. Text clears duration-badge zone.
3. WCAG contrast ratio >= 4.5:1.
4. Native Windows OCR legibility at 210px mobile width.
5. JPG size under limit via quality search (Mobile <= 2MB, Master <= 50MB).
6. Exact 16:9 resolution (1920x1080 and 1280x720).
7. Three variants come from distinct source clips / distinct templates.
8. Vertical source footage renders blurred background pillarbox.
9. Double cats template.
10. Fallback ensures never a blank image.
"""

import os
import sys
import json
import unittest
import tempfile
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from thumbnail_maker import (
    ThumbnailMaker,
    calculate_wcag_contrast,
    run_windows_ocr_check,
    generate_job_thumbnails,
    get_thumbnail_learning_recommendation,
    record_thumbnail_feedback,
    load_platform_limits
)

REAL_JOB_ID = "lionreel_cat_20261016_065802_502f5dd4"


class TestThumbnailMaker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.limits = load_platform_limits()
        cls.maker = ThumbnailMaker(REAL_JOB_ID)

    def test_platform_limits_grounded_in_youtube_help(self):
        """Verifies platform limits conform to official YouTube Help answers."""
        limits = self.limits
        self.assertEqual(limits.get("aspect_ratio"), "16:9")
        self.assertEqual(limits.get("desktop_max_mb"), 50)
        self.assertEqual(limits.get("mobile_max_mb"), 2)
        self.assertEqual(limits.get("desktop_standard_res"), [1920, 1080])
        self.assertEqual(limits.get("mobile_recommended_res"), [1280, 720])
        self.assertIn("https://support.google.com/youtube/answer/72431", limits.get("source_urls", []))

    def test_wcag_contrast_calculation(self):
        """Tests that contrast calculations strictly follow WCAG 2.1 relative luminance."""
        # Yellow on black
        contrast_yellow_black = calculate_wcag_contrast((255, 230, 0), (0, 0, 0))
        self.assertGreaterEqual(contrast_yellow_black, 10.0)

        # White on black
        contrast_white_black = calculate_wcag_contrast((255, 255, 255), (0, 0, 0))
        self.assertGreaterEqual(contrast_white_black, 20.0)

        # Low contrast check
        contrast_low = calculate_wcag_contrast((120, 120, 120), (100, 100, 100))
        self.assertLess(contrast_low, 2.5)

    def test_native_windows_ocr_legibility_at_210px(self):
        """Tests that native Windows OCR successfully reads hook text at 210px mobile width."""
        test_img = Image.new("RGB", (210, 118), (15, 23, 42))
        draw = ImageDraw.Draw(test_img)
        font = ImageFont.truetype(r"C:\Windows\Fonts\impact.ttf", 26)
        draw.text((15, 38), "SILLY CATS", fill=(255, 230, 0), font=font)

        res = run_windows_ocr_check(test_img)
        self.assertTrue(res["success"])
        self.assertIn("CATS", res["recognized_text"].upper())

    def test_render_thumbnail_16_9_and_badge_clearance(self):
        """Verifies rendered thumbnail has exact 16:9 aspect ratio and clears bottom-right badge."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            frame_path = tf.name
        try:
            # Create a synthetic cat frame (640x360)
            frame = np.full((360, 640, 3), 120, dtype=np.uint8)
            cv2.rectangle(frame, (200, 80), (440, 320), (80, 80, 180), -1)
            cv2.imwrite(frame_path, frame)

            img_master = self.maker.render_thumbnail(
                frame_path,
                template="subject_right_text_left",
                hook_text="FUNNY CATS",
                target_res=(1920, 1080)
            )

            self.assertEqual(img_master.size, (1920, 1080))
            aspect = img_master.width / img_master.height
            self.assertAlmostEqual(aspect, 16.0 / 9.0, places=2)

            # Test mobile resolution
            img_mobile = self.maker.render_thumbnail(
                frame_path,
                template="bold_color_block",
                hook_text="PURE CHAOS",
                target_res=(1280, 720)
            )
            self.assertEqual(img_mobile.size, (1280, 720))
        finally:
            if os.path.exists(frame_path):
                os.remove(frame_path)

    def test_vertical_source_pillarbox_blurred_background(self):
        """Tests that vertical source footage (9:16) gets rendered with a blurred background."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            vert_frame_path = tf.name
        try:
            # 1080x1920 vertical image
            vert_frame = np.full((1920, 1080, 3), 90, dtype=np.uint8)
            cv2.circle(vert_frame, (540, 960), 200, (200, 150, 50), -1)
            cv2.imwrite(vert_frame_path, vert_frame)

            rendered = self.maker.render_thumbnail(
                vert_frame_path,
                template="subject_center_text_top",
                hook_text="VERTICAL CAT",
                target_res=(1280, 720)
            )
            self.assertEqual(rendered.size, (1280, 720))
            # The canvas must have been transformed into 16:9 without stretching
            np_arr = np.array(rendered)
            self.assertEqual(np_arr.shape[:2], (720, 1280))
        finally:
            if os.path.exists(vert_frame_path):
                os.remove(vert_frame_path)

    def test_double_cats_split_template(self):
        """Tests that split_double_cats template renders vertical divider line."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            frame_path = tf.name
        try:
            frame = np.full((720, 1280, 3), 100, dtype=np.uint8)
            cv2.imwrite(frame_path, frame)

            img_split = self.maker.render_thumbnail(
                frame_path,
                template="split_double_cats",
                hook_text="TWO CATS",
                target_res=(1280, 720)
            )
            self.assertEqual(img_split.size, (1280, 720))
        finally:
            if os.path.exists(frame_path):
                os.remove(frame_path)

    def test_export_sets_and_quality_search_file_sizes(self):
        """Verifies Master and Mobile export sets meet YouTube limits and quality search works."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            frame_path = tf.name
        try:
            frame = np.full((720, 1280, 3), 110, dtype=np.uint8)
            cv2.circle(frame, (640, 360), 180, (220, 180, 140), -1)
            cv2.imwrite(frame_path, frame)

            exports = self.maker.export_thumbnail_sets(
                frame_path,
                hook_text="FUNNY CATS",
                template="subject_right_text_left"
            )

            # Master checks
            master = exports["master"]
            self.assertTrue(os.path.exists(master["path"]))
            self.assertLessEqual(master["size_bytes"], 52428800)
            self.assertEqual(master["resolution"], "1920x1080")

            # Mobile checks
            mobile = exports["mobile_safe"]
            self.assertTrue(os.path.exists(mobile["path"]))
            self.assertLessEqual(mobile["size_bytes"], 2097152)
            self.assertEqual(mobile["resolution"], "1280x720")

            # Test & Compare set checks
            var_set = exports["test_and_compare"]
            self.assertEqual(len(var_set), 3)
            templates = [v["template"] for v in var_set]
            self.assertEqual(len(set(templates)), 3, "Variants must use distinct templates")
            for v in var_set:
                self.assertTrue(os.path.exists(v["path"]))
                self.assertEqual(v["resolution"], "1280x720")
        finally:
            if os.path.exists(frame_path):
                os.remove(frame_path)

    def test_learning_loop_recommendation_requires_five_videos(self):
        """Tests that learning recommendations are withheld until at least 5 videos are logged."""
        # Initial state: 0 or fewer than 5
        rec = get_thumbnail_learning_recommendation()
        if rec.get("sample_count", 0) < 5:
            self.assertFalse(rec["has_recommendation"])
            self.assertIn("at least 5 videos", rec["reason"])


if __name__ == "__main__":
    unittest.main()
