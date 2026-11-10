"""
tests/test_fix11_loop_and_harvest.py
====================================
Test-first verification for:
1. One job = One immutable config (work/<job_id>/job_config.json) + PID lock file
2. One-shot [USER ACTION] consumption (cannot replay on restart)
3. Stage A caching of ALL results (including REJECTs)
4. Timing table shares match time column against wall clock total
5. Preflight capacity calculation: min(verified_windows, usable_sources * 3)
6. Harvest status schema (/api/harvest/status)
7. Fast 12-frame post-crop gate with matching measurement
"""

import os
import sys
import json
import time
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

class TestFix11LoopAndHarvest(unittest.TestCase):

    def test_job_config_immutability_and_mismatch_rejection(self):
        """
        Requirement 2:
        - At creation, write work/<job_id>/job_config.json.
        - Engine reads ONLY this file, never shared files.
        - A relaunch of the same job id with different settings is rejected.
        """
        import job_options
        test_job_id = f"sandbox_cfg_test_{int(time.time()*1000)}"
        work_dir = os.path.join(BASE_DIR, "work", test_job_id)
        os.makedirs(work_dir, exist_ok=True)
        cfg_path = os.path.join(work_dir, "job_config.json")

        initial_cfg = {
            "job_id": test_job_id,
            "type": "compilation",
            "mode": "cat",
            "clips": 25,
            "clip_time": 12.0,
            "layout": "smart_crop",
            "created_at": time.time()
        }
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(initial_cfg, f)

        # 1. Matching config load succeeds
        loaded = job_options.load_or_verify_job_config(test_job_id, initial_cfg)
        self.assertEqual(loaded["clips"], 25)
        self.assertEqual(loaded["type"], "compilation")

        # 2. Conflicting config (e.g. 100 clips, short) must be rejected
        conflicting_cfg = {
            "job_id": test_job_id,
            "type": "short",
            "mode": "cat",
            "clips": 100,
            "clip_time": 12.0,
            "layout": "smart_crop"
        }
        with self.assertRaises(ValueError) as ctx:
            job_options.load_or_verify_job_config(test_job_id, conflicting_cfg)
        self.assertIn("rejected", str(ctx.exception).lower())

        # Cleanup
        try:
            import shutil
            shutil.rmtree(work_dir)
        except Exception:
            pass

    def test_one_process_per_job_lock(self):
        """
        Requirement 2: One process per job via lock file with pid.
        Second launch of same job id exits immediately.
        """
        import job_options
        test_job_id = f"sandbox_lock_test_{int(time.time()*1000)}"
        work_dir = os.path.join(BASE_DIR, "work", test_job_id)
        os.makedirs(work_dir, exist_ok=True)

        lock_acquired = job_options.acquire_job_lock(test_job_id, os.getpid())
        self.assertTrue(lock_acquired)

        # Re-entrant acquire from the same PID must succeed (pipeline re-checking lock inside render_video)
        reentrant_acquired = job_options.acquire_job_lock(test_job_id, os.getpid())
        self.assertTrue(reentrant_acquired, "Re-entrant lock acquisition from same PID must succeed")

        # Attempt to acquire lock from another PID (or simulate another process)
        second_acquired = job_options.acquire_job_lock(test_job_id, os.getpid() + 9999)
        self.assertFalse(second_acquired, "Second launch of same job id must fail lock acquisition")

        job_options.release_job_lock(test_job_id)
        try:
            import shutil
            shutil.rmtree(work_dir)
        except Exception:
            pass

    def test_user_action_one_shot_consumption(self):
        """
        Requirement 2: [USER ACTION] decisions are one-shot events:
        stored with job id, UI event id and timestamp, consumed once, never replayed on restart.
        """
        import job_options
        test_job_id = f"sandbox_action_test_{int(time.time()*1000)}"
        work_dir = os.path.join(BASE_DIR, "work", test_job_id)
        os.makedirs(work_dir, exist_ok=True)

        action_event = job_options.record_user_action(test_job_id, "make_shorter", triggered_by="ui")
        self.assertIsNotNone(action_event.get("event_id"))

        # Consume action
        consumed = job_options.consume_user_action(test_job_id)
        self.assertIsNotNone(consumed)
        self.assertEqual(consumed.get("action"), "make_shorter")

        # Second consume attempt must return None (cannot replay)
        replayed = job_options.consume_user_action(test_job_id)
        self.assertIsNone(replayed, "Consumed action must not replay on subsequent check")

        try:
            import shutil
            shutil.rmtree(work_dir)
        except Exception:
            pass

    def test_stage_a_caches_reject_results(self):
        """
        Requirement 7: Cache EVERY Stage A result, including REJECT reasons,
        keyed by (source hash, start, end, analyzer version, thresholds hash).
        """
        from pet_detector import StageACache
        cache = StageACache()
        src_hash = "mock_source_reject_hash_456"
        st, en = 50.0, 60.0
        ver = "v97"
        thresh = "sharp85_conf25"

        cache.clear(src_hash, st, en)
        self.assertIsNone(cache.get(src_hash, st, en, ver, thresh))

        reject_payload = {
            "status": "reject",
            "reason": "LOW_SHARPNESS (11.3 < 85)",
            "framing_score": 0.0,
            "sharpness": 11.3
        }
        cache.put(src_hash, st, en, ver, thresh, reject_payload)

        cached = cache.get(src_hash, st, en, ver, thresh)
        self.assertIsNotNone(cached, "REJECT results must be cached in StageACache")
        self.assertEqual(cached.get("status"), "reject")
        self.assertEqual(cached.get("reason"), "LOW_SHARPNESS (11.3 < 85)")

    def test_timing_table_shares_match_time_column(self):
        """
        Requirement 7: Timing table shares must be computed against the wall clock total
        for every row (exclusive for parents, nested rows indented), and they must match the time column.
        """
        from stage_timer import StageTimer
        timer = StageTimer("test_timing_shares", wall_start_epoch=time.time())

        # Stage with nested tracking
        timer.start_stage("stage_5_predict_framing")
        time.sleep(0.02)
        timer.start_stage("tracking")
        time.sleep(0.08)
        timer.stop_stage("tracking")
        time.sleep(0.02)
        timer.stop_stage("stage_5_predict_framing")

        timer.start_stage("reframe")
        time.sleep(0.05)
        timer.stop_stage("reframe")

        table_str = timer.format_table()
        lines = table_str.splitlines()

        # Find rows
        s5_line = next((l for l in lines if "stage_5_predict_framing" in l), None)
        trk_line = next((l for l in lines if "tracking" in l), None)
        ref_line = next((l for l in lines if "reframe" in l), None)

        self.assertIsNotNone(s5_line)
        self.assertIsNotNone(trk_line)
        self.assertIsNotNone(ref_line)

        # Check indentation on nested tracking
        self.assertIn("└─ tracking", trk_line, "Nested tracking must be indented")

        # Parse time and share columns for reframe
        parts = [p.strip() for p in ref_line.split("|")]
        dur_s = float(parts[1])
        share_pct = float(parts[3].replace("%", ""))

        summary = timer.get_summary()
        wall_sec = summary["total_wall_time_sec"]
        expected_share = round(dur_s / wall_sec * 100.0, 1)
        self.assertAlmostEqual(share_pct, expected_share, delta=1.0,
                               msg=f"Share {share_pct}% does not match time {dur_s}s / {wall_sec}s")

    def test_preflight_capacity_calculation(self):
        """
        Requirement 5: capacity = min(verified_windows, usable_sources * 3).
        100 clips on 2 usable sources with 1 verified window gives capacity = min(1, 6) = 1.
        """
        from web_server import compute_pool_capacity
        cap = compute_pool_capacity(verified_windows=1, usable_sources=2)
        self.assertEqual(cap["capacity"], 1)
        self.assertEqual(cap["min_sources_needed_for_100"], 34)
        self.assertEqual(cap["usable_sources"], 2)

    def test_harvest_status_full_schema(self):
        """
        Requirement 4: /api/harvest/status returns state (idle, running, error),
        current source, sources scanned, windows analyzed, windows verified,
        rejects by reason, last activity time and growth per minute.
        """
        from harvest_worker import get_harvest_status
        status = get_harvest_status()
        self.assertIn("state", status)
        self.assertIn(status["state"], ["idle", "running", "error"])
        self.assertIn("sources_scanned", status)
        self.assertIn("windows_analyzed", status)
        self.assertIn("windows_verified", status)
        self.assertIn("rejects_by_reason", status)
        self.assertIn("growth_per_minute", status)
    def test_waiting_sleep_state_machine(self):
        """
        Requirement 3:
        - Job in WAITING_FOR_CLIPS keeps ONE process and sleeps.
        - Wakes when verified clip count increases or user action received.
        - Persists wait budget (1800s) and waiting_since to wait_checkpoint.json.
        - Transitions to NEEDS_SOURCES after 3 consecutive no-growth checks or budget expiry.
        """
        from lion_automate_v97 import LionReelV97Pipeline
        import job_options
        pipeline = LionReelV97Pipeline()
        test_job_id = f"sandbox_wait_test_{int(time.time()*1000)}"
        work_dir = os.path.join(BASE_DIR, "work", test_job_id)
        os.makedirs(work_dir, exist_ok=True)
        wait_cp_path = os.path.join(work_dir, "wait_checkpoint.json")

        # 1. State machine initialization
        state = pipeline.init_or_load_wait_checkpoint(test_job_id, work_dir, initial_budget=1800.0)
        self.assertTrue(os.path.exists(wait_cp_path))
        self.assertEqual(state["wait_budget_sec"], 1800.0)
        self.assertEqual(state["consecutive_no_growth"], 0)
        start_ts = state["waiting_since"]

        # 2. Simulate 3 consecutive no-growth polls
        state = pipeline.update_wait_checkpoint(test_job_id, work_dir, new_growth=False)
        self.assertEqual(state["consecutive_no_growth"], 1)
        state = pipeline.update_wait_checkpoint(test_job_id, work_dir, new_growth=False)
        self.assertEqual(state["consecutive_no_growth"], 2)
        state = pipeline.update_wait_checkpoint(test_job_id, work_dir, new_growth=False)
        self.assertEqual(state["consecutive_no_growth"], 3)
        self.assertEqual(state["status"], job_options.STATE_NEEDS_SOURCES)

        # 3. Simulate growth resets consecutive_no_growth
        state = pipeline.update_wait_checkpoint(test_job_id, work_dir, new_growth=True)
        self.assertEqual(state["consecutive_no_growth"], 0)

        # 4. Persistence across restarts (waiting_since must NOT reset)
        reloaded = pipeline.init_or_load_wait_checkpoint(test_job_id, work_dir, initial_budget=1800.0)
        self.assertEqual(reloaded["waiting_since"], start_ts)

        try:
            import shutil
            shutil.rmtree(work_dir)
        except Exception:
            pass

    def test_auto_resume_watcher_rejects_sandbox_jobs(self):
        """
        Requirement 2 & 3:
        Production supervisor/auto_resume_watcher never resumes sandbox_ or test_ jobs.
        """
        from web_server import should_auto_resume_job
        self.assertFalse(should_auto_resume_job("sandbox_test_123", "waiting_for_clips"))
        self.assertFalse(should_auto_resume_job("test_small_long_1791693001", "waiting_for_clips"))
        # Real production job with waiting_for_clips can be evaluated
        self.assertTrue(should_auto_resume_job("lionreel_cat_20261011_120000_abcdef12", "waiting_for_clips"))

    def test_get_verified_clips_kwarg_compatibility(self):
        """
        Fix 14: get_verified_clips must accept both animal_type and animal_mode
        keyword arguments without raising TypeError.
        """
        import clip_ledger
        ledger = clip_ledger.ClipLedger()
        clips1 = ledger.get_verified_clips(animal_type="cat", limit=5)
        self.assertIsInstance(clips1, list)
        clips2 = ledger.get_verified_clips(animal_mode="cat", limit=5)
        self.assertIsInstance(clips2, list)
        clips3 = ledger.get_verified_clips(animal_type="cat", animal_mode="cat", limit=5)
        self.assertIsInstance(clips3, list)

if __name__ == "__main__":
    unittest.main()
