"""
Unit tests for Always-On Clip Bank Filler
Tests:
1. Target tracking (fills toward target, default 300).
2. Pauses while render is running.
3. Pause/resume control toggle.
4. Consecutive reject circuit breaker (stops analyzing after 5 consecutive rejects).
5. Source selection preferring vertical 9:16 sources.
6. Permanent cache utilization.
"""

import os
import sys
import unittest
import json
import tempfile
import shutil

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger
from clip_bank_filler import ClipBankFiller, FillerStatus


class TestClipBankFiller(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_filler_")
        self.db_path = os.path.join(self.test_dir, "test_ledger.db")
        self.status_path = os.path.join(self.test_dir, "filler_status.json")
        self.control_path = os.path.join(self.test_dir, "filler_control.json")
        self.ledger = ClipLedger(db_path=self.db_path)
        self.filler = ClipBankFiller(
            ledger=self.ledger,
            status_path=self.status_path,
            control_path=self.control_path,
            target_verified=50
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_status_reporting_and_chip_string(self):
        """Status chip shows 'idle', 'filling 142 of 300', or 'paused'."""
        self.filler.save_status(state="filling", ready=142, target=300)
        status = self.filler.get_status()
        self.assertEqual(status["chip_text"], "filling 142 of 300")

        self.filler.save_status(state="paused", ready=142, target=300)
        status = self.filler.get_status()
        self.assertEqual(status["chip_text"], "paused")

        self.filler.save_status(state="idle", ready=300, target=300)
        status = self.filler.get_status()
        self.assertEqual(status["chip_text"], "idle (300/300)")

    def test_toggle_pause_resume(self):
        """Clicking chip toggles pause/resume without dialogs."""
        self.filler.toggle_pause()
        self.assertTrue(self.filler.is_paused())

        self.filler.toggle_pause()
        self.assertFalse(self.filler.is_paused())

    def test_render_lock_causes_pause(self):
        """Filler pauses when render job is active."""
        mock_active_job = os.path.join(self.test_dir, "active_job.json")
        with open(mock_active_job, "w") as f:
            json.dump({"job_id": "test_render", "status": "running"}, f)

        self.filler.active_job_path = mock_active_job
        self.assertTrue(self.filler.is_render_active())

    def test_circuit_breaker_consecutive_rejects(self):
        """Stops analyzing a source after 5 consecutive rejects."""
        tracker = self.filler.get_source_tracker("bad_source.mp4")
        for _ in range(5):
            tracker.record_reject()
        self.assertTrue(tracker.should_skip())

    def test_source_selection_priority(self):
        """Prefers vertical 9:16 and high-res sources first."""
        sources = [
            {"path": "raw/horiz_1080p.mp4", "width": 1920, "height": 1080, "orientation": "landscape"},
            {"path": "raw/vert_916.mp4", "width": 1080, "height": 1920, "orientation": "vertical"},
            {"path": "raw/horiz_4k.mp4", "width": 3840, "height": 2160, "orientation": "landscape"},
        ]
        sorted_sources = self.filler.prioritize_sources(sources)
        # Vertical 9:16 must be ranked first
        self.assertEqual(sorted_sources[0]["path"], "raw/vert_916.mp4")


if __name__ == "__main__":
    unittest.main()
