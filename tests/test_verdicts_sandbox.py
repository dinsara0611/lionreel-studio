"""
tests/test_verdicts_sandbox.py
==============================
Sandbox test matrix validating all 4 unified verdicts:
1. PASSED
2. PASSED WITH WARNINGS
3. FAILED
4. NOT RUN

Generates mock job directories, invokes report_generator.generate_job_report(),
validates JSON verdict integrity, HTML rendering, and PDF compilation.
"""

import os
import sys
import json
import unittest
import tempfile
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import report_generator


class TestVerdictsSandbox(unittest.TestCase):
    def setUp(self):
        self.tmp_root = tempfile.mkdtemp(prefix="lionreel_sandbox_verdicts_")

    def tearDown(self):
        if os.path.exists(self.tmp_root):
            shutil.rmtree(self.tmp_root, ignore_errors=True)

    def _create_mock_job(self, job_id, qa_data, clips, target_dur=60.0, actual_dur=60.0):
        job_dir = os.path.join(self.tmp_root, job_id)
        os.makedirs(job_dir, exist_ok=True)

        # 1. config
        config = {
            "JOB_ID": job_id,
            "TARGET_DURATION_SEC": target_dur,
            "ASPECT_RATIO": "16:9",
            "THEME": "cat_sandbox",
            "OUTPUT_NAME": f"{job_id}.mp4"
        }
        with open(os.path.join(job_dir, "job_config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        # 2. mapping
        mapping = {
            "job_id": job_id,
            "clips": clips,
            "total_duration_sec": actual_dur
        }
        with open(os.path.join(job_dir, "mapping.json"), "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2)

        # 3. qa report
        with open(os.path.join(job_dir, "qa_report.json"), "w", encoding="utf-8") as f:
            json.dump(qa_data, f, indent=2)

        # 4. metadata
        meta = {
            "title": f"Test Video {job_id}",
            "description": "Sandbox verification video",
            "tags": "cat, funny, sandbox, test"
        }
        with open(os.path.join(job_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        return job_dir

    def test_verdict_passed(self):
        """Case 1: 100% hard gates pass, 0 warnings -> PASSED (green)."""
        job_id = "sandbox_job_passed"
        # 10 clips, 6 unique sources, 10 unique windows, author set
        clips = []
        for i in range(10):
            clips.append({
                "clip_id": f"clip_{i:02d}",
                "source_id": f"src_channel_{i % 6:02d}",
                "start_s": float(i * 10),
                "end_s": float(i * 10 + 6),
                "duration_s": 6.0,
                "uploader": f"Creator {i % 6:02d}",
                "source_title": f"Source Video {i % 6:02d}",
                "use_count": 1
            })

        qa_data = {
            "passed": True,
            "overall_status": "PASSED",
            "duration_contract": {
                "target_duration_s": 60.0,
                "actual_duration_s": 60.0,
                "duration_diff_s": 0.0,
                "allowed_tolerance_s": 1.0,
                "passed": True
            },
            "pet_centering": {
                "passed_frames": 16,
                "sampled_frames": 16,
                "detected_frames": 16,
                "passed": True
            },
            "sharpness": {
                "min_sharpness": 380.5,
                "median_sharpness": 520.0,
                "benchmark_floor": 150.0,
                "passed": True
            },
            "watermark_gate": {"passed": True, "reason": "No watermark detected"},
            "burned_in_text_gate": {"passed": True, "reason": "Frame overlays clean"},
            "gates": {
                "gate_1_stream_specs": {"passed": True, "status": "PASS"},
                "gate_1b_duration_contract": {"passed": True, "status": "PASS"},
                "gate_1c_clip_count": True,
                "gate_2_audio_loudness": {"passed": True, "status": "PASS"},
                "gate_3_black_frames": {"passed": True, "status": "PASS"},
                "gate_4_pet_centering": {"passed": True, "status": "PASS"},
                "gate_5_freeze_frames": {"passed": True, "status": "PASS"},
                "gate_6_watermark": {"passed": True, "status": "PASS"},
                "gate_6b_clean_overlays": {"passed": True, "status": "PASS"},
                "gate_7_audio_clipping": {"passed": True, "status": "PASS"},
                "gate_8_motion_pacing": {"passed": True, "status": "PASS"},
                "gate_9_sharpness": {"passed": True, "status": "PASS"}
            }
        }

        job_dir = self._create_mock_job(job_id, qa_data, clips, target_dur=60.0, actual_dur=60.0)
        res = report_generator.generate_job_report(job_id, output_dir=job_dir, work_dir=job_dir)

        # Inspect report.json
        with open(res["report_json"], "r", encoding="utf-8") as f:
            data = json.load(f)

        verdict = data["unified_verdict"]
        self.assertEqual(verdict["badge"], "PASSED")
        self.assertEqual(verdict["color"], "green")
        self.assertEqual(len(verdict["critical_errors"]), 0)
        self.assertEqual(len(verdict["warnings"]), 0)
        self.assertEqual(len(verdict["not_run_gates"]), 0)

        # Check HTML
        with open(res["report_html"], "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("PASSED / BROADCAST READY", html)
        self.assertIn("badge-success", html)

        # Check PDF
        self.assertTrue(res["pdf_success"], "PDF generation must succeed")
        self.assertTrue(os.path.exists(res["report_pdf"]), "PDF file must exist")

    def test_verdict_passed_with_warnings(self):
        """Case 2: 100% hard gates pass, but warning exists (sources < 5 or repeat > 30%) -> PASSED WITH WARNINGS (amber)."""
        job_id = "sandbox_job_passed_with_warnings"
        # 10 clips from only 2 sources (triggers unique_sources < 5 warning)
        clips = []
        for i in range(10):
            clips.append({
                "clip_id": f"clip_{i:02d}",
                "source_id": f"src_channel_{i % 2:02d}",
                "start_s": float(i * 10),
                "end_s": float(i * 10 + 6),
                "duration_s": 6.0,
                "uploader": f"Creator {i % 2:02d}",
                "source_title": f"Source Video {i % 2:02d}",
                "use_count": 1
            })

        qa_data = {
            "passed": True,
            "overall_status": "PASSED",
            "duration_contract": {
                "target_duration_s": 60.0,
                "actual_duration_s": 60.0,
                "duration_diff_s": 0.0,
                "allowed_tolerance_s": 1.0,
                "passed": True
            },
            "pet_centering": {
                "passed_frames": 15,
                "sampled_frames": 16,
                "detected_frames": 16,
                "passed": True
            },
            "sharpness": {
                "min_sharpness": 280.0,
                "median_sharpness": 400.0,
                "benchmark_floor": 150.0,
                "passed": True
            },
            "watermark_gate": {"passed": True},
            "burned_in_text_gate": {"passed": True},
            "gates": {
                "gate_1_stream_specs": {"passed": True},
                "gate_1b_duration_contract": {"passed": True},
                "gate_1c_clip_count": True,
                "gate_2_audio_loudness": {"passed": True},
                "gate_3_black_frames": {"passed": True},
                "gate_4_pet_centering": {"passed": True},
                "gate_5_freeze_frames": {"passed": True},
                "gate_6_watermark": {"passed": True},
                "gate_6b_clean_overlays": {"passed": True},
                "gate_7_audio_clipping": {"passed": True},
                "gate_8_motion_pacing": {"passed": True},
                "gate_9_sharpness": {"passed": True}
            }
        }

        job_dir = self._create_mock_job(job_id, qa_data, clips, target_dur=60.0, actual_dur=60.0)
        res = report_generator.generate_job_report(job_id, output_dir=job_dir, work_dir=job_dir)

        with open(res["report_json"], "r", encoding="utf-8") as f:
            data = json.load(f)

        verdict = data["unified_verdict"]
        self.assertEqual(verdict["badge"], "PASSED WITH WARNINGS")
        self.assertEqual(verdict["color"], "amber")
        self.assertEqual(len(verdict["critical_errors"]), 0)
        self.assertGreater(len(verdict["warnings"]), 0)
        self.assertTrue(any("diversity" in w.lower() or "unique sources" in w.lower() for w in verdict["warnings"]))

        with open(res["report_html"], "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("PASSED WITH WARNINGS", html)

        self.assertTrue(res["pdf_success"])
        self.assertTrue(os.path.exists(res["report_pdf"]))

    def test_verdict_failed(self):
        """Case 3: Any hard gate fails (e.g. duration diff > 1.0s) -> FAILED (red)."""
        job_id = "sandbox_job_failed"
        clips = []
        for i in range(10):
            clips.append({
                "clip_id": f"clip_{i:02d}",
                "source_id": f"src_channel_{i:02d}",
                "start_s": float(i * 10),
                "end_s": float(i * 10 + 6),
                "duration_s": 6.0,
                "uploader": f"Creator {i:02d}",
                "use_count": 1
            })

        qa_data = {
            "passed": False,
            "overall_status": "FAILED",
            "duration_contract": {
                "target_duration_s": 60.0,
                "actual_duration_s": 55.0,
                "duration_diff_s": 5.0,
                "allowed_tolerance_s": 1.0,
                "passed": False
            },
            "pet_centering": {
                "passed_frames": 16,
                "sampled_frames": 16,
                "passed": True
            },
            "sharpness": {
                "min_sharpness": 300.0,
                "benchmark_floor": 150.0,
                "passed": True
            },
            "gates": {
                "gate_1_stream_specs": {"passed": True},
                "gate_1b_duration_contract": {"passed": False, "reason": "Duration diff 5.0s > 1.0s"},
                "gate_2_audio_loudness": {"passed": True},
                "gate_3_black_frames": {"passed": True},
                "gate_4_pet_centering": {"passed": True},
                "gate_5_freeze_frames": {"passed": True},
                "gate_6_watermark": {"passed": True},
                "gate_6b_clean_overlays": {"passed": True},
                "gate_7_audio_clipping": {"passed": True},
                "gate_8_motion_pacing": {"passed": True},
                "gate_9_sharpness": {"passed": True}
            }
        }

        job_dir = self._create_mock_job(job_id, qa_data, clips, target_dur=60.0, actual_dur=55.0)
        res = report_generator.generate_job_report(job_id, output_dir=job_dir, work_dir=job_dir)

        with open(res["report_json"], "r", encoding="utf-8") as f:
            data = json.load(f)

        verdict = data["unified_verdict"]
        self.assertEqual(verdict["badge"], "FAILED")
        self.assertEqual(verdict["color"], "red")
        self.assertGreater(len(verdict["critical_errors"]), 0)
        self.assertTrue(any("Duration" in err for err in verdict["critical_errors"]))

        with open(res["report_html"], "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("FAILED / REJECTED", html)
        self.assertIn("badge-failed", html)

        self.assertTrue(res["pdf_success"])
        self.assertTrue(os.path.exists(res["report_pdf"]))

    def test_verdict_not_run(self):
        """Case 4: Any gate skipped, crashed, or missing data -> NOT RUN (amber). Never PASSED."""
        job_id = "sandbox_job_not_run"
        clips = []
        for i in range(10):
            clips.append({
                "clip_id": f"clip_{i:02d}",
                "source_id": f"src_channel_{i:02d}",
                "start_s": float(i * 10),
                "end_s": float(i * 10 + 6),
                "duration_s": 6.0,
                "uploader": f"Creator {i:02d}",
                "use_count": 1
            })

        qa_data = {
            "passed": True,  # Fake legacy pass
            "overall_status": "PASSED",
            "duration_contract": {
                "target_duration_s": 60.0,
                "actual_duration_s": 60.0,
                "duration_diff_s": 0.0,
                "allowed_tolerance_s": 1.0,
                "passed": True
            },
            "pet_centering": {"passed_frames": 16, "sampled_frames": 16, "passed": True},
            "sharpness": {"min_sharpness": 300.0, "benchmark_floor": 150.0, "passed": True},
            "watermark_gate": {"passed": True},
            "burned_in_text_gate": {
                "passed": True,
                "skipped": True,
                "reason": "Check skipped: unexpected keyword argument 'is_master_with_captions'"
            },
            "gates": {
                "gate_1_stream_specs": {"passed": True},
                "gate_1b_duration_contract": {"passed": True},
                "gate_1c_clip_count": True,
                "gate_2_audio_loudness": {"passed": True},
                "gate_3_black_frames": {"passed": True},
                "gate_4_pet_centering": {"passed": True},
                "gate_5_freeze_frames": {"passed": True},
                "gate_6_watermark": {"passed": True},
                "gate_6b_clean_overlays": {
                    "passed": True,
                    "skipped": True,
                    "reason": "Check skipped: unexpected keyword argument"
                },
                "gate_7_audio_clipping": {"passed": True},
                "gate_8_motion_pacing": {"passed": True},
                "gate_9_sharpness": {"passed": True}
            }
        }

        job_dir = self._create_mock_job(job_id, qa_data, clips, target_dur=60.0, actual_dur=60.0)
        res = report_generator.generate_job_report(job_id, output_dir=job_dir, work_dir=job_dir)

        with open(res["report_json"], "r", encoding="utf-8") as f:
            data = json.load(f)

        verdict = data["unified_verdict"]
        self.assertEqual(verdict["badge"], "NOT RUN")
        self.assertNotEqual(verdict["badge"], "PASSED")
        self.assertGreater(len(verdict["not_run_gates"]), 0)

        with open(res["report_html"], "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("NOT RUN", html)

        self.assertTrue(res["pdf_success"])
        self.assertTrue(os.path.exists(res["report_pdf"]))


if __name__ == "__main__":
    unittest.main()
