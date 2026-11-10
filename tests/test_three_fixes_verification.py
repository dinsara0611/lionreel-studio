import os
import sys
import unittest
import tempfile
import sqlite3
import json
import subprocess
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger, is_same_moment
from qa_check import check_loudness_ebur128
from lion_automate_v97 import master_audio_ebu_r128
import imageio_ffmpeg

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


class TestThreeFixesVerification(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "sandbox_test_ledger.db")
        self.ledger = ClipLedger(db_path=self.db_path)

    def tearDown(self):
        try:
            del self.ledger
            import gc
            gc.collect()
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_is_same_moment_overlap_threshold(self):
        """
        Verify is_same_moment accurately identifies overlapping moments in same video:
        - Different source -> False
        - Same source, 0% overlap -> False
        - Same source, 25% overlap (<= 30%) -> False
        - Same source, 50% overlap (> 30%) -> True
        - Same source, exact duplicate (100%) -> True
        """
        srcA = "raw/cache_video_A.mp4"
        srcB = "raw/cache_video_B.mp4"

        # Different sources
        self.assertFalse(is_same_moment(srcA, 10.0, 17.5, srcB, 10.0, 17.5))

        # Same source, completely disjoint
        self.assertFalse(is_same_moment(srcA, 10.0, 17.5, srcA, 20.0, 27.5))

        # Same source, 25% overlap (window 10-18 = 8s; window 16-24 = 8s; overlap 2s -> 2/8 = 25% <= 30%)
        self.assertFalse(is_same_moment(srcA, 10.0, 18.0, srcA, 16.0, 24.0, overlap_thresh=0.30))

        # Same source, 50% overlap (window 10-18 = 8s; window 14-22 = 8s; overlap 4s -> 4/8 = 50% > 30%)
        self.assertTrue(is_same_moment(srcA, 10.0, 18.0, srcA, 14.0, 22.0, overlap_thresh=0.30))

        # Exact match
        self.assertTrue(is_same_moment(srcA, 10.0, 17.5, srcA, 10.0, 17.5))

    def test_finished_video_windows_tracking_and_6_rules(self):
        """
        Verify SQLite finished_video_windows table population and 6 selection rules.
        """
        # Populate test clips into ledger
        fake_sources = [os.path.join(self.temp_dir.name, f"source_{i:02d}.mp4") for i in range(10)]
        for s in fake_sources:
            with open(s, "wb") as f:
                f.write(b"dummy")

        with self.ledger._get_conn() as conn:
            for s_idx, s_path in enumerate(fake_sources):
                for w_idx in range(5):
                    cid = f"clip_s{s_idx}_w{w_idx}"
                    st = float(w_idx * 20.0)
                    en = st + 7.5
                    conn.execute("""
                        INSERT INTO clips
                        (clip_id, source_id, source_url_or_path, start_s, end_s, quality_score, funny_score, is_verified, times_used)
                        VALUES (?, ?, ?, ?, ?, 0.9, 0.9, 1, 0)
                    """, (cid, f"src_{s_idx}", s_path, st, en))
            conn.commit()

        # Job 1: reserve 4 clips
        job1_clips = self.ledger.reserve_clips_for_short(count=4, animal_type="cat", short_id="job_001")
        self.assertEqual(len(job1_clips), 4)
        self.ledger.commit_short("job_001")

        clip_windows_job1 = [
            {"clip_id": c["clip_id"], "source_id": c["source_id"], "source_path": c["source_url_or_path"],
             "start": c["start_s"], "duration": 7.5}
            for c in job1_clips
        ]
        self.ledger.register_output(
            job_id="job_001",
            output_filename="job_001.mp4",
            sha256="hash_001",
            clip_ids=[c["clip_id"] for c in job1_clips],
            duration_sec=30.0,
            render_time_sec=10.0,
            clip_windows=clip_windows_job1
        )

        # Check finished_video_windows has 4 entries
        with self.ledger._get_conn() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM finished_video_windows WHERE job_id = 'job_001'")
            self.assertEqual(cur.fetchone()[0], 4)

        # Job 2: reserve 4 clips - must NOT reuse windows from Job 1
        job2_clips = self.ledger.reserve_clips_for_short(count=4, animal_type="cat", short_id="job_002")
        self.assertEqual(len(job2_clips), 4)

        # Verify zero overlap with job 1 windows
        job1_cids = {c["clip_id"] for c in job1_clips}
        job2_cids = {c["clip_id"] for c in job2_clips}
        self.assertEqual(len(job1_cids.intersection(job2_cids)), 0)

        for c2 in job2_clips:
            for c1 in job1_clips:
                self.assertFalse(is_same_moment(
                    c2["source_id"], c2["start_s"], c2["end_s"],
                    c1["source_id"], c1["start_s"], c1["end_s"]
                ))

        # Verify Rule 5: max 50% from one source
        src_counts = {}
        for c in job2_clips:
            src_counts[c["source_id"]] = src_counts.get(c["source_id"], 0) + 1
        for s, cnt in src_counts.items():
            self.assertLessEqual(cnt, 2, f"Source {s} exceeded max 50% limit (used {cnt} of 4)")

    def test_audio_mastering_and_qa_gate(self):
        """
        Verify broadcast audio mastering:
        - Decodes to 48kHz stereo PCM
        - 15ms linear edge fades
        - Ducked background music
        - Two-pass loudnorm to -14.0 LUFS with TP=-2.0
        - Gate 3 passes with True Peak <= -1.0 dBTP and Integrated LUFS in [-15.0, -13.0]
        """
        work_dir = os.path.join(self.temp_dir.name, "audio_qa_test")
        os.makedirs(work_dir, exist_ok=True)

        # Generate 2 synthetic test clips (3.0s each with tone)
        clip1 = os.path.join(work_dir, "test_clip1.mp4")
        clip2 = os.path.join(work_dir, "test_clip2.mp4")
        bgm_file = os.path.join(work_dir, "test_bgm.wav")

        # 3s video with 440Hz sine wave audio
        cmd_c1 = [
            FFMPEG_EXE, "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=3.0:r=30",
            "-f", "lavfi", "-i", "sine=f=440:d=3.0",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            clip1
        ]
        subprocess.run(cmd_c1, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

        # 3s video with 880Hz sine wave audio
        cmd_c2 = [
            FFMPEG_EXE, "-y",
            "-f", "lavfi", "-i", "color=c=red:s=1080x1920:d=3.0:r=30",
            "-f", "lavfi", "-i", "sine=f=880:d=3.0",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-ar", "48000", "-ac", "2",
            clip2
        ]
        subprocess.run(cmd_c2, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

        # 10s BGM tone
        cmd_bgm = [
            FFMPEG_EXE, "-y",
            "-f", "lavfi", "-i", "sine=f=220:d=10.0",
            "-ar", "48000", "-ac", "2",
            bgm_file
        ]
        subprocess.run(cmd_bgm, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

        # Concat the 2 clips for in_video
        concat_txt = os.path.join(work_dir, "concat.txt")
        with open(concat_txt, "w") as f:
            f.write(f"file '{os.path.abspath(clip1)}'\nfile '{os.path.abspath(clip2)}'\n")
        raw_video = os.path.join(work_dir, "raw_assembled.mp4")
        cmd_cat = [
            FFMPEG_EXE, "-y",
            "-f", "concat", "-safe", "0", "-i", concat_txt,
            "-c", "copy",
            raw_video
        ]
        subprocess.run(cmd_cat, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

        # Master audio
        mastered_mp4 = os.path.join(work_dir, "mastered_output.mp4")
        success = master_audio_ebu_r128(
            in_video=raw_video,
            out_video=mastered_mp4,
            bgm_path=bgm_file,
            clip_paths=[clip1, clip2],
            work_dir=work_dir,
            job_id="test_qa",
            tp_target=-2.0,
            lufs_target=-14.0
        )
        self.assertTrue(success)
        self.assertTrue(os.path.exists(mastered_mp4))

        # Run Gate 3 QA check
        qa_res = check_loudness_ebur128(mastered_mp4)
        self.assertTrue(qa_res["passed"], f"Audio QA failed: {qa_res}")
        self.assertEqual(qa_res["sample_rate"], 48000)
        self.assertEqual(qa_res["channels"], 2)
        self.assertLessEqual(qa_res["true_peak_dbtp"], -1.0)
        self.assertGreaterEqual(qa_res["integrated_lufs"], -15.0)
        self.assertLessEqual(qa_res["integrated_lufs"], -13.0)
        self.assertLessEqual(qa_res["drift_ms"], 20.0)


if __name__ == "__main__":
    unittest.main()
