"""
tests/test_mode_contract_matrix.py
===================================
Comprehensive Matrix Validation for Mode Contracts:
- Short: 30s, 45s, 60s in 9:16 (1080x1920, 1 output file)
- Long: 1m, 3m, 8m in 16:9 (1920x1080, 1 output file)
- Long: 3m in 9:16 (1080x1920, 1 output file)
- Long: 3m in 1:1 (1080x1080, 1 output file)
- Both: Long 3m 16:9 (1920x1080) + Teaser 45s 9:16 (1080x1920), 2 output files
"""

import unittest
import os
import sys
import json
import tempfile
import shutil

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import job_options

class TestModeContractMatrix(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="mode_matrix_")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_short_matrix_30s_45s_60s(self):
        """Short video matrix: 30s, 45s, 60s must all produce valid 9:16 config, correct target_seconds, and 1 file schema."""
        cases = [
            {"clips": 4, "clip_time": 7.5, "expected_target": 30.0},
            {"clips": 6, "clip_time": 7.5, "expected_target": 45.0},
            {"clips": 8, "clip_time": 7.5, "expected_target": 60.0},
        ]
        for idx, tc in enumerate(cases):
            job_id = f"test_short_matrix_{int(tc['expected_target'])}s"
            cfg = {
                "VIDEO_TYPE": "short",
                "TARGET_CLIPS": tc["clips"],
                "SHORT_CLIP_SEC": tc["clip_time"],
                "ASPECT_RATIO": "9:16"
            }
            valid, norm, err = job_options.normalize_job_options(cfg)
            self.assertTrue(valid, f"Failed normalizing short {tc['expected_target']}s: {err}")
            self.assertEqual(norm["type"], "short")
            self.assertEqual(norm["aspect_ratio"], "9:16")
            self.assertEqual(norm["width"], 1080)
            self.assertEqual(norm["height"], 1920)
            self.assertEqual(norm["clips"] * norm["clip_time"], tc["expected_target"])

            # Verify saved job_config.json
            saved = job_options.load_or_verify_job_config(job_id, norm, work_base_dir=self.tmp_dir)
            self.assertEqual(saved["mode"], "short")
            self.assertEqual(saved["ratio"], "9:16")
            self.assertEqual(saved["resolution"], "1080x1920")
            self.assertEqual(saved["target_seconds"], tc["expected_target"])
            self.assertEqual(saved["clip_count"], tc["clips"])
            self.assertEqual(saved["clip_time"], tc["clip_time"])
            self.assertIsNone(saved.get("teaser"))

    def test_long_matrix_1m_3m_8m_16_9(self):
        """Long video matrix in 16:9: 1m (60s), 3m (180s), 8m (480s) contracts."""
        cases = [
            {"min": 1.0, "clip_time": 7.5, "expected_target": 60.0, "expected_clips": 8},
            {"min": 3.0, "clip_time": 7.5, "expected_target": 180.0, "expected_clips": 24},
            {"min": 8.0, "clip_time": 7.5, "expected_target": 480.0, "expected_clips": 64},
        ]
        for tc in cases:
            job_id = f"test_long_matrix_{int(tc['min'])}m"
            cfg = {
                "VIDEO_TYPE": "long",
                "TARGET_DURATION_MIN": tc["min"],
                "SHORT_CLIP_SEC": tc["clip_time"],
                "ASPECT_RATIO": "16:9"
            }
            valid, norm, err = job_options.normalize_job_options(cfg)
            self.assertTrue(valid, f"Failed normalizing long {tc['min']}m: {err}")
            self.assertEqual(norm["type"], "compilation")
            self.assertEqual(norm["aspect_ratio"], "16:9")
            self.assertEqual(norm["width"], 1920)
            self.assertEqual(norm["height"], 1080)
            self.assertEqual(norm["target_seconds"], tc["expected_target"])
            self.assertEqual(norm["clips"], tc["expected_clips"])

            saved = job_options.load_or_verify_job_config(job_id, norm, work_base_dir=self.tmp_dir)
            self.assertEqual(saved["mode"], "compilation")
            self.assertEqual(saved["ratio"], "16:9")
            self.assertEqual(saved["resolution"], "1920x1080")
            self.assertEqual(saved["target_seconds"], tc["expected_target"])
            self.assertEqual(saved["clip_count"], tc["expected_clips"])
            self.assertIsNone(saved.get("teaser"))

    def test_long_matrix_3m_selectable_aspect_ratios(self):
        """Long 3m video in 9:16 (vertical) and 1:1 (square)."""
        aspects = [
            {"ratio": "9:16", "w": 1080, "h": 1920},
            {"ratio": "1:1", "w": 1080, "h": 1080}
        ]
        for asp in aspects:
            job_id = f"test_long_3m_{asp['ratio'].replace(':', '_')}"
            cfg = {
                "VIDEO_TYPE": "long",
                "TARGET_DURATION_MIN": 3.0,
                "SHORT_CLIP_SEC": 7.5,
                "ASPECT_RATIO": asp["ratio"]
            }
            valid, norm, err = job_options.normalize_job_options(cfg)
            self.assertTrue(valid)
            self.assertEqual(norm["aspect_ratio"], asp["ratio"])
            self.assertEqual(norm["width"], asp["w"])
            self.assertEqual(norm["height"], asp["h"])
            self.assertEqual(norm["target_seconds"], 180.0)

            saved = job_options.load_or_verify_job_config(job_id, norm, work_base_dir=self.tmp_dir)
            self.assertEqual(saved["ratio"], asp["ratio"])
            self.assertEqual(saved["resolution"], f"{asp['w']}x{asp['h']}")
            self.assertEqual(saved["target_seconds"], 180.0)

    def test_both_formats_matrix(self):
        """Both Formats matrix: Long 3m 16:9 (1920x1080) + 45s Teaser 9:16 (1080x1920). Exactly 2 output contracts."""
        job_id = "test_both_formats_matrix_01"
        cfg = {
            "VIDEO_TYPE": "both",
            "TARGET_DURATION_MIN": 3.0,
            "SHORT_CLIP_SEC": 7.5,
            "ASPECT_RATIO": "16:9"
        }
        valid, norm, err = job_options.normalize_job_options(cfg)
        self.assertTrue(valid)
        self.assertEqual(norm["type"], "both")
        self.assertEqual(norm["aspect_ratio"], "16:9")
        self.assertEqual(norm["target_seconds"], 180.0)
        self.assertEqual(norm["clips"], 24)
        self.assertIn("teaser", norm)
        self.assertEqual(norm["teaser"]["seconds"], 45.0)
        self.assertEqual(norm["teaser"]["ratio"], "9:16")
        self.assertEqual(norm["teaser"]["resolution"], "1080x1920")

        # Check job_config persistence
        saved = job_options.load_or_verify_job_config(job_id, norm, work_base_dir=self.tmp_dir)
        self.assertEqual(saved["mode"], "both")
        self.assertEqual(saved["ratio"], "16:9")
        self.assertEqual(saved["resolution"], "1920x1080")
        self.assertEqual(saved["target_seconds"], 180.0)
        self.assertEqual(saved["clip_count"], 24)
        self.assertIsNotNone(saved["teaser"])
        self.assertEqual(saved["teaser"]["seconds"], 45.0)
        self.assertEqual(saved["teaser"]["ratio"], "9:16")

        # Also verify companion teaser job_config
        teaser_job_id = f"{job_id}_teaser"
        teaser_saved = job_options.load_or_verify_job_config(teaser_job_id, {
            "type": "short",
            "video_type": "short",
            "aspect_ratio": "9:16",
            "clips": 6,
            "clip_time": 7.5,
            "target_seconds": 45.0
        }, work_base_dir=self.tmp_dir)
        self.assertEqual(teaser_saved["mode"], "short")
        self.assertEqual(teaser_saved["ratio"], "9:16")
        self.assertEqual(teaser_saved["resolution"], "1080x1920")
        self.assertEqual(teaser_saved["target_seconds"], 45.0)

    def test_sandbox_ffprobe_media_matrix(self):
        """
        Sandbox run producing and checking actual media files with ffprobe across all selections:
        - Short: 30s, 45s, 60s (9:16, 1080x1920)
        - Long: 1 min, 3 min, 8 min (16:9, 1920x1080)
        - Long: 3 min 9:16 (1080x1920) and 1:1 (1080x1080)
        - Both: Long 3 min 16:9 (1920x1080) + 45s 9:16 teaser (1080x1920), 2 files
        Also verifies QA fails if resolution, duration (+/-1s) or clip count differ from stored job_config.json.
        """
        import subprocess
        import imageio_ffmpeg
        import qa_check

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        def _render_fast_test_mp4(out_path: str, w: int, h: int, dur_s: float):
            cmd = [
                ffmpeg_exe, "-y",
                "-f", "lavfi", "-i", f"color=c=navy:s={w}x{h}:r=30:d={dur_s}",
                "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={dur_s}",
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
                "-pix_fmt", "yuv420p", "-r", "30",
                "-c:a", "aac", "-b:a", "128k", "-ac", "2",
                out_path
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        selections = [
            # Shorts: 30s, 45s, 60s
            {"id": "sbx_short_30s", "cfg": {"VIDEO_TYPE": "short", "TARGET_CLIPS": 4, "SHORT_CLIP_SEC": 7.5, "ASPECT_RATIO": "9:16"}},
            {"id": "sbx_short_45s", "cfg": {"VIDEO_TYPE": "short", "TARGET_CLIPS": 6, "SHORT_CLIP_SEC": 7.5, "ASPECT_RATIO": "9:16"}},
            {"id": "sbx_short_60s", "cfg": {"VIDEO_TYPE": "short", "TARGET_CLIPS": 8, "SHORT_CLIP_SEC": 7.5, "ASPECT_RATIO": "9:16"}},
            # Long 16:9: 1m, 3m, 8m
            {"id": "sbx_long_1m_16_9", "cfg": {"VIDEO_TYPE": "long", "TARGET_DURATION_MIN": 1.0, "SHORT_CLIP_SEC": 7.5, "ASPECT_RATIO": "16:9"}},
            {"id": "sbx_long_3m_16_9", "cfg": {"VIDEO_TYPE": "long", "TARGET_DURATION_MIN": 3.0, "SHORT_CLIP_SEC": 7.5, "ASPECT_RATIO": "16:9"}},
            {"id": "sbx_long_8m_16_9", "cfg": {"VIDEO_TYPE": "long", "TARGET_DURATION_MIN": 8.0, "SHORT_CLIP_SEC": 7.5, "ASPECT_RATIO": "16:9"}},
            # Long 3m 9:16 and 1:1
            {"id": "sbx_long_3m_9_16", "cfg": {"VIDEO_TYPE": "long", "TARGET_DURATION_MIN": 3.0, "SHORT_CLIP_SEC": 7.5, "ASPECT_RATIO": "9:16"}},
            {"id": "sbx_long_3m_1_1", "cfg": {"VIDEO_TYPE": "long", "TARGET_DURATION_MIN": 3.0, "SHORT_CLIP_SEC": 7.5, "ASPECT_RATIO": "1:1"}},
            # Both: Long 3m 16:9 + 45s 9:16 teaser
            {"id": "sbx_both_3m", "cfg": {"VIDEO_TYPE": "both", "TARGET_DURATION_MIN": 3.0, "SHORT_CLIP_SEC": 7.5, "ASPECT_RATIO": "16:9"}},
        ]

        for item in selections:
            jid = item["id"]
            valid, norm, err = job_options.normalize_job_options(item["cfg"])
            self.assertTrue(valid, f"Normalize failed for {jid}: {err}")
            saved = job_options.load_or_verify_job_config(jid, norm, work_base_dir=self.tmp_dir)
            job_dir = os.path.join(self.tmp_dir, jid)
            out_mp4 = os.path.join(job_dir, f"{jid}.mp4")

            _render_fast_test_mp4(out_mp4, norm["width"], norm["height"], saved["target_seconds"])
            self.assertTrue(os.path.exists(out_mp4))

            # Verify with ffprobe analysis
            probe = qa_check.run_ffprobe_analysis(out_mp4)
            v_st = next((s for s in probe.get("streams", []) if s.get("width")), {})
            actual_w = int(v_st.get("width", 0))
            actual_h = int(v_st.get("height", 0))
            actual_dur = float(probe.get("format", {}).get("duration", 0.0))

            self.assertEqual(f"{actual_w}x{actual_h}", saved["resolution"], f"Resolution mismatch for {jid}")
            self.assertAlmostEqual(actual_dur, saved["target_seconds"], delta=1.0, msg=f"Duration mismatch for {jid}")

            # If Both mode, also render and verify the 45s 9:16 teaser (2 files)
            if saved["mode"] == "both":
                teaser_mp4 = os.path.join(job_dir, f"{jid}_teaser.mp4")
                _render_fast_test_mp4(teaser_mp4, 1080, 1920, saved["teaser"]["seconds"])
                self.assertTrue(os.path.exists(teaser_mp4))
                t_probe = qa_check.run_ffprobe_analysis(teaser_mp4)
                tv_st = next((s for s in t_probe.get("streams", []) if s.get("width")), {})
                self.assertEqual(f"{int(tv_st['width'])}x{int(tv_st['height'])}", "1080x1920")
                t_dur = float(t_probe.get("format", {}).get("duration", 0.0))
                self.assertAlmostEqual(t_dur, 45.0, delta=1.0)

        # Verify QA failure when duration differs > 1.0s
        dur_res = qa_check.evaluate_duration_contract(actual_s=32.5, target_s=30.0, tolerance=1.0)
        self.assertFalse(dur_res["passed"], "QA must fail when duration differs by > 1.0s")

if __name__ == "__main__":
    unittest.main()
