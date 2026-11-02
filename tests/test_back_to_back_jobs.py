"""
test_back_to_back_jobs.py
==========================
End-to-end integration test verifying back-to-back jobs:
1. Job 1 reserves clips, masters audio to broadcast specs, passes Gate 3 QA,
   and registers output in finished_video_windows.
2. Job 2 reserves clips under the 6 freshness rules, strictly excluding moments from Job 1,
   masters audio to broadcast specs, passes Gate 3 QA, and registers output.
3. Validates:
   - Zero moment overlap (>30%) between Job 1 and Job 2.
   - finished_video_windows correctly populated.
   - Gate 3 Audio QA: 48kHz, stereo, True Peak <= -1.0 dBTP, Integrated LUFS in [-15.0, -13.0], A/V drift <= 20ms.
   - No synthetic rows written to production database.
"""

import os
import sys
import unittest
import tempfile
import subprocess
import gc
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger, is_same_moment
from qa_check import check_loudness_ebur128
from lion_automate_v97 import master_audio_ebu_r128
import imageio_ffmpeg

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


class TestBackToBackJobs(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "sandbox_b2b_ledger.db")
        self.ledger = ClipLedger(db_path=self.db_path)
        self.work_dir = os.path.join(self.temp_dir.name, "work")
        os.makedirs(self.work_dir, exist_ok=True)

    def tearDown(self):
        try:
            del self.ledger
            gc.collect()
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _create_synthetic_clip(self, path, duration=3.0, freq=440, color="blue", sr=44100):
        cmd = [
            FFMPEG_EXE, "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s=1080x1920:d={duration}:r=30",
            "-f", "lavfi", "-i", f"sine=f={freq}:d={duration}",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-ar", str(sr), "-ac", "2",
            path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    def _create_synthetic_bgm(self, path, duration=15.0):
        cmd = [
            FFMPEG_EXE, "-y",
            "-f", "lavfi", "-i", f"sine=f=220:d={duration}",
            "-ar", "48000", "-ac", "2",
            path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    def test_back_to_back_short_jobs_freshness_and_audio_qa(self):
        # 1. Prepare 6 distinct source files with 3 windows each
        source_files = []
        colors = ["red", "green", "blue", "yellow", "magenta", "cyan"]
        for i in range(6):
            s_path = os.path.join(self.work_dir, f"source_{i:02d}.mp4")
            self._create_synthetic_clip(s_path, duration=10.0, freq=300 + i * 100, color=colors[i], sr=48000)
            source_files.append(s_path)

        # Populate sandbox ledger
        with self.ledger._get_conn() as conn:
            for s_idx, s_path in enumerate(source_files):
                for w_idx in range(3):
                    cid = f"clip_s{s_idx}_w{w_idx}"
                    st = float(w_idx * 3.0)
                    en = st + 3.0
                    conn.execute("""
                        INSERT INTO clips
                        (clip_id, source_id, source_url_or_path, start_s, end_s, quality_score, funny_score, is_verified, times_used)
                        VALUES (?, ?, ?, ?, ?, 0.95, 0.90, 1, 0)
                    """, (cid, f"src_{s_idx}", s_path, st, en))
            conn.commit()

        bgm_path = os.path.join(self.work_dir, "bgm.wav")
        self._create_synthetic_bgm(bgm_path, duration=20.0)

        # ------------------------------------------------------------------
        # JOB 1: Reserve 3 clips, assemble, master audio, QA check, register
        # ------------------------------------------------------------------
        job1_id = "job_b2b_001"
        job1_clips = self.ledger.reserve_clips_for_short(count=3, animal_type="cat", short_id=job1_id)
        self.assertEqual(len(job1_clips), 3, "Job 1 should reserve exactly 3 clips")
        self.ledger.commit_short(job1_id)

        # Render / assemble Job 1 video
        job1_work = os.path.join(self.work_dir, job1_id)
        os.makedirs(job1_work, exist_ok=True)
        job1_cut_clips = []
        for idx, c in enumerate(job1_clips):
            cut_p = os.path.join(job1_work, f"cut_{idx}.mp4")
            cmd_cut = [
                FFMPEG_EXE, "-y",
                "-ss", str(c["start_s"]), "-i", c["source_url_or_path"],
                "-t", "3.0",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-ar", "48000", "-ac", "2",
                cut_p
            ]
            subprocess.run(cmd_cut, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
            job1_cut_clips.append(cut_p)

        # Concat clips
        concat_txt1 = os.path.join(job1_work, "concat.txt")
        with open(concat_txt1, "w") as f:
            for p in job1_cut_clips:
                f.write(f"file '{os.path.abspath(p)}'\n")
        raw_v1 = os.path.join(job1_work, "raw.mp4")
        subprocess.run([
            FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt1, "-c", "copy", raw_v1
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

        mastered_v1 = os.path.join(job1_work, f"{job1_id}.mp4")
        ok1 = master_audio_ebu_r128(
            in_video=raw_v1,
            out_video=mastered_v1,
            bgm_path=bgm_path,
            clip_paths=job1_cut_clips,
            work_dir=job1_work,
            job_id=job1_id,
            tp_target=-2.0,
            lufs_target=-14.2
        )
        self.assertTrue(ok1, "Job 1 audio mastering failed")

        # QA Check Job 1
        qa1 = check_loudness_ebur128(mastered_v1)
        self.assertTrue(qa1["passed"], f"Job 1 Gate 3 QA failed: {qa1}")
        self.assertEqual(qa1["sample_rate"], 48000)
        self.assertEqual(qa1["channels"], 2)
        self.assertLessEqual(qa1["true_peak_dbtp"], -1.0)
        self.assertGreaterEqual(round(qa1["integrated_lufs"], 1), -15.0)
        self.assertLessEqual(round(qa1["integrated_lufs"], 1), -13.0)
        self.assertLessEqual(qa1["drift_ms"], 20.0)

        # Register Job 1 output
        clip_windows_1 = [
            {"clip_id": c["clip_id"], "source_id": c["source_id"], "source_path": c["source_url_or_path"],
             "start": c["start_s"], "duration": 3.0}
            for c in job1_clips
        ]
        self.ledger.register_output(
            job_id=job1_id,
            output_filename=f"{job1_id}.mp4",
            sha256="sha_job1_hash",
            clip_ids=[c["clip_id"] for c in job1_clips],
            duration_sec=9.0,
            render_time_sec=15.0,
            clip_windows=clip_windows_1
        )

        # Check finished_video_windows
        with self.ledger._get_conn() as conn:
            cur1 = conn.execute("SELECT COUNT(*) FROM finished_video_windows WHERE job_id = ?", (job1_id,))
            self.assertEqual(cur1.fetchone()[0], 3)

        # ------------------------------------------------------------------
        # JOB 2: Reserve 3 clips, verify freshness vs Job 1, assemble, QA, register
        # ------------------------------------------------------------------
        job2_id = "job_b2b_002"
        job2_clips = self.ledger.reserve_clips_for_short(count=3, animal_type="cat", short_id=job2_id)
        self.assertEqual(len(job2_clips), 3, "Job 2 should reserve exactly 3 clips")
        self.ledger.commit_short(job2_id)

        # STRICT FRESHNESS VERIFICATION
        # 1. No clip ID reused
        cids_1 = {c["clip_id"] for c in job1_clips}
        cids_2 = {c["clip_id"] for c in job2_clips}
        self.assertEqual(len(cids_1.intersection(cids_2)), 0, "Job 2 reused clip IDs from Job 1")

        # 2. No moment overlap (>30%) with any window from Job 1
        for c2 in job2_clips:
            for c1 in job1_clips:
                self.assertFalse(
                    is_same_moment(
                        c2["source_id"], c2["start_s"], c2["end_s"],
                        c1["source_id"], c1["start_s"], c1["end_s"],
                        overlap_thresh=0.30
                    ),
                    f"Job 2 clip {c2['clip_id']} overlapped with Job 1 clip {c1['clip_id']}"
                )

        # Render / assemble Job 2 video
        job2_work = os.path.join(self.work_dir, job2_id)
        os.makedirs(job2_work, exist_ok=True)
        job2_cut_clips = []
        for idx, c in enumerate(job2_clips):
            cut_p = os.path.join(job2_work, f"cut_{idx}.mp4")
            cmd_cut = [
                FFMPEG_EXE, "-y",
                "-ss", str(c["start_s"]), "-i", c["source_url_or_path"],
                "-t", "3.0",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-ar", "48000", "-ac", "2",
                cut_p
            ]
            subprocess.run(cmd_cut, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
            job2_cut_clips.append(cut_p)

        concat_txt2 = os.path.join(job2_work, "concat.txt")
        with open(concat_txt2, "w") as f:
            for p in job2_cut_clips:
                f.write(f"file '{os.path.abspath(p)}'\n")
        raw_v2 = os.path.join(job2_work, "raw.mp4")
        subprocess.run([
            FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt2, "-c", "copy", raw_v2
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

        mastered_v2 = os.path.join(job2_work, f"{job2_id}.mp4")
        ok2 = master_audio_ebu_r128(
            in_video=raw_v2,
            out_video=mastered_v2,
            bgm_path=bgm_path,
            clip_paths=job2_cut_clips,
            work_dir=job2_work,
            job_id=job2_id,
            tp_target=-2.0,
            lufs_target=-14.2
        )
        self.assertTrue(ok2, "Job 2 audio mastering failed")

        # QA Check Job 2
        qa2 = check_loudness_ebur128(mastered_v2)
        self.assertTrue(qa2["passed"], f"Job 2 Gate 3 QA failed: {qa2}")
        self.assertEqual(qa2["sample_rate"], 48000)
        self.assertEqual(qa2["channels"], 2)
        self.assertLessEqual(qa2["true_peak_dbtp"], -1.0)
        self.assertGreaterEqual(round(qa2["integrated_lufs"], 1), -15.0)
        self.assertLessEqual(round(qa2["integrated_lufs"], 1), -13.0)
        self.assertLessEqual(qa2["drift_ms"], 20.0)

        # Register Job 2 output
        clip_windows_2 = [
            {"clip_id": c["clip_id"], "source_id": c["source_id"], "source_path": c["source_url_or_path"],
             "start": c["start_s"], "duration": 3.0}
            for c in job2_clips
        ]
        self.ledger.register_output(
            job_id=job2_id,
            output_filename=f"{job2_id}.mp4",
            sha256="sha_job2_hash",
            clip_ids=[c["clip_id"] for c in job2_clips],
            duration_sec=9.0,
            render_time_sec=15.0,
            clip_windows=clip_windows_2
        )

        # Check finished_video_windows total is now 6
        with self.ledger._get_conn() as conn:
            cur_tot = conn.execute("SELECT COUNT(*) FROM finished_video_windows")
            self.assertEqual(cur_tot.fetchone()[0], 6)


if __name__ == "__main__":
    unittest.main()
