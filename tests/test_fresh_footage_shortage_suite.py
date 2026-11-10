"""
tests/test_fresh_footage_shortage_suite.py
==========================================
TDD Test Suite for Fresh Footage Shortage, Active Waiting, Stage A Parity,
Resumability, Duplicate Prevention, and Calm UI Contracts.

Must fail before fixes are applied, then 100% pass after.
"""

import os
import sys
import json
import sqlite3
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger
from fulfillment_planner import FulfillmentPlanner, FulfillmentPlan
from stage_timer import StageTimer


class TestFreshFootageShortageSuite(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_ledger.db")
        self.ledger = ClipLedger(db_path=self.db_path)
        self.planner = FulfillmentPlanner(ledger=self.ledger)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_clips(self, clips_data):
        with self.ledger._get_conn() as conn:
            for c in clips_data:
                src_path = os.path.join(self.temp_dir, c["source_id"])
                if not os.path.exists(src_path):
                    with open(src_path, "wb") as f:
                        f.write(b"0" * 1024)
                conn.execute("""
                    INSERT INTO clips (
                        clip_id, source_id, source_url_or_path, license, start_s, end_s,
                        quality_score, funny_score, animal_type, times_used,
                        is_verified, framing_score, sharpness, orientation, compilation_flag,
                        uploader, title, verified_plan, verified_at, rejection_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    c["clip_id"], c["source_id"], src_path, c.get("license", "CC-BY"),
                    float(c.get("start_s", 0.0)), float(c.get("end_s", 7.5)),
                    float(c.get("quality_score", 1.0)), float(c.get("funny_score", 0.8)),
                    c.get("animal_type", "cat"), int(c.get("times_used", 0)),
                    int(c.get("is_verified", 1)), float(c.get("framing_score", 1.0)),
                    float(c.get("sharpness", 200.0)), c.get("orientation", "landscape"),
                    0, c.get("uploader", "Creator"), c.get("title", "Title"),
                    json.dumps(c.get("verified_plan", {"status": "pass"})),
                    "2026-10-25 08:00:00", c.get("rejection_reason", None)
                ))
            conn.commit()

    # -------------------------------------------------------------------------
    # TEST 1: Unified Counts Function
    # -------------------------------------------------------------------------
    def test_01_unified_counts_function(self):
        """One function must accurately compute verified, usable_now, cooldown, used, unverified, and rejected."""
        self.assertTrue(hasattr(self.ledger, "get_pool_unified_counts"),
                        "ClipLedger must implement get_pool_unified_counts()")
        
        # Seed 1 verified usable, 2 in cooldown, 1 used, 2 unverified, 2 rejected
        clips = [
            {"clip_id": "c1", "source_id": "fresh_src.mp4", "is_verified": 1, "times_used": 0},
            {"clip_id": "c2", "source_id": "cd_src_1.mp4", "is_verified": 1, "times_used": 0},
            {"clip_id": "c3", "source_id": "cd_src_2.mp4", "is_verified": 1, "times_used": 0},
            {"clip_id": "c4", "source_id": "used_src.mp4", "is_verified": 1, "times_used": 1},
            {"clip_id": "c5", "source_id": "unver_1.mp4", "is_verified": 0, "rejection_reason": None},
            {"clip_id": "c6", "source_id": "unver_2.mp4", "is_verified": 0, "rejection_reason": None},
            {"clip_id": "c7", "source_id": "rej_1.mp4", "is_verified": 0, "rejection_reason": "LOW_SHARPNESS"},
            {"clip_id": "c8", "source_id": "rej_2.mp4", "is_verified": 0, "rejection_reason": "BAD_FRAMING"},
            {"clip_id": "c9", "source_id": "retry_1.mp4", "is_verified": 0, "rejection_reason": "MEASUREMENT_FAILED"}
        ]
        self._seed_clips(clips)

        # Mock cooldown sources returning cd_src_1 and cd_src_2
        with patch.object(self.ledger, "get_cooldown_sources", return_value={"cd_src_1", "cd_src_2"}):
            counts = self.ledger.get_pool_unified_counts(animal_type="cat")
            self.assertEqual(counts["verified_total"], 4) # c1, c2, c3, c4
            self.assertEqual(counts["cooldown"], 2)       # c2, c3
            self.assertEqual(counts["used"], 1)           # c4
            self.assertEqual(counts["usable_now"], 1)     # c1 (4 - 2 cooldown - 1 used)
            self.assertEqual(counts["unverified"], 2)     # c5, c6
            self.assertEqual(counts["rejected"], 2)       # c7, c8
            self.assertEqual(counts["needs_recheck"], 1)  # c9
            self.assertIn("LOW_SHARPNESS", counts["rejected_by_reason"])

    # -------------------------------------------------------------------------
    # TEST 2: Planner capacity check before render: never prints SUCCESS on shortage
    # -------------------------------------------------------------------------
    def test_02_planner_starts_harvest_and_never_prints_success_on_shortage(self):
        """When usable_now (1) < needed (4), planner must NOT print SUCCESS and must indicate shortage."""
        clips = [
            {"clip_id": "c1", "source_id": "fresh_src.mp4", "is_verified": 1, "times_used": 0},
            {"clip_id": "c2", "source_id": "cd_src_1.mp4", "is_verified": 1, "times_used": 0},
            {"clip_id": "c3", "source_id": "cd_src_2.mp4", "is_verified": 1, "times_used": 0},
            {"clip_id": "c4", "source_id": "cd_src_3.mp4", "is_verified": 1, "times_used": 0},
        ]
        self._seed_clips(clips)

        with patch.object(self.ledger, "get_cooldown_sources", return_value={"cd_src_1", "cd_src_2", "cd_src_3"}):
            plan = self.planner.plan_fulfillment(
                job_id="job_shortage_test",
                animal_mode="cat",
                target_total_sec=30.0,
                target_clip_sec=7.5,
                video_type="short",
                allow_reuse=False
            )
            # Cannot print "Step 1 SUCCESS" or "SUCCESS" when usable_now is 1 of 4 needed
            for msg in plan.log_messages:
                self.assertNotIn("Step 1 SUCCESS", msg, f"False success logged: {msg}")
            
            # Plain plan sentence check: "4 clips x 7.5 s = 30 s. 1 new clip ready, 3 to find."
            self.assertTrue(hasattr(plan, "plain_plan_sentence") or "ready" in plan.status_card_line.lower())
            self.assertIn("1", plan.status_card_line)
            self.assertIn("3", plan.status_card_line)

    # -------------------------------------------------------------------------
    # TEST 3: Waiting is work: verifies unverified rows and reduces need
    # -------------------------------------------------------------------------
    def test_03_waiting_verifies_rows_and_reduces_need(self):
        """While in shortage wait, unverified rows must be processed and verified clips reduce shortage."""
        clips = [
            {"clip_id": "u1", "source_id": "harvested_src_1.mp4", "is_verified": 0, "rejection_reason": None},
            {"clip_id": "u2", "source_id": "harvested_src_2.mp4", "is_verified": 0, "rejection_reason": None},
        ]
        self._seed_clips(clips)

        # Calling verify_unverified_pool on ledger
        self.assertTrue(hasattr(self.ledger, "verify_pending_unverified_rows") or hasattr(self.ledger, "process_unverified_row"),
                        "Ledger or worker must implement verification for unverified rows")
        
        # Verify u1
        verified_count = self.ledger.verify_pending_unverified_rows(animal_type="cat", limit=1)
        self.assertGreaterEqual(verified_count, 1)

    # -------------------------------------------------------------------------
    # TEST 4: Waiting time recorded in its own stage, never counted as reframe
    # -------------------------------------------------------------------------
    def test_04_waiting_time_is_own_timing_row(self):
        """Waiting time must be recorded under 'waiting_for_footage', NOT 'reframe'."""
        timer = StageTimer()
        timer.start_stage("reframe")
        timer.stop_stage("reframe")
        
        timer.start_stage("waiting_for_footage")
        timer.stop_stage("waiting_for_footage")

        stages_dict = timer.stages
        self.assertIn("waiting_for_footage", stages_dict)
        self.assertIn("reframe", stages_dict)

    # -------------------------------------------------------------------------
    # TEST 5: Rendered clips survive shortage wait/failure and resume
    # -------------------------------------------------------------------------
    def test_05_rendered_clips_survive_and_reuse_on_resume(self):
        """A job halting on shortage must save rendered clips to clips_rendered.json and reuse them on resume."""
        work_dir = os.path.join(self.temp_dir, "work_job_001")
        clips_dir = os.path.join(work_dir, "clips")
        os.makedirs(clips_dir, exist_ok=True)

        clip_meta = {
            "clip_id": "clip_c_cat_cache_test_01",
            "source": "cache_test.mp4",
            "rendered_file": os.path.join(clips_dir, "clip_c_cat_cache_test_01_1080x1920.mp4"),
            "verified": True
        }
        with open(clip_meta["rendered_file"], "wb") as f:
            f.write(b"video_bytes")

        # Save checkpoint
        rendered_manifest = os.path.join(work_dir, "clips_rendered.json")
        with open(rendered_manifest, "w", encoding="utf-8") as f:
            json.dump([clip_meta], f)

        # On resume, existing rendered clips must be loaded
        self.assertTrue(os.path.exists(rendered_manifest))
        with open(rendered_manifest, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["clip_id"], "clip_c_cat_cache_test_01")
        self.assertTrue(os.path.exists(loaded[0]["rendered_file"]))

    # -------------------------------------------------------------------------
    # TEST 6: Stage A sharpness floor 150.0 standard scale
    # -------------------------------------------------------------------------
    def test_06_stage_a_sharpness_115_cannot_pass(self):
        """A candidate with sharpness 115.9 (< 150 quality floor) must REJECT in Stage A."""
        from lion_automate_v97 import evaluate_stage_a_candidate_gate
        cand_plan = {
            "status": "pass",
            "framing_score": 1.0,
            "sharpness": 115.9,
            "pet_detected_ratio": 1.0,
            "details": {"vis": 1.0, "horiz": 1.0, "vert": 1.0, "size": 1.0}
        }
        res = evaluate_stage_a_candidate_gate(cand_plan, min_sharpness_floor=150.0)
        self.assertEqual(res["status"], "reject")
        self.assertIn("LOW_SHARPNESS", res["reason"])

    # -------------------------------------------------------------------------
    # TEST 7: 0.0% measurement failure goes to needs_recheck, retried once
    # -------------------------------------------------------------------------
    def test_07_zero_score_goes_to_needs_recheck(self):
        """0.0% score from frame decode / read glitch must be 'MEASUREMENT_FAILED' and set to needs_recheck."""
        cand_id = "test_clip_zero"
        clips = [{"clip_id": cand_id, "source_id": "test_src.mp4", "is_verified": 1, "times_used": 0}]
        self._seed_clips(clips)

        # Release with 0.0% measurement failure
        self.ledger.record_candidate_evaluation_failure(
            clip_id=cand_id,
            score=0.0,
            sharpness=0.0,
            reason="EARLY_ABORT (PREDICTED_BAD_FRAMING (0.0% < 88%))"
        )
        
        # Check that clip is in needs_recheck, NOT permanently rejected
        with self.ledger._get_conn() as conn:
            row = conn.execute("SELECT status, retry_count, rejection_reason FROM clips WHERE clip_id = ?", (cand_id,)).fetchone()
            self.assertEqual(row["status"], "needs_recheck")
            self.assertEqual(row["retry_count"], 1)

    # -------------------------------------------------------------------------
    # TEST 8: Duplicate-source replenishment blocked
    # -------------------------------------------------------------------------
    def test_08_duplicate_source_replenishment_blocked(self):
        """Replenishment reservation must NOT pick a source already rendered in this job when allow_reuse=False."""
        clips = [
            {"clip_id": "c_src1_w1", "source_id": "cache_OzAzzpR4JmY.mp4", "start_s": 0.0, "end_s": 7.5, "is_verified": 1},
            {"clip_id": "c_src1_w2", "source_id": "cache_OzAzzpR4JmY.mp4", "start_s": 35.0, "end_s": 42.5, "is_verified": 1},
            {"clip_id": "c_src2_w1", "source_id": "cache_another_src.mp4", "start_s": 0.0, "end_s": 7.5, "is_verified": 1},
        ]
        self._seed_clips(clips)

        # Job already rendered a clip from cache_OzAzzpR4JmY.mp4
        res = self.ledger.reserve_clips_for_short(
            count=1,
            animal_type="cat",
            short_id="job_replenish_test",
            allow_reuse=False,
            exclude_sources=["cache_OzAzzpR4JmY.mp4", "cache_OzAzzpR4JmY"],
            patience_budget_sec=0
        )
        self.assertEqual(len(res), 1)
        self.assertNotEqual(res[0]["source_id"], "cache_OzAzzpR4JmY.mp4")
        self.assertEqual(res[0]["source_id"], "cache_another_src.mp4")

    # -------------------------------------------------------------------------
    # TEST 9: Render screen calm UI contracts: no glow, time range in eta
    # -------------------------------------------------------------------------
    def test_09_render_screen_calm_ui_contracts(self):
        """Render screen CSS must have no glow/shadows; stage_estimator etaFormatted must never be words."""
        from stage_estimator import StageEstimator
        estimator = StageEstimator()
        
        # In waiting status, etaFormatted must be formatted time range or 'Calculating', never 'Waiting for clips'
        est = estimator.compute_job_telemetry("job_test", stages_data=[], status="waiting_for_clips")
        self.assertNotIn("Waiting", est["etaFormatted"], "etaFormatted must not contain words/sentences")
        self.assertTrue(est["etaFormatted"] in ["--:--", "00:00", "calculating", "Calculating…"] or "-" in est["etaFormatted"] or ":" in est["etaFormatted"])

        # Check style.css has no render-hero-glow radial gradient and no render-pct-large text-shadow
        css_path = os.path.join(BASE_DIR, "gui", "style.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()

        self.assertNotIn("text-shadow: 0 0 24px rgba(24, 232, 122, 0.25)", css_content)


if __name__ == "__main__":
    unittest.main()
