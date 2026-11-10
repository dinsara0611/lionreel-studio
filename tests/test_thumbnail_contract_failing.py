"""
Tests for Thumbnail Maker Contract:
1. Letterboxed input (outer 3% rows dark/flat) must be rejected or cropped to 100% full bleed (zero black bars).
2. 4:3 input must use subject-aware cover crop (never distorted, never pillarboxed/letterboxed, exactly 1280x720).
3. Small input (< 1280 px wide) must be rejected (never upscaled).
4. Text-on-frame input must be rejected by text gate.
5. Short job (duration < 180s or short mode) must produce NO custom thumbnail.
"""

import os
import sys
import unittest
import numpy as np
import cv2
import tempfile
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from thumbnail_maker import (
    ThumbnailMaker,
    generate_job_thumbnails,
    check_full_bleed,
    is_frame_upscaled_or_small
)

class TestThumbnailContract(unittest.TestCase):
    def setUp(self):
        self.maker = ThumbnailMaker("test_contract_job")

    def test_letterboxed_input_rejected_or_cropped_full_bleed(self):
        """Outer 3% rows/columns must NOT be uniformly dark/flat (no black/blurred bars)."""
        # Create a 1920x1080 frame with black bars on top and bottom (letterboxed)
        frame = np.full((1080, 1920, 3), 140, dtype=np.uint8)
        bar_h = int(1080 * 0.12)
        frame[:bar_h, :] = 0  # top black bar
        frame[-bar_h:, :] = 0  # bottom black bar

        # Check full bleed gate function
        is_bleed, reason = check_full_bleed(frame)
        self.assertFalse(is_bleed, f"Letterboxed frame must fail full bleed gate, but passed: {reason}")

    def test_4_3_input_subject_aware_cover_crop(self):
        """4:3 input must be cover-cropped to 1280x720 16:9 without bars or distortion."""
        # 1440x1080 is 4:3 (width >= 1280)
        frame_4_3 = np.full((1080, 1440, 3), 150, dtype=np.uint8)
        # Draw a synthetic cat face centered at (720, 540)
        cv2.circle(frame_4_3, (720, 540), 180, (50, 100, 200), -1)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            fpath = tf.name
        try:
            cv2.imwrite(fpath, frame_4_3)
            thumb = self.maker.render_thumbnail(fpath, target_res=(1280, 720))
            self.assertEqual(thumb.size, (1280, 720))

            # Convert to numpy and check full bleed (no bars)
            arr = np.array(thumb)
            is_bleed, reason = check_full_bleed(arr)
            self.assertTrue(is_bleed, f"Cover crop of 4:3 must produce full bleed, but got: {reason}")
        finally:
            if os.path.exists(fpath):
                os.remove(fpath)

    def test_small_input_rejected_never_upscaled(self):
        """Source frame smaller than 1280 px wide must be rejected (never upscaled)."""
        small_frame = np.full((480, 640, 3), 120, dtype=np.uint8)
        is_small = is_frame_upscaled_or_small(small_frame, min_width=1280)
        self.assertTrue(is_small, "Frames under 1280px width must be flagged as small/rejected")

    def test_text_on_frame_rejected(self):
        """Frame with creator text/burned-in overlay must be rejected."""
        frame = np.full((720, 1280, 3), 160, dtype=np.uint8)
        # Put high-contrast creator text in bottom 25%
        cv2.putText(frame, "SUBSCRIBE TO MY CHANNEL! LIKE & SHARE", (100, 660),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)

        has_text = self.maker.detect_burned_in_text(frame)
        self.assertTrue(has_text, "Frame with burned-in subtitles/creator text must be detected and rejected")

    def test_short_job_creates_no_thumbnail(self):
        """Short video (< 180s) must produce NO thumbnail output."""
        res = generate_job_thumbnails("lionreel_cat_20261016_084742_31bc5d3b")
        # lionreel_cat_20261016_084742_31bc5d3b is a 30s Short!
        self.assertTrue(res.get("skipped"), "Short video jobs must skip thumbnail generation entirely")
        thumb_file = os.path.join(BASE_DIR, "output", "lionreel_cat_20261016_084742_31bc5d3b", "thumbnail.jpg")
        self.assertFalse(os.path.exists(thumb_file), f"No thumbnail.jpg should exist for Short job, but found {thumb_file}")

if __name__ == "__main__":
    unittest.main()
