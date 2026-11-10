import os
import sys
import unittest
import json
import zipfile
import io

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import deliverables_manager

class TestDownloadCenter(unittest.TestCase):
    def setUp(self):
        self.job_id = "lionreel_cat_20261026_092004_9c9af4ac"

    def test_deliverables_discovery_real_job(self):
        """Verifies deliverables discovery on real job artifacts without typed numbers."""
        data = deliverables_manager.discover_job_deliverables(self.job_id)
        self.assertEqual(data["job_id"], self.job_id)
        self.assertTrue(data["has_video"])
        self.assertGreater(data["total_deliverables"], 5)
        self.assertGreater(data["total_size_bytes"], 30 * 1024 * 1024) # Real video > 30MB

        categories = {d["category"] for d in data["deliverables"]}
        self.assertIn("video", categories)
        self.assertIn("report", categories)
        self.assertIn("metadata", categories)
        self.assertIn("visual", categories)

        for d in data["deliverables"]:
            self.assertTrue(d["filename"])
            self.assertTrue(d["download_url"])
            self.assertGreater(d["size_bytes"], 0)
            self.assertTrue(d["size_formatted"])

    def test_download_pack_excludes_video_and_creates_valid_zip(self):
        """Validates that download pack creates a valid ZIP strictly containing non-video files."""
        zip_buf, zip_name = deliverables_manager.create_non_video_download_pack(self.job_id)
        self.assertTrue(zip_name.endswith("_assets.zip"))
        self.assertGreater(len(zip_buf.getvalue()), 1000)

        with zipfile.ZipFile(zip_buf, "r") as zf:
            namelist = zf.namelist()
            self.assertGreater(len(namelist), 3)
            # CRITICAL RULE: Video must NEVER be in download pack
            for fname in namelist:
                self.assertFalse(fname.lower().endswith(".mp4"), f"Video file {fname} found inside non-video download pack!")
                self.assertFalse(fname.lower().endswith(".webm"))

            # Must contain report, metadata, and visuals
            has_report = any("report" in n.lower() for n in namelist)
            has_meta = any("metadata" in n.lower() or "credits" in n.lower() for n in namelist)
            self.assertTrue(has_report, "Report missing from download pack")
            self.assertTrue(has_meta, "Metadata missing from download pack")

    def test_path_traversal_prevention(self):
        """Verifies that attempts to break out of job directories are strictly blocked."""
        # 1. Path traversal with ..
        with self.assertRaises(PermissionError):
            deliverables_manager.resolve_safe_job_file(self.job_id, "../../../Windows/System32/calc.exe")

        with self.assertRaises(PermissionError):
            deliverables_manager.resolve_safe_job_file(self.job_id, "..\\..\\config.json")

        with self.assertRaises(PermissionError):
            deliverables_manager.resolve_safe_job_file(self.job_id, "output/../../web_server.py")

        # 2. Non-existent file
        with self.assertRaises(FileNotFoundError):
            deliverables_manager.resolve_safe_job_file(self.job_id, "completely_bogus_file_12345.xyz")

        # 3. Legitimate file
        safe_file = deliverables_manager.resolve_safe_job_file(self.job_id, f"{self.job_id}_report.pdf")
        self.assertTrue(os.path.exists(safe_file))
        self.assertTrue(safe_file.endswith(".pdf"))

    def test_file_size_formatting(self):
        """Tests standard file size formatting utility."""
        self.assertEqual(deliverables_manager.format_file_size(500), "500 B")
        self.assertEqual(deliverables_manager.format_file_size(2048), "2.0 KB")
        self.assertEqual(deliverables_manager.format_file_size(10 * 1024 * 1024), "10.0 MB")
        self.assertEqual(deliverables_manager.format_file_size(1500 * 1024 * 1024), "1.46 GB")

if __name__ == "__main__":
    unittest.main()
