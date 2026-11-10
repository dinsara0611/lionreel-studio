"""
Unit and integration tests for Part 1: Automated Job Report Generator (report.json, report.html, report.pdf).
Uses standard unittest framework.
"""

import os
import sys
import json
import unittest
import pypdf
import tempfile
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from report_generator import (
    build_report_data,
    render_report_html,
    generate_report_pdf,
    generate_job_report
)

REAL_JOB_ID = "lionreel_cat_20261026_092004_9c9af4ac"
OUTPUT_JOB_DIR = os.path.join(BASE_DIR, "output", REAL_JOB_ID)


class TestReportGenerator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Generates the report for the real verified 20-min job."""
        cls.report_res = generate_job_report(REAL_JOB_ID)
        assert cls.report_res["pdf_success"] is True, f"PDF generation failed: {cls.report_res.get('error')}"

    def test_report_json_traceability_and_provenance(self):
        """Test that all summary figures match source artifacts and sources_map is populated."""
        json_path = self.report_res["report_json"]
        self.assertTrue(os.path.exists(json_path))
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        sources = data.get("_sources", {})
        self.assertIn("summary.job_id", sources)
        self.assertIn("summary.duration", sources)
        self.assertIn("summary.delivered_clips", sources)

        # Recompute from mapping.json
        mapping_path = os.path.join(OUTPUT_JOB_DIR, f"{REAL_JOB_ID}_mapping.json")
        if not os.path.exists(mapping_path):
            mapping_path = os.path.join(OUTPUT_JOB_DIR, "mapping.json")
        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping_data = json.load(f)
        clips_list = mapping_data.get("clips", []) if isinstance(mapping_data, dict) else mapping_data
        self.assertEqual(data["summary"]["delivered_clips"], len(clips_list))
        self.assertEqual(len(data["clips_table"]), len(clips_list))

    def test_exclusive_times_sum_to_total(self):
        """Test that exclusive stage times sum to subtotal and percentage shares sum to ~100%."""
        with open(self.report_res["report_json"], "r", encoding="utf-8") as f:
            data = json.load(f)

        timing_sec = data.get("timing_breakdown", {})
        exclusive_rows = timing_sec.get("exclusive_stages", [])
        if exclusive_rows:
            row_sum = sum(r["exclusive_sec"] for r in exclusive_rows)
            subtotal = timing_sec.get("total_exclusive_sec", 0.0)
            self.assertAlmostEqual(row_sum, subtotal, delta=1.0)
            share_sum = sum(r["share_pct"] for r in exclusive_rows)
            self.assertAlmostEqual(share_sum, 100.0, delta=2.0)

    def test_pdf_properties_and_selectable_text(self):
        """Verify PDF exists, size < 10 MB, text is selectable, and contains expected tokens."""
        pdf_path = self.report_res["report_pdf"]
        self.assertTrue(os.path.exists(pdf_path))
        file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        self.assertLess(file_size_mb, 10.0, f"PDF file size {file_size_mb:.2f} MB exceeds 10 MB limit")

        reader = pypdf.PdfReader(pdf_path)
        page_count = len(reader.pages)
        self.assertGreaterEqual(page_count, 1)
        self.assertLessEqual(page_count, 25)

        full_text = ""
        for p in reader.pages:
            full_text += p.extract_text() or ""

        self.assertGreater(len(full_text), 500)
        self.assertIn(REAL_JOB_ID, full_text)
        self.assertTrue("PASSED" in full_text or "SUCCESS" in full_text or "FAILED" in full_text or "NOT RUN" in full_text)
        self.assertTrue("Delivered Length" in full_text or "DELIVERED LENGTH" in full_text)
        self.assertTrue("Clip Count" in full_text or "CLIP COUNT" in full_text or "Delivered Clips" in full_text or "DELIVERED CLIPS" in full_text)

    def test_pagination_for_100_plus_clips(self):
        """Verify that jobs with 100+ clips paginate properly in the HTML report."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_job_id = "test_pagination_120_clips"
            job_dir = os.path.join(tmp_dir, "output", test_job_id)
            os.makedirs(job_dir, exist_ok=True)

            clips = []
            for i in range(120):
                clips.append({
                    "clip_id": f"clip_{i:03d}",
                    "source_id": f"yt_source_{i % 10}",
                    "title": f"Funny Cat Moment #{i+1}",
                    "uploader": f"Creator {i % 5}",
                    "license": "Creative Commons",
                    "duration": 7.5,
                    "start_s": 10.0,
                    "end_s": 17.5,
                    "framing_score": 98.5,
                    "sharpness": 280.0
                })

            with open(os.path.join(job_dir, "mapping.json"), "w", encoding="utf-8") as f:
                json.dump({"clips": clips}, f)

            with open(os.path.join(job_dir, "job_config.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "job_id": test_job_id,
                    "target_seconds": 900.0,
                    "aspect_ratio": "16:9",
                    "clips": 120
                }, f)

            report_data = build_report_data(test_job_id, output_dir=job_dir)
            html = render_report_html(report_data)

            self.assertTrue("page-break-after: always" in html or "page-break-inside: avoid" in html)
            self.assertIn("clip_119", html)
            self.assertIn("Funny Cat Moment #120", html)

    def test_failed_job_diagnostic_report(self):
        """Verify that a failed job gets a diagnostic report with 'What happened' and last 30 log lines."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            fail_job_id = "test_failed_job_diagnostic"
            job_dir = os.path.join(tmp_dir, "output", fail_job_id)
            os.makedirs(job_dir, exist_ok=True)

            log_lines = [f"[2026-10-16 09:00:{i:02d}] INFO Stage running step {i}" for i in range(50)]
            log_lines.append("[2026-10-16 09:01:00] ERROR Concat failed: non-matching audio sample rates in clip_007")

            with open(os.path.join(job_dir, "job_config.json"), "w", encoding="utf-8") as f:
                json.dump({"job_id": fail_job_id, "target_seconds": 60.0}, f)

            report_data = build_report_data(
                fail_job_id,
                is_success=False,
                failure_reason="Concat failed: non-matching audio sample rates in clip_007",
                output_dir=job_dir,
                raw_log_lines=log_lines
            )

            self.assertEqual(report_data["status"], "FAILED")
            diagnostic = report_data.get("failure_diagnostic", {})
            self.assertIn("Concat failed", diagnostic.get("reason_code", ""))
            self.assertLessEqual(len(diagnostic.get("last_30_log_lines", [])), 30)
            self.assertIn("clip_007", "\n".join(diagnostic.get("last_30_log_lines", [])))

            html = render_report_html(report_data)
            self.assertIn("Diagnostic", html)
            self.assertIn("Resumption Strategy", html)


if __name__ == "__main__":
    unittest.main()
