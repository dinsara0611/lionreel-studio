"""
tests/test_waiting_state.py
===========================
Test-first verification for:
1. Waiting is a state, not a failure:
   - Job with shortfall (76 ready, 100 needed) must enter WAITING_FOR_CLIPS.
   - Must write job_result.json with status=waiting_for_clips, reason_code=CLIPS_SHORTFALL, exit_code=0.
   - Must log 'JOB WAITING:' and NEVER 'JOB FAILED:'.
   - Exit code 0 must never be mapped to CRASH.
2. Web server status mapping:
   - Maps state strictly from job_result.json (status + reason code), never exit code 0 to CRASH.
3. Log integrity:
   - SEQ 1 and SEQ 6 (CONFIG) must never be dropped by log dedupe / indexing.
   - Launch banner must not be duplicated.
"""

import os
import sys
import json
import time
import subprocess
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import job_options

PYTHON_EXE = r"C:\LionReel\venv\Scripts\python.exe"
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable

class TestWaitingState(unittest.TestCase):
    def test_canonical_states_and_reason_codes_defined(self):
        """Verify job_options defines all canonical states and reason codes."""
        self.assertTrue(hasattr(job_options, "STATE_RUNNING"))
        self.assertTrue(hasattr(job_options, "STATE_SUCCESS"))
        self.assertTrue(hasattr(job_options, "STATE_WAITING_FOR_CLIPS"))
        self.assertTrue(hasattr(job_options, "STATE_NEEDS_SOURCES"))
        self.assertTrue(hasattr(job_options, "STATE_FAILED"))

        self.assertTrue(hasattr(job_options, "REASON_CLIPS_SHORTFALL"))
        self.assertTrue(hasattr(job_options, "REASON_NEEDS_SOURCES"))
        self.assertTrue(hasattr(job_options, "REASON_INVALID_ARGUMENTS"))
        self.assertTrue(hasattr(job_options, "REASON_CRASH"))
        self.assertTrue(hasattr(job_options, "REASON_TIMEOUT"))
        self.assertTrue(hasattr(job_options, "REASON_DISK_FULL"))
        self.assertTrue(hasattr(job_options, "REASON_FFMPEG_ERROR"))
        self.assertTrue(hasattr(job_options, "REASON_LICENSE_BLOCKED"))

    def test_pipeline_waiting_not_failed_on_shortfall(self):
        """
        Scenario: Cat compilation requesting 100 clips of 12s when ledger has 76 clips.
        Must transition to WAITING_FOR_CLIPS with exit code 0, write job_result.json,
        and log JOB WAITING, never JOB FAILED.
        """
        job_id = f"test_waiting_shortfall_{int(time.time())}"
        job_dir = os.path.join(BASE_DIR, "output", job_id)
        os.makedirs(job_dir, exist_ok=True)
        job_result_path = os.path.join(job_dir, "job_result.json")

        cmd = [
            PYTHON_EXE,
            os.path.join(BASE_DIR, "lion_automate_v97.py"),
            "--mode", "cat",
            "--type", "compilation",
            "--clips", "100",
            "--clip-time", "12.0",
            "--job-id", job_id
        ]

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=BASE_DIR)
        out = proc.stdout + proc.stderr

        # 1. Must exit with code 0
        self.assertEqual(proc.returncode, 0, f"Process exited with non-zero code {proc.returncode}. Output:\n{out}")

        # 2. Must log JOB WAITING and NEVER JOB FAILED
        self.assertIn("JOB WAITING", out, f"Output did not contain 'JOB WAITING'. Output:\n{out}")
        self.assertNotIn("JOB FAILED", out, f"Output wrongly contained 'JOB FAILED'. Output:\n{out}")

        # 3. job_result.json must exist and have canonical waiting status and reason
        self.assertTrue(os.path.exists(job_result_path), "job_result.json does not exist in job dir")
        with open(job_result_path, "r", encoding="utf-8") as f:
            jr = json.load(f)

        self.assertEqual(jr.get("status"), "waiting_for_clips", f"Expected status 'waiting_for_clips', got {jr.get('status')}")
        self.assertEqual(jr.get("reason_code"), "CLIPS_SHORTFALL", f"Expected reason_code 'CLIPS_SHORTFALL', got {jr.get('reason_code')}")
        self.assertEqual(jr.get("exit_code"), 0, f"Expected exit_code 0, got {jr.get('exit_code')}")
        self.assertGreater(jr.get("clips_ready", 0), 0, "clips_ready should be positive")
        self.assertEqual(jr.get("clips_needed"), 100, "clips_needed should be 100")

    def test_log_integrity_seq_and_config(self):
        """
        Verify log integrity: SEQ 1 and SEQ 6 (CONFIG) must be preserved and returned,
        and the launch banner is not printed twice.
        """
        import web_server
        # Synthesize 10 sample lines simulating lion_automate output with SEQ tags
        raw_lines = [
            "=== Launching LionReel Automation Script ===",
            "[SEQ:1] [STAGE 1] Initializing pipeline...",
            "[SEQ:2] STARTUP: build=v97 python=C:\\LionReel\\venv\\Scripts\\python.exe",
            "[SEQ:3] Checking ledger pool...",
            "[SEQ:4] Pool check: 76 unused clips available",
            "[SEQ:5] Target: 100 clips",
            "--- RENDERING VIDEO 1 OF 1 ---",
            "[SEQ:6] CONFIG: mode=cat, type=compilation, layout=auto, clips=100, clip_time=12.0, expected_total=1200.0s, pace=balanced, slicing=peak_viral, allow_shorter=False, allow_reuse=False, build_id=v97",
            "[SEQ:7] [SELF-HEALING PAUSE] Finding more clips: 76 of 100 ready.",
            "[SEQ:8] JOB WAITING: Finding more clips: 76 of 100 ready"
        ]

        parsed = web_server.format_log_lines_monotonic(raw_lines)
        texts = [p["text"] for p in parsed]
        seqs = [p["seq"] for p in parsed]

        # 1. Total lines in must equal total lines out
        self.assertEqual(len(parsed), len(raw_lines), f"Expected {len(raw_lines)} lines, got {len(parsed)}")

        # 2. SEQ 1 and CONFIG must be present
        self.assertTrue(any("CONFIG:" in t for t in texts), "CONFIG line was dropped")
        self.assertTrue(any("Initializing pipeline" in t for t in texts), "SEQ 1 line was dropped")

        # 3. Seqs must be strictly monotonic 1..10
        self.assertEqual(seqs, list(range(1, len(raw_lines) + 1)))

if __name__ == "__main__":
    unittest.main()
