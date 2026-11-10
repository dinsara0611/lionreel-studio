"""
Tests for 4K Ultra-HD Thumbnail Quality (3840x2160):
1. 4K resolution (3840x2160) and exact 16:9 aspect ratio.
2. File size strictly under 2.0 MB (2,097,152 bytes) with dynamic quality search.
3. Visual quality enhancement (unsharp masking, micro-contrast, 4:4:4 chroma subsampling).
4. Full bleed contract verification (0 black bars, edge-to-edge).
5. Deliverables discovery and safe job file resolution for 4K Master thumbnail.
"""

import os
import sys
import unittest
import tempfile
import json
import cv2
import numpy as np
from PIL import Image

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from thumbnail_maker import (
    ThumbnailMaker,
    check_full_bleed,
    enhance_visual_quality,
    save_jpeg_under_limit
)
import deliverables_manager


class TestThumbnail4KQuality(unittest.TestCase):
    def setUp(self):
        self.job_id = "test_4k_quality_job"
        self.maker = ThumbnailMaker(self.job_id)

    def test_4k_resolution_and_aspect_ratio(self):
        """Verifies that 4K thumbnail renders at exact 3840x2160 resolution with 16:9 aspect ratio."""
        # Create a synthetic 1080p source frame
        frame = np.full((1080, 1920, 3), 128, dtype=np.uint8)
        cv2.circle(frame, (960, 540), 250, (60, 120, 210), -1)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            fpath = tf.name
        try:
            cv2.imwrite(fpath, frame)
            img_4k = self.maker.render_thumbnail(
                fpath,
                target_res=(3840, 2160),
                is_4k=True
            )
            self.assertEqual(img_4k.size, (3840, 2160))
            aspect = img_4k.width / float(img_4k.height)
            self.assertAlmostEqual(aspect, 16.0 / 9.0, places=2)
        finally:
            if os.path.exists(fpath):
                os.remove(fpath)

    def test_4k_file_size_strictly_under_2mb(self):
        """
        User requirement: '4k qulit ok it mwan quliok ok not file sixe ok'
        4K image must be strictly <= 2,000,000 bytes (under YouTube 2.0 MB limit).
        """
        # Create a detailed textured 4K image (synthetic fur texture)
        np.random.seed(42)
        base = np.full((2160, 3840, 3), 140, dtype=np.uint8)
        noise = np.random.randint(-25, 25, (2160, 3840, 3), dtype=np.int16)
        textured = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        img_pil = Image.fromarray(cv2.cvtColor(textured, cv2.COLOR_BGR2RGB))

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            out_path = tf.name
        try:
            size_bytes, q_used = save_jpeg_under_limit(
                img_pil,
                out_path,
                max_bytes=2000000,
                is_4k=True
            )
            self.assertLessEqual(size_bytes, 2000000, f"4K file size {size_bytes} exceeds 2.0 MB limit")
            self.assertLessEqual(os.path.getsize(out_path), 2000000)
            self.assertGreaterEqual(q_used, 60, "JPEG quality should remain high")
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)

    def test_4k_visual_enhancement_and_sharpness(self):
        """Verifies that 4K visual enhancement sharpens edges without clipping."""
        # Create an image with soft edges
        soft_img = np.full((720, 1280, 3), 120, dtype=np.uint8)
        cv2.circle(soft_img, (640, 360), 120, (200, 200, 200), -1)
        soft_img = cv2.GaussianBlur(soft_img, (7, 7), 2.0)
        pil_soft = Image.fromarray(cv2.cvtColor(soft_img, cv2.COLOR_BGR2RGB))

        # Measure baseline Laplacian variance
        gray_before = cv2.cvtColor(np.array(pil_soft), cv2.COLOR_RGB2GRAY)
        lap_before = float(cv2.Laplacian(gray_before, cv2.CV_64F).var())

        # Apply 4K enhancement
        enhanced = enhance_visual_quality(pil_soft, is_4k=True)
        gray_after = cv2.cvtColor(np.array(enhanced), cv2.COLOR_RGB2GRAY)
        lap_after = float(cv2.Laplacian(gray_after, cv2.CV_64F).var())

        self.assertGreater(lap_after, lap_before, "4K enhancement must increase sharpness (Laplacian variance)")

    def test_4k_full_bleed_zero_bars(self):
        """Verifies 4K rendered output passes full-bleed gate with zero black bars."""
        frame = np.full((1080, 1920, 3), 130, dtype=np.uint8)
        cv2.circle(frame, (960, 540), 200, (80, 160, 240), -1)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            fpath = tf.name
        try:
            cv2.imwrite(fpath, frame)
            img_4k = self.maker.render_thumbnail(fpath, target_res=(3840, 2160), is_4k=True)
            is_bleed, reason = check_full_bleed(img_4k)
            self.assertTrue(is_bleed, f"4K thumbnail must pass full bleed gate, but failed: {reason}")
        finally:
            if os.path.exists(fpath):
                os.remove(fpath)

    def test_4k_export_sets_and_deliverables_integration(self):
        """Verifies export_thumbnail_sets exports 4K files and deliverables_manager discovers them."""
        frame = np.full((720, 1280, 3), 140, dtype=np.uint8)
        cv2.circle(frame, (640, 360), 150, (100, 150, 200), -1)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            fpath = tf.name
        try:
            cv2.imwrite(fpath, frame)
            exports = self.maker.export_thumbnail_sets(fpath)

            # 4K deliverable checks
            self.assertIn("ultra_hd_4k", exports)
            u4k = exports["ultra_hd_4k"]
            self.assertEqual(u4k["resolution"], "3840x2160")
            self.assertEqual(u4k["chroma_subsampling"], "4:4:4")
            self.assertTrue(os.path.exists(u4k["path"]))
            self.assertLessEqual(u4k["size_bytes"], 2000000)

            # Metadata JSON file exists
            json_4k_path = os.path.join(self.maker.thumb_dir, "thumbnail_4k_3840x2160.json")
            self.assertTrue(os.path.exists(json_4k_path))
            with open(json_4k_path, "r", encoding="utf-8") as jf:
                data = json.load(jf)
            self.assertEqual(data["resolution"], "3840x2160")
            self.assertEqual(data["chroma_subsampling"], "4:4:4")
            self.assertTrue(data["size_under_2mb"])

            # Report includes ultra_hd_4k
            rep_path = os.path.join(self.maker.output_dir, "thumbnail_report.json")
            self.assertTrue(os.path.exists(rep_path))
            with open(rep_path, "r", encoding="utf-8") as rf:
                rep = json.load(rf)
            self.assertIn("ultra_hd_4k", rep)
            self.assertEqual(rep["ultra_hd_4k"]["resolution"], "3840x2160")

            # deliverables_manager discovery
            discovered = deliverables_manager.discover_job_deliverables(self.job_id)
            thumb_items = [d for d in discovered.get("deliverables", []) if d.get("category") == "thumbnail"]
            names = [d.get("name", "") for d in thumb_items]
            has_4k_label = any("4K Ultra-HD" in n for n in names)
            self.assertTrue(has_4k_label, f"Deliverables manager must list 4K Ultra-HD Thumbnail, found: {names}")

            # deliverables_manager safe resolution
            resolved = deliverables_manager.resolve_safe_job_file(self.job_id, "thumbnail_4k_3840x2160.jpg")
            self.assertTrue(os.path.exists(resolved))
        finally:
            if os.path.exists(fpath):
                os.remove(fpath)


if __name__ == "__main__":
    unittest.main()
