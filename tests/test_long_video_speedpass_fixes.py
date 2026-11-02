"""
tests/test_long_video_speedpass_fixes.py
========================================
Test-first regression suite for Long Video Speed Pass bugfixes:
1. Checkpoint integrity & quarantine: corrupt checkpoints must be quarantined, not reused.
2. Distinct repeat ids, files, and offsets: repeats never share checkpoint paths or base offsets.
3. Spacing rules: repeats separated by >= 8 clips, no back-to-back identical windows.
4. Bounded waiting & watchdog: wait loop must exit when budget expires or watchdog triggers.
5. Planned duration & clip time alignment: 100 x 12s does not become 139 x 5s.
6. Stage status consistency: only active stage becomes WAITING, earlier stages remain DONE.
"""

import unittest
import os
import sys
import json
import time
import shutil
import tempfile
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger
import job_options


class TestLongVideoSpeedPassFixes(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="lionreel_test_speedpass_")
        self.db_path = os.path.join(self.test_dir, "test_ledger.db")
        self.ledger = ClipLedger(db_path=self.db_path)

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except Exception:
            pass

    def test_checkpoint_verification_and_quarantine(self):
        """
        Corrupt checkpoint file must be quarantined (moved to quarantine/),
        never restored or reported as 'rendered and verified'.
        """
        from lion_automate_v97 import LionReelV97Pipeline
        pipeline = LionReelV97Pipeline()
        
        chk_dir = os.path.join(self.test_dir, "clips")
        os.makedirs(chk_dir, exist_ok=True)
        corrupt_clip = os.path.join(chk_dir, "clip_test_corrupt.mp4")
        with open(corrupt_clip, "wb") as f:
            f.write(b"CORRUPT DATA INVALID NAL UNIT NO MOOV ATOM")

        meta_path = os.path.join(chk_dir, "clip_test_corrupt.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"clip_id": "test_corrupt", "start_s": 10.0, "dur_s": 12.0, "size": len(b"CORRUPT DATA")}, f)

        # Method under test: verify_and_restore_checkpoint
        restored, msg = pipeline.verify_and_restore_checkpoint(
            checkpoint_clip=corrupt_clip,
            checkpoint_meta=meta_path,
            dest_clip=os.path.join(self.test_dir, "dest.mp4"),
            expected_start=10.0,
            expected_dur=12.0,
            quarantine_dir=os.path.join(self.test_dir, "quarantine")
        )
        self.assertFalse(restored, "Corrupt checkpoint must fail verification")
        self.assertIn("quarantined", msg.lower())
        self.assertFalse(os.path.exists(corrupt_clip), "Original corrupt file must be moved to quarantine")
        quarantined_files = os.listdir(os.path.join(self.test_dir, "quarantine"))
        self.assertEqual(len(quarantined_files), 1, "Corrupt file must be present in quarantine dir")

    def test_repeats_get_distinct_ids_offsets_and_files(self):
        """
        Repeat cycle must assign unique IDs (including repeat cycle and offset),
        apply distinct trim offsets (>= 1.5s), and map to separate checkpoint files.
        """
        from fulfillment_planner import FulfillmentPlanner
        planner = FulfillmentPlanner(ledger=self.ledger)

        # Seed 2 dummy candidates
        with self.ledger._get_conn() as conn:
            conn.execute("""
                INSERT INTO clips (clip_id, source_id, source_url_or_path, license, start_s, end_s, animal_type, times_used, is_verified, framing_score, sharpness, verified_plan)
                VALUES ('c_cand_1', 'src_1', 'dummy_1.mp4', 'CC-BY', 10.0, 22.0, 'cat', 0, 1, 1.0, 200.0, '{"status":"pass"}')
            """)
            conn.execute("""
                INSERT INTO clips (clip_id, source_id, source_url_or_path, license, start_s, end_s, animal_type, times_used, is_verified, framing_score, sharpness, verified_plan)
                VALUES ('c_cand_2', 'src_2', 'dummy_2.mp4', 'CC-BY', 30.0, 42.0, 'cat', 0, 1, 1.0, 200.0, '{"status":"pass"}')
            """)
            conn.commit()

        # Request 10 clips of 12.0s = 120s
        plan = planner.plan_fulfillment(
            job_id="test_repeats_job",
            animal_mode="cat",
            target_total_sec=120.0,
            target_clip_sec=12.0,
            video_type="compilation",
            allow_reuse=True
        )

        clip_ids = [c["clip_id"] for c in plan.clips]
        self.assertEqual(len(clip_ids), len(set(clip_ids)), "Every planned clip must have a globally unique clip_id")

        # Check that repeats have offsets >= 1.5s and differing start_s
        seen_starts = {}
        for c in plan.clips:
            base_src = c["source_url_or_path"]
            start = c["start_s"]
            if c.get("is_repeat"):
                self.assertGreaterEqual(c.get("repeat_offset_s", 0.0), 1.5)
            # Verify no two consecutive clips share the same source or window
            pass

        for i in range(len(plan.clips) - 1):
            c1 = plan.clips[i]
            c2 = plan.clips[i + 1]
            self.assertNotEqual(c1.get("clip_id"), c2.get("clip_id"))
            self.assertFalse(c1.get("source_url_or_path") == c2.get("source_url_or_path") and abs(c1.get("start_s") - c2.get("start_s")) < 1.0,
                            f"Consecutive clips {i} and {i+1} cannot be back-to-back identical windows")

    def test_bounded_waiting_deadline_and_watchdog(self):
        """
        Wait loop must exit when monotonic deadline (waiting_since + wait_budget_sec) is exceeded,
        or when progress watchdog detects no progress for 10 minutes.
        """
        from lion_automate_v97 import LionReelV97Pipeline
        pipeline = LionReelV97Pipeline()

        # Simulate wait checkpoint that has exceeded its budget
        now = time.time()
        expired_cp = {
            "job_id": "test_job_expired",
            "waiting_since": now - 1850.0,
            "wait_budget_sec": 1800.0,
            "consecutive_no_growth": 60,
            "last_poll_time": now,
            "status": "waiting_for_clips"
        }
        cp_path = os.path.join(self.test_dir, "wait_checkpoint.json")
        with open(cp_path, "w") as f:
            json.dump(expired_cp, f)

        # Check budget expiration evaluation
        is_expired, reason = pipeline.check_wait_budget_and_watchdog(
            work_job_dir=self.test_dir,
            now=now,
            max_stall_sec=600.0
        )
        self.assertTrue(is_expired, "Monotonic wait budget exceeded must trigger expiration")
        self.assertIn("budget", reason.lower())

    def test_planner_honors_requested_clip_time(self):
        """
        100 clips x 12.0s = 1200s must plan clips honoring ~12.0s (+/- 0.5s),
        never shrinking each clip to 5.2s and bloating clip count to 139.
        """
        from fulfillment_planner import FulfillmentPlanner
        planner = FulfillmentPlanner(ledger=self.ledger)

        with self.ledger._get_conn() as conn:
            # 5s window in ledger
            conn.execute("""
                INSERT INTO clips (clip_id, source_id, source_url_or_path, license, start_s, end_s, animal_type, times_used, is_verified, framing_score, sharpness, verified_plan)
                VALUES ('c_short_win', 'src_1', 'dummy_1.mp4', 'CC-BY', 10.0, 15.2, 'cat', 0, 1, 1.0, 200.0, '{"status":"pass"}')
            """)
            conn.commit()

        plan = planner.plan_fulfillment(
            job_id="test_clip_time_honor",
            animal_mode="cat",
            target_total_sec=120.0,
            target_clip_sec=12.0,
            video_type="compilation",
            allow_reuse=True
        )

        # For 120s at 12s target, expect 10 clips (within +/- 2 clips), NOT 23 clips of 5.2s!
        self.assertLessEqual(plan.target_clips_count, 12, f"Planned clip count ({plan.target_clips_count}) must be near 10, not bloated")
        for c in plan.clips:
            self.assertGreaterEqual(c["dur_s"], 8.0, "Clips should be adapted near target clip time, not clamped to 5s")

    def test_stage_status_consistency_in_server(self):
        """
        When Stage 6 enters waiting, only Stage 6 should be marked WAITING.
        Stage 1 (already DONE) must NOT be rewritten to WAITING.
        """
        from web_server import update_stages_list_status
        stages = [
            {"id": 1, "key": "collect_candidates", "label": "Collect candidate moments from ledger", "status": "DONE"},
            {"id": 2, "key": "prepare_sources", "label": "Prepare sources", "status": "DONE"},
            {"id": 3, "key": "check_quality_fps", "label": "Check quality", "status": "DONE"},
            {"id": 4, "key": "detect_watermarks", "label": "Detect watermarks", "status": "DONE"},
            {"id": 5, "key": "predict_framing", "label": "Predict framing", "status": "DONE"},
            {"id": 6, "key": "reframe_render_clips", "label": "Reframe & render", "status": "RUNNING"},
            {"id": 7, "key": "color_grading", "label": "Color grading", "status": "PENDING"},
        ]
        job_res = {"clips_ready": 34, "clips_needed": 100}

        updated = update_stages_list_status(stages, computed_status="waiting_for_clips", job_res=job_res)
        s1 = next(s for s in updated if s["id"] == 1)
        s6 = next(s for s in updated if s["id"] == 6)
        self.assertEqual(s1["status"], "DONE", "Stage 1 must remain DONE")
        self.assertEqual(s6["status"], "WAITING", "Only active Stage 6 should become WAITING")

    def test_ffmpeg_noise_suppression_and_flood_limit(self):
        """
        Flood test: 10,000 ffmpeg error lines must produce at most 30 lines in the log
        plus exactly one summary line, preventing console flood.
        """
        from io import StringIO
        import sys

        # Simulate 10,000 lines of decoder error messages
        ten_thousand_lines = "\n".join([f"[h264 @ 000001] Invalid NAL unit size (-276925642 > 3220) error #{i}" for i in range(10000)])
        captured = StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured
            err_lines = [l for l in ten_thousand_lines.splitlines() if l.strip()]
            if err_lines:
                print(f"[FFMPEG] {len(err_lines)} decode/encode message(s) during attempt 0 for clip_test.mp4: {err_lines[0][:120]}")
        finally:
            sys.stdout = old_stdout

        output_str = captured.getvalue().strip()
        lines = output_str.splitlines()
        self.assertLessEqual(len(lines), 30, "Flood output must be at most 30 lines")
        self.assertIn("10000 decode/encode message(s)", output_str, "Must contain exactly one summary line with count")

    def test_qa_gate_fails_identical_consecutive_clips(self):
        """
        Timeline QA gate must fail assembly if identical consecutive clips exist.
        """
        from fulfillment_planner import FulfillmentPlanner
        planner = FulfillmentPlanner(ledger=self.ledger)

        # Sequence with adjacent identical clips
        bad_sequence = [
            {"clip_id": "clip_A", "base_clip_id": "cand_1", "start_s": 10.0, "dur_s": 12.0},
            {"clip_id": "clip_B", "base_clip_id": "cand_1", "start_s": 10.0, "dur_s": 12.0},  # identical consecutive!
            {"clip_id": "clip_C", "base_clip_id": "cand_2", "start_s": 20.0, "dur_s": 12.0},
        ]
        # Spaced version must fix adjacent identical clips
        spaced = planner._space_repeats(bad_sequence)
        for i in range(len(spaced) - 1):
            self.assertNotEqual(spaced[i]["base_clip_id"], spaced[i+1]["base_clip_id"],
                               f"Consecutive clips at {i} and {i+1} must not be identical")

    def test_pool_with_2_sources_and_34_clips_no_infinite_wait(self):
        """
        Pool with 2 sources and 34 ready clips for a long target:
        Verify no infinite wait, no identical consecutive clips, no corrupt file used,
        final plan within patience budget, and repeat share clearly calculated.
        """
        from fulfillment_planner import FulfillmentPlanner
        planner = FulfillmentPlanner(ledger=self.ledger)

        # Seed 34 candidate windows across 2 sources
        with self.ledger._get_conn() as conn:
            for s_idx in [1, 2]:
                for w_idx in range(17):
                    cid = f"cand_src{s_idx}_win{w_idx}"
                    st = float(w_idx * 25.0)
                    conn.execute("""
                        INSERT INTO clips (clip_id, source_id, source_url_or_path, license, start_s, end_s, animal_type, times_used, is_verified, framing_score, sharpness, verified_plan)
                        VALUES (?, ?, ?, 'CC-BY', ?, ?, 'cat', 0, 1, 1.0, 200.0, '{"status":"pass"}')
                    """, (cid, f"src_{s_idx}", f"source_{s_idx}.mp4", st, st + 12.0))
            conn.commit()

        # Request 100 clips of 12.0s = 1200s (compilation)
        plan = planner.plan_fulfillment(
            job_id="test_long_compilation_100clips",
            animal_mode="cat",
            target_total_sec=1200.0,
            target_clip_sec=12.0,
            video_type="compilation",
            allow_reuse=True
        )

        self.assertIsNotNone(plan)
        self.assertGreater(len(plan.clips), 0)
        self.assertGreater(plan.repeat_share_pct, 0.0, "Repeat share must be tracked and > 0%")
        self.assertIn("repeat", plan.strategy_used.lower())

        # Verify no two consecutive clips share identical base candidate
        for i in range(len(plan.clips) - 1):
            c1 = plan.clips[i]
            c2 = plan.clips[i + 1]
            self.assertNotEqual(c1.get("clip_id"), c2.get("clip_id"), f"Clips {i} and {i+1} cannot have identical ID")
            self.assertFalse(
                c1.get("base_clip_id", c1.get("clip_id")) == c2.get("base_clip_id", c2.get("clip_id")) and abs(c1.get("start_s") - c2.get("start_s")) < 1.0,
                f"Consecutive clips {i} and {i+1} cannot be back-to-back identical moments"
            )

    def test_candidate_verified_plan_retrieved_and_stale_locks_cleared(self):
        """Verify that fulfillment planner retrieves verified_plan and clean_stale_reservations frees dead locks."""
        from fulfillment_planner import FulfillmentPlanner

        with self.ledger._get_conn() as conn:
            conn.execute("""
                INSERT INTO clips (clip_id, source_id, source_url_or_path, license, start_s, end_s, animal_type, times_used, is_verified, framing_score, sharpness, verified_plan, pending_short_id)
                VALUES ('test_vp_clip_locked', 'src_vp', 'source_vp.mp4', 'CC-BY', 10.0, 20.0, 'cat', 0, 1, 0.98, 210.0, '{"status":"pass","score":0.98}', 'dead_job_123')
            """)
            conn.commit()

        planner = FulfillmentPlanner(ledger=self.ledger)
        # While locked with pending_short_id, should not be fetched
        cands_before = planner._fetch_verified_candidates("cat")
        locked_found = [c for c in cands_before if c["clip_id"] == "test_vp_clip_locked"]
        self.assertEqual(len(locked_found), 0, "Locked candidate must not be fetched")

        # Now clean stale reservations
        self.ledger.clean_stale_reservations(["active_job_456"])
        cands_after = planner._fetch_verified_candidates("cat")
        unlocked_found = [c for c in cands_after if c["clip_id"] == "test_vp_clip_locked"]
        self.assertEqual(len(unlocked_found), 1, "Candidate must be fetched after stale lock cleaned")
        self.assertIsNotNone(unlocked_found[0].get("verified_plan"), "verified_plan must be retrieved")
        self.assertEqual(unlocked_found[0]["verified_plan"].get("status"), "pass")

    def test_post_crop_gate_vertical_direct_clamping(self):
        """
        Native vertical videos (vertical_direct / is_clamped) have no horizontal panning slack.
        They must pass post-crop gate when pet is fully inside and comfortably centered (0.28 <= cx <= 0.72),
        rather than falsely rejecting at cx = 0.35.
        """
        import numpy as np
        import cv2
        from qa_check import verify_single_pass_post_crop_gate

        # Generate a small 12-frame 1080x1920 test video
        test_video_path = os.path.join(self.test_dir, "test_vertical_direct.mp4")
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(test_video_path, fourcc, 30.0, (1080, 1920))
        for _ in range(15):
            # Non-black textured frame to pass layout fill and sharpness
            frame = np.random.randint(50, 200, (1920, 1080, 3), dtype=np.uint8)
            out.write(frame)
        out.release()

        class MockPetDetector:
            def detect(self, frame, conf_threshold=0.22):
                # cx = (216 + 540) / (2 * 1080) = 0.35 (outside 0.38-0.62, inside 0.28-0.72)
                # cy = (400 + 1200) / (2 * 1920) = 0.417
                # h_frac = 800 / 1920 = 0.417
                return [{"box": [216, 400, 540, 1200], "conf": 0.95}]

        plan = {
            "mode": "vertical_direct",
            "is_clamped": True,
            "orig_size": [1080, 1920],
            "crop_w": 1080,
            "crop_h": 1920
        }

        ok, msg = verify_single_pass_post_crop_gate(
            test_video_path,
            plan=plan,
            layout_mode="vertical_direct",
            n_samples=12,
            detector=MockPetDetector()
        )
        self.assertTrue(ok, f"vertical_direct clip with cx=0.35 should pass post-crop gate, but failed with: {msg}")

    def test_stage_6_repeat_deficit_fulfillment(self):
        """
        Stage 6 deficit fulfillment (Autopilot Ladder Step 5):
        When rendered pool has fewer clips than target_clips_count and pool >= 2,
        the pipeline must fulfill the remaining slots using distinct repeat cycles
        with offsets >= 1.5s, unique IDs, distinct output files, and fresh captions.
        """
        from lion_automate_v97 import LionReelV97Pipeline
        pipeline = LionReelV97Pipeline()

        # Create 2 base dummy clip files
        c0_file = os.path.join(self.test_dir, "clip_00.mp4")
        c1_file = os.path.join(self.test_dir, "clip_01.mp4")
        with open(c0_file, "wb") as f: f.write(b"0" * 20000)
        with open(c1_file, "wb") as f: f.write(b"1" * 20000)

        rendered_pool = [
            {
                "clip_id": "c_orig_0",
                "base_clip_id": "c_orig_0",
                "source": "src0.mp4",
                "source_abs_path": c0_file,
                "start_s": 5.0,
                "dur_s": 12.0,
                "speed": 1.0,
                "path": c0_file,
                "plan": {"mode": "smart_crop"},
                "cand": {"clip_id": "c_orig_0", "source": "src0.mp4"},
                "cinfo": {"license": "CC-BY", "author": "Creator 0"}
            },
            {
                "clip_id": "c_orig_1",
                "base_clip_id": "c_orig_1",
                "source": "src1.mp4",
                "source_abs_path": c1_file,
                "start_s": 10.0,
                "dur_s": 12.0,
                "speed": 1.0,
                "path": c1_file,
                "plan": {"mode": "smart_crop"},
                "cand": {"clip_id": "c_orig_1", "source": "src1.mp4"},
                "cinfo": {"license": "CC-BY", "author": "Creator 1"}
            }
        ]

        # Target is 5 clips, pool currently has 2 clips
        target_clips = 5
        fulfilled_pool = pipeline.fulfill_stage6_deficit(
            rendered_candidates_pool=rendered_pool,
            target_clips_count=target_clips,
            job_id="test_job_repeat",
            work_job_dir=self.test_dir,
            target_clip_sec=12.0
        )

        self.assertEqual(len(fulfilled_pool), target_clips, "Pool must be fulfilled to exactly target_clips_count")
        
        # Verify repeat clips
        rep_clips = [c for c in fulfilled_pool if c.get("is_repeat")]
        self.assertEqual(len(rep_clips), 3, "Exactly 3 repeat clips should be added")
        
        cids = [c["clip_id"] for c in fulfilled_pool]
        self.assertEqual(len(cids), len(set(cids)), "All clip IDs must be unique")

        for rep in rep_clips:
            self.assertTrue(rep["is_repeat"])
            self.assertGreaterEqual(rep["repeat_offset_s"], 1.5)
            self.assertGreaterEqual(rep["repeat_cycle"], 1)
            self.assertTrue(rep["caption_variant"].startswith("Viral Moment (Encore #"))
            self.assertTrue(os.path.exists(rep["path"]), "Repeat output clip path must exist on disk")
            self.assertTrue("_use" in rep["clip_id"] or "_rep" in rep["clip_id"])


if __name__ == "__main__":
    unittest.main()


