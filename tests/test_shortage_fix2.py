import unittest
import os
import sys
import json
import time
import tempfile
import sqlite3

# Ensure workspace root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import clip_ledger
from clip_ledger import ClipLedger, is_same_moment
import job_options

class TestShortageFix2(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="lionreel_test_sf2_")
        self.db_path = os.path.join(self.test_dir, "test_clip_ledger.db")
        self.ledger = ClipLedger(db_path=self.db_path)

    def tearDown(self):
        import shutil
        try:
            shutil.rmtree(self.test_dir)
        except Exception:
            pass

    def test_01_rejected_window_never_returns_under_any_id_or_length(self):
        """
        Task 5: A window rejected for a real gate value is never offered again,
        keyed by source_id + overlapping time range (>30% overlap).
        """
        # Add a dummy clip that was rejected in window [106.0, 111.0]
        src = "test_cat_source_1.mp4"
        cid_rejected = "c_test_106_111"
        self.ledger.add_clip(
            clip_id=cid_rejected,
            source_id="test_cat_source_1",
            source_url_or_path=src,
            license_name="Creative Commons CC-BY 4.0",
            start_s=106.0,
            end_s=111.0,
            frame_phashes=["1"*64]*5,
            is_verified=0,
            rejection_reason="LOW_SHARPNESS (40.7 < 150.0)"
        )

        # Check if an overlapping window [106.4, 116.4] (>30% overlap) is identified as rejected
        is_rej, reason = self.ledger.is_window_rejected_by_overlap(
            source_id_or_path=src,
            start_s=106.4,
            end_s=116.4,
            overlap_thresh=0.30
        )
        self.assertTrue(is_rej, "Overlapping candidate window must be detected as rejected")
        self.assertIn("LOW_SHARPNESS", reason)

    def test_02_stage_a_equals_render_window(self):
        """
        Task 6: One function builds the window; Stage A and Stage 6 both call it.
        Given plan clip_time 7.5s, window start 106.4, the canonical window must have
        duration exactly 7.5s (106.4 to 113.9), NOT 10.0s for Stage A and 5.2s for render.
        """
        from canonical_window import get_canonical_window
        win = get_canonical_window(source_id="cache_ByH9LuSILxU", start_s=106.4, target_duration=7.5)
        self.assertEqual(win["start_s"], 106.4)
        self.assertEqual(win["end_s"], 113.9)
        self.assertEqual(win["duration"], 7.5)
        self.assertEqual(win["clip_id"], "c_cache_ByH9LuSILxU_1064_1139")

    def test_03_stored_score_remeasured_fresh(self):
        """
        Task 6: Stored bank scores cannot be blindly used as pass results.
        If a stored candidate is evaluated at job start, fresh measurement is enforced.
        """
        from canonical_window import should_remeasure_candidate
        stored_cand = {
            "clip_id": "c_cat_cache_Rr9701_s-Qs_22_27",
            "framing_score": 1.0,
            "sharpness": 200.0,
            "verified_at": "2026-10-15 10:00:00",
            "gate_version": "v1"
        }
        # A stored score older than 24h or different gate version must require fresh remeasurement
        needs_fresh = should_remeasure_candidate(stored_cand, current_gate_version="v97_fix2")
        self.assertTrue(needs_fresh, "Stored candidate must require fresh remeasurement")

    def test_04_prediction_error_tracking(self):
        """
        Task 6: If Stage A (e.g. 453.2) and render (40.7) differ by >15%,
        log prediction error and count it in qa_report.
        """
        from canonical_window import check_prediction_variance
        var_detected, var_pct, note = check_prediction_variance(stage_a_val=453.2, render_val=40.7, tolerance_pct=0.15)
        self.assertTrue(var_detected, "Sharpness difference of 453.2 vs 40.7 (>90% drop) must trigger prediction error")
        self.assertGreater(var_pct, 0.15)

    def test_05_resume_reuses_rendered_clips(self):
        """
        Task 7: Rendered and verified clips of a failed or waiting job stay in
        the job folder and are reused on Resume/Retry.
        """
        from keep_work import get_preserved_rendered_clips
        job_dir = os.path.join(self.test_dir, "test_job_resume")
        os.makedirs(job_dir, exist_ok=True)
        rendered_json = os.path.join(job_dir, "clips_rendered.json")
        with open(rendered_json, "w", encoding="utf-8") as f:
            json.dump({
                "rendered_clips": [
                    {"index": 1, "clip_id": "c1", "file": "c1.mp4", "verified": True},
                    {"index": 2, "clip_id": "c2", "file": "c2.mp4", "verified": True}
                ]
            }, f)
        
        # Create dummy clip files cleanly
        with open(os.path.join(job_dir, "c1.mp4"), "w") as f1:
            f1.write("dummy")
        with open(os.path.join(job_dir, "c2.mp4"), "w") as f2:
            f2.write("dummy")

        preserved = get_preserved_rendered_clips(job_dir, target_clips_count=4)
        self.assertEqual(len(preserved), 2)
        self.assertEqual(preserved[0]["clip_id"], "c1")
        self.assertEqual(preserved[1]["clip_id"], "c2")

    def test_06_bank_growth_enlist_during_wait(self):
        """
        Task 4: When a window becomes verified during a wait, it must be enlisted and
        rendered within 10s. Repeated identical growth messages must be coalesced.
        """
        from bank_enlist import BankGrowthManager
        bgm = BankGrowthManager()
        # Initial bank has 4
        bgm.update_count(4)
        # Bank grows 4 -> 5
        event = bgm.handle_growth(5)
        self.assertTrue(event["should_enlist"], "Growth 4 -> 5 must trigger enlist")
        
        # Second call with 5 (same count) must NOT trigger duplicate enlist
        event_dup = bgm.handle_growth(5)
        self.assertFalse(event_dup["should_enlist"], "Identical count 5 must not re-trigger enlist")

    def test_07_failure_exit_code_and_choices(self):
        """
        Task 9 & 10: No exit code 0 on failure; failure screen provides 4 one-click choices.
        """
        from job_options import get_failure_action_options
        opts = get_failure_action_options(reason_code="SHORTAGE_WAIT_EXCEEDED")
        expected_actions = [
            "find_new_footage_now",
            "resume_when_ready",
            "allow_reuse_old_footage",
            "make_shorter_video"
        ]
        action_ids = [o["id"] for o in opts]
        for ea in expected_actions:
            self.assertIn(ea, action_ids, f"Action {ea} must be offered on shortage failure")

    def test_08_duplicate_log_lines_prevention(self):
        """
        Task 8: Format log lines strictly monotonic without duplicating lines across sequential polling,
        and suppress duplicate engine launch banners or duplicate [SEQ:N] lines.
        """
        from web_server import format_log_lines_monotonic
        raw_lines = [
            "=== Launching LionReel Automation Script (Job: test_j) ===\n",
            "[SEQ:1] [14:16:47] [INFO] Line 1\n",
            "[SEQ:2] [14:16:47] [INFO] Line 2\n",
            "[SEQ:3] [14:16:48] [INFO] Line 3\n"
        ]
        # First poll with req_seq=0
        poll1 = format_log_lines_monotonic(raw_lines, req_seq=0)
        self.assertEqual(len(poll1), 4)
        self.assertEqual(poll1[-1]["seq"], 4)

        # Second poll with req_seq=4 (no new lines) must return 0 lines
        poll2 = format_log_lines_monotonic(raw_lines, req_seq=4)
        self.assertEqual(len(poll2), 0)

        # Evidence F scenario: Duplicate launch banner and duplicate [SEQ:1], [SEQ:2] blocks
        duplicated_raw = [
            "=== Launching LionReel Automation Script (Job: test_j) ===\n",
            "=== Launching LionReel Automation Script (Job: test_j) ===\n",
            "[SEQ:1] [14:16:47] [INFO] Line 1\n",
            "[SEQ:2] [14:16:47] [INFO] Line 2\n",
            "[SEQ:1] [14:16:47] [INFO] Line 1\n",
            "[SEQ:2] [14:16:47] [INFO] Line 2\n",
            "[SEQ:3] [14:16:48] [INFO] Line 3\n"
        ]
        deduped = format_log_lines_monotonic(duplicated_raw, req_seq=0)
        self.assertEqual(len(deduped), 4, "Duplicate banner and duplicate [SEQ:1], [SEQ:2] must be suppressed")
        self.assertEqual([d["seq"] for d in deduped], [1, 2, 3, 4])

    def test_09_harvest_stage_runs_real_work_when_deficit(self):
        """
        Task 2 & 11: Harvest stage must not return in 0.05s when there is a deficit.
        It must execute real work (queries, window cutting, verification).
        """
        from harvest_worker import run_real_harvest_sync
        # Call with mock or dry_run=True to ensure real work logic is traversed
        res = run_real_harvest_sync(animal_mode="cat", target_needed=4, dry_run=True)
        self.assertIn("queries_run", res)
        self.assertIn("windows_verified", res)
        self.assertGreater(res.get("time_taken_s", 0.0), 0.1, "Harvest cannot exit in 0.05s when deficit exists")

    def test_10_bank_filler_starts_below_threshold(self):
        """
        Task 3 & 11: Background bank filler auto-triggers when verified usable windows
        fall below threshold (default 60 for cat, or < 2x target clips needed).
        """
        from clip_bank_filler import check_and_trigger_bank_filler
        # Mock bank having 3 usable windows when 4 needed (2x target = 8, target bank = 60)
        should_fill, reason = check_and_trigger_bank_filler(current_usable=3, target_bank=60, job_needed=4, trigger=False)
        self.assertTrue(should_fill, "Bank filler must trigger when usable (3) < 2x target (8) or < target_bank (60)")
        self.assertIn("deficit", reason.lower())

    def test_11_rejection_from_measurement_failure_needs_recheck(self):
        """
        Task 5 & 11: A rejection from measurement failure goes to 'needs_recheck' (one retry),
        while real gate failure (e.g. low sharpness) stays rejected permanently.
        """
        cid_meas = "c_test_meas_fail"
        self.ledger.add_clip(
            clip_id=cid_meas,
            source_id="test_cat_source_meas",
            source_url_or_path="test_cat_source_meas.mp4",
            license_name="Creative Commons CC-BY 4.0",
            start_s=10.0,
            end_s=15.0,
            frame_phashes=["0"*64]*5,
            is_verified=0
        )
        res = self.ledger.record_candidate_evaluation_failure(cid_meas, score=0.0, sharpness=0.0, reason="MEASUREMENT_FAILED")
        self.assertEqual(res["action"], "needs_recheck", "First measurement failure must route to needs_recheck")
        
        # Second failure must route to rejected
        res2 = self.ledger.record_candidate_evaluation_failure(cid_meas, score=0.0, sharpness=0.0, reason="MEASUREMENT_FAILED")
        self.assertEqual(res2["action"], "rejected", "Second measurement failure must route to rejected")

if __name__ == "__main__":
    unittest.main()
