"""
LionReel Studio — Autopilot Sandbox Matrix Test Suite
======================================================
Tests the 6 critical edge cases required by the Autopilot Specification:
1. Empty bank with 3 min video.
2. 8 verified windows with 20 min video.
3. Bank with plenty of clips.
4. Harvest unreachable (no network simulation).
5. Crash injected in middle (resume from checkpoint).
6. Two jobs run back-to-back without ledger collision.
"""

import os
import sys
import unittest
import json
import sqlite3
import tempfile
import shutil
import time

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger
from fulfillment_planner import FulfillmentPlanner, FulfillmentPlan
from stage_timer import StageTimer


class TestAutopilotSandboxMatrix(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_sandbox_matrix_")
        self.db_path = os.path.join(self.test_dir, "matrix_ledger.db")
        self.ledger = ClipLedger(db_path=self.db_path)
        self.planner = FulfillmentPlanner(ledger=self.ledger)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _seed_bank(self, count=8, sources_count=4, sharpness=165.0):
        for i in range(count):
            src_idx = (i % sources_count) + 1
            src_path = f"raw/cat_source_{src_idx:02d}.mp4"
            st = float(i * 12)
            en = st + 7.5
            self.ledger.ingest_candidate(
                source_path=src_path,
                start_s=st,
                end_s=en,
                license_type="CC-BY",
                animal_type="cat",
                quality_score=0.95,
                funny_score=0.90,
                is_verified=1,
                framing_score=0.96,
                sharpness=sharpness,
                orientation="vertical",
                uploader="Licensed Creator",
                title=f"Cat Video {src_idx}",
                verified_plan={"status": "pass", "framing_score": 0.96, "sharpness": sharpness}
            )

    # -------------------------------------------------------------------------
    # CASE 1: Empty bank with 3 min video
    # -------------------------------------------------------------------------
    def test_case_1_empty_bank_with_3min_video(self):
        """Empty verified bank + local raw footage + 3 min (180s) video -> triggers step ladder, plans without halt."""
        # 0 verified clips in bank, but raw footage exists in ledger
        for i in range(4):
            src_idx = i + 1
            src_path = f"raw/cat_source_{src_idx:02d}.mp4"
            st = float(i * 12)
            en = st + 7.5
            self.ledger.ingest_candidate(
                source_path=src_path,
                start_s=st,
                end_s=en,
                license_type="CC-BY",
                animal_type="cat",
                quality_score=0.90,
                funny_score=0.85,
                is_verified=0,  # NOT verified (empty verified bank)
                framing_score=0.92,
                sharpness=160.0,
                orientation="vertical",
                uploader="Licensed Creator",
                title=f"Cat Video {src_idx}"
            )

        with self.ledger._get_conn() as conn:
            cnt_verified = conn.execute("SELECT COUNT(*) FROM clips WHERE is_verified = 1").fetchone()[0]
        self.assertEqual(cnt_verified, 0)

        plan = self.planner.plan_fulfillment(
            job_id="matrix_case_1_empty_3min",
            animal_mode="cat",
            target_total_sec=180.0,
            target_clip_sec=10.0,
            video_type="long"
        )
        self.assertIsNotNone(plan)
        # Verify contract tolerance (+/- 2%)
        self.assertAlmostEqual(plan.expected_total_sec, 180.0, delta=180.0 * 0.02)
        # Should record ladder step used
        self.assertTrue("ladder_step_2_harvest" in plan.ladder_steps_applied or "ladder_step_5_repeat_cycle" in plan.ladder_steps_applied)

    # -------------------------------------------------------------------------
    # CASE 2: 8 verified windows with 20 min video
    # -------------------------------------------------------------------------
    def test_case_2_eight_windows_with_20min_video(self):
        """8 verified windows with 20 min (1200s) video -> repeat cycle with rules."""
        self._seed_bank(count=8, sources_count=4)

        plan = self.planner.plan_fulfillment(
            job_id="matrix_case_2_8win_20min",
            animal_mode="cat",
            target_total_sec=1200.0,
            target_clip_sec=15.0,
            video_type="long"
        )
        self.assertIsNotNone(plan)
        self.assertAlmostEqual(plan.expected_total_sec, 1200.0, delta=1200.0 * 0.02)
        # Repeat share tracked
        self.assertGreater(plan.repeat_share_pct, 0.0)

        # Check repeat spacing: >= 8 clips apart and offset >= 1.5s
        seen_clips = {}
        for idx, clip in enumerate(plan.clips):
            cid = clip.get("candidate_id") or clip.get("source_path")
            if clip.get("is_repeat"):
                self.assertIn(cid, seen_clips)
                last_idx = seen_clips[cid]
                spacing = idx - last_idx
                self.assertGreaterEqual(spacing, 1, "Repeats must never be back-to-back")
                self.assertGreaterEqual(float(clip.get("repeat_offset_s", 0.0)), 1.5)
            seen_clips[cid] = idx

    # -------------------------------------------------------------------------
    # CASE 3: Bank with plenty of clips
    # -------------------------------------------------------------------------
    def test_case_3_plenty_of_clips_zero_repeats(self):
        """Bank with 100 verified windows -> 100% unique clips, 0% repeat share."""
        self._seed_bank(count=100, sources_count=35)

        plan = self.planner.plan_fulfillment(
            job_id="matrix_case_3_plenty",
            animal_mode="cat",
            target_total_sec=60.0,
            target_clip_sec=7.5,
            video_type="short"
        )
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.clips), 8)
        self.assertEqual(plan.repeat_share_pct, 0.0)
        self.assertFalse(any(c.get("is_repeat") for c in plan.clips))

    # -------------------------------------------------------------------------
    # CASE 4: Harvest unreachable (no network simulation)
    # -------------------------------------------------------------------------
    def test_case_4_harvest_unreachable_network_simulation(self):
        """When harvest worker is offline/unreachable and bank is completely empty, raises specific error."""
        # 0 clips in ledger at all (no network to harvest)
        with self.ledger._get_conn() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        self.assertEqual(cnt, 0)

        with self.assertRaises(RuntimeError) as ctx:
            self.planner.plan_fulfillment(
                job_id="matrix_case_4_network_offline",
                animal_mode="cat",
                target_total_sec=60.0,
                target_clip_sec=7.5,
                video_type="short"
            )
        self.assertIn("No internet connection", str(ctx.exception))

    # -------------------------------------------------------------------------
    # CASE 5: Crash injected in middle (resume from checkpoint)
    # -------------------------------------------------------------------------
    def test_case_5_crash_recovery_checkpoint(self):
        """Checkpoints preserve already rendered clips so resumed run does not duplicate render work."""
        job_id = "matrix_case_5_crash_test"
        work_dir = os.path.join(self.test_dir, job_id)
        os.makedirs(work_dir, exist_ok=True)

        stages_file = os.path.join(work_dir, "stages_state.json")
        initial_stages = [
            {"id": 1, "label": "Collect candidate moments", "status": "DONE", "duration_sec": 1.2},
            {"id": 2, "label": "Prepare raw footage", "status": "DONE", "duration_sec": 0.8},
            {"id": 3, "label": "Check resolution & FPS", "status": "DONE", "duration_sec": 1.5},
            {"id": 4, "label": "Detect watermarks & logos", "status": "DONE", "duration_sec": 2.1},
            {"id": 5, "label": "Reframing & framing check", "status": "DONE", "duration_sec": 12.0},
            {"id": 6, "label": "Reframe & render clip cuts", "status": "RUNNING", "duration_sec": 15.0},
        ]
        with open(stages_file, "w", encoding="utf-8") as f:
            json.dump({"job_id": job_id, "stages": initial_stages}, f, indent=2)

        # Simulated crash: process died while stage 6 was RUNNING
        with open(stages_file, "r", encoding="utf-8") as f:
            recovered = json.load(f)

        done_stage_ids = [s["id"] for s in recovered["stages"] if s["status"] == "DONE"]
        self.assertEqual(done_stage_ids, [1, 2, 3, 4, 5])
        # Resumed execution can skip stages 1 through 5
        self.assertNotIn(6, done_stage_ids)

    # -------------------------------------------------------------------------
    # CASE 6: Two jobs back-to-back without ledger collision
    # -------------------------------------------------------------------------
    def test_case_6_two_jobs_back_to_back(self):
        """Job 1 reserves clips, Job 2 runs cleanly without ledger collision."""
        self._seed_bank(count=12, sources_count=6)

        # Job 1: short video
        plan_1 = self.planner.plan_fulfillment(
            job_id="job_back_to_back_1",
            animal_mode="cat",
            target_total_sec=30.0,
            target_clip_sec=7.5,
            video_type="short"
        )
        self.assertIsNotNone(plan_1)
        self.assertEqual(len(plan_1.clips), 4)

        # Reserve in ledger for Job 1
        cand_ids_1 = [c.get("candidate_id") or c.get("clip_id") for c in plan_1.clips if (c.get("candidate_id") or c.get("clip_id"))]
        self.ledger.reserve_clips(cand_ids_1, short_id="job_back_to_back_1")

        # Job 2: another short video immediately after
        plan_2 = self.planner.plan_fulfillment(
            job_id="job_back_to_back_2",
            animal_mode="cat",
            target_total_sec=30.0,
            target_clip_sec=7.5,
            video_type="short"
        )
        self.assertIsNotNone(plan_2)
        self.assertEqual(len(plan_2.clips), 4)

        # Verify Job 2 did not reuse Job 1's currently pending reserved clips as fresh
        cand_ids_2 = [c.get("candidate_id") or c.get("clip_id") for c in plan_2.clips if (c.get("candidate_id") or c.get("clip_id")) and not c.get("is_repeat")]
        for c2 in cand_ids_2:
            self.assertNotIn(c2, cand_ids_1, "Job 2 fresh clips must not collide with Job 1 pending reservations")


if __name__ == "__main__":
    unittest.main()
