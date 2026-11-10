"""
Unit Tests for Server-Side Pipeline Estimator (stage_estimator.py)
Tests all 8 required fixture conditions:
(a) elapsed 165s at 50% with history that says 60s left must NOT return 165s
(b) slow stage (tracking taking 3x longer than expected) raises ETA but never percentage backwards
(c) cached stage (0.1s) does not distort speed factor
(d) scope growth (harvest or replacement clip) keeps progress monotonic
(e) first stage shows "Calculating..."
(f) failed job: no ETA, timers stopped
(g) waiting state: waiting time separate
(h) huge clip count stays sane
"""

import os
import sys
import unittest
import time
import tempfile
import sqlite3

from stage_estimator import StageEstimator, format_time_hms

class TestStageEstimator(unittest.TestCase):
    def setUp(self):
        # Use a temporary database for test isolation
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.estimator = StageEstimator(db_path=self.temp_db.name)

        # Seed known test history: Stage 1: 1s, Stage 2: 1s, Stage 3: 2s, Stage 4: 10s,
        # Stage 5: 60s, Stage 6: 120s, Stage 7: 1s, Stage 8: 30s, Stage 9: 60s, Stage 10: 2s
        # Total ~ 287s
        for stage_id, dur in [(1, 1.0), (2, 1.0), (3, 2.0), (4, 10.0), (5, 60.0),
                              (6, 120.0), (7, 1.0), (8, 30.0), (9, 60.0), (10, 2.0)]:
            for _ in range(5):
                self.estimator.record_stage_execution(
                    job_id="fixture_seed",
                    stage_id=stage_id,
                    stage_key=f"stage_{stage_id}",
                    duration_sec=dur,
                    clips_count=6,
                    clip_time=7.5,
                    mode="short"
                )

    def tearDown(self):
        try:
            os.unlink(self.temp_db.name)
        except Exception:
            pass

    def _build_stages_state(self, stage_statuses):
        """Helper to build a stages state array with specified statuses and durations."""
        stages = []
        for i in range(1, 11):
            st, dur, units = stage_statuses.get(i, ("PENDING", 0.0, (0, 0)))
            stages.append({
                "id": i,
                "key": f"stage_{i}",
                "label": f"Stage {i}",
                "status": st,
                "duration_sec": dur,
                "start_time": time.time() - dur if st == "RUNNING" else None,
                "details": {
                    "units_done": units[0],
                    "units_total": units[1],
                    "unit_type": "items"
                }
            })
        return stages

    def test_a_elapsed_165s_at_50_pct_never_returns_165s_eta(self):
        """(a) Elapsed 165s at 50% with history saying ~60s left must NOT return 165s."""
        # Stages 1-5 done (total ~74s expected), Stage 6 running at 50% (expected 120s, so 60s left in stg 6 + 93s pending)
        # Even with elapsed = 165s, the estimator must calculate from remaining stages, NOT elapsed * (100-p)/p!
        stages = self._build_stages_state({
            1: ("DONE", 1.0, (0, 0)),
            2: ("DONE", 1.0, (0, 0)),
            3: ("DONE", 2.0, (0, 0)),
            4: ("DONE", 10.0, (0, 0)),
            5: ("DONE", 60.0, (10, 10)),
            6: ("RUNNING", 60.0, (3, 6)),  # 3 of 6 clips done (50% of Stage 6)
            7: ("PENDING", 0.0, (0, 0)),
            8: ("PENDING", 0.0, (0, 0)),
            9: ("PENDING", 0.0, (0, 0)),
            10: ("PENDING", 0.0, (0, 0)),
        })
        start_time = time.time() - 165.0 # elapsed = 165s
        telemetry = self.estimator.compute_job_telemetry(
            job_id="test_a",
            stages_data={"stages": stages, "max_seen_pct": 0},
            config={"TARGET_CLIPS": 6, "SHORT_CLIP_SEC": 7.5, "VIDEO_TYPE": "short"},
            start_time_epoch=start_time,
            is_running=True,
            status="running"
        )
        self.assertEqual(telemetry["elapsedSeconds"], 165)
        # Old naive formula would give exactly 165s!
        # With real remaining work (60s remaining in stage 6 + stage 7(1) + stage 8(30) + stage 9(60) + stage 10(2) = ~153s)
        # ETA must NOT be equal to 165s by straight-line formula!
        self.assertNotEqual(telemetry["etaSeconds"], 165, "ETA must not equal elapsed time by straight-line formula")
        self.assertNotEqual(telemetry["etaFormatted"], format_time_hms(165))

    def test_b_slow_stage_raises_eta_without_reversing_progress(self):
        """(b) Slow stage (taking 3x longer than expected) raises ETA but never reverses percentage."""
        # Initial state at 30%
        stages_normal = self._build_stages_state({
            1: ("DONE", 1.0, (0, 0)),
            2: ("DONE", 1.0, (0, 0)),
            3: ("DONE", 2.0, (0, 0)),
            4: ("DONE", 10.0, (0, 0)),
            5: ("RUNNING", 20.0, (5, 20)),
        })
        state_dict = {"stages": stages_normal, "max_seen_pct": 35}
        tel1 = self.estimator.compute_job_telemetry("test_b", state_dict, start_time_epoch=time.time() - 34)
        pct1 = tel1["progressPct"]

        # Now stage 5 takes 3x longer (180s actual for stage 5)
        stages_slow = self._build_stages_state({
            1: ("DONE", 1.0, (0, 0)),
            2: ("DONE", 1.0, (0, 0)),
            3: ("DONE", 2.0, (0, 0)),
            4: ("DONE", 10.0, (0, 0)),
            5: ("RUNNING", 180.0, (5, 20)),
        })
        state_dict["stages"] = stages_slow
        tel2 = self.estimator.compute_job_telemetry("test_b", state_dict, start_time_epoch=time.time() - 194)
        pct2 = tel2["progressPct"]

        self.assertGreaterEqual(pct2, pct1, "Progress percentage must be monotonic and never decrease")
        self.assertGreater(tel2["speedFactor"], 1.0, "Speed factor must increase when stage takes longer")

    def test_c_cached_stage_does_not_distort_speed_factor(self):
        """(c) Cached stage (0.1s) does not distort speed factor."""
        stages = self._build_stages_state({
            1: ("DONE", 1.0, (0, 0)),
            2: ("DONE", 1.0, (0, 0)),
            3: ("DONE", 2.0, (0, 0)),
            4: ("DONE", 10.0, (0, 0)),
            5: ("CACHED", 0.05, (20, 20)), # Cached stage
            6: ("RUNNING", 10.0, (1, 6)),
        })
        stages[4]["status"] = "CACHED" # explicitly ensure CACHED status
        telemetry = self.estimator.compute_job_telemetry("test_c", {"stages": stages})
        # Speed factor should remain normal (close to 1.0) and NOT drop to 0.01
        self.assertGreaterEqual(telemetry["speedFactor"], 0.8)
        self.assertLessEqual(telemetry["speedFactor"], 1.5)

    def test_d_scope_growth_keeps_progress_monotonic(self):
        """(d) Scope growth (replacement clip / harvest) keeps progress monotonic."""
        # Initially 4 clips rendered out of 6
        stages_initial = self._build_stages_state({
            1: ("DONE", 1.0, (0, 0)),
            2: ("DONE", 1.0, (0, 0)),
            3: ("DONE", 2.0, (0, 0)),
            4: ("DONE", 10.0, (0, 0)),
            5: ("DONE", 60.0, (20, 20)),
            6: ("RUNNING", 80.0, (4, 6)),
        })
        state_dict = {"stages": stages_initial, "max_seen_pct": 0}
        t1 = self.estimator.compute_job_telemetry("test_d", state_dict)
        pct1 = t1["progressPct"]

        # Scope expands: replacement clip needed, now 4 out of 8 clips rendered
        stages_expanded = self._build_stages_state({
            1: ("DONE", 1.0, (0, 0)),
            2: ("DONE", 1.0, (0, 0)),
            3: ("DONE", 2.0, (0, 0)),
            4: ("DONE", 10.0, (0, 0)),
            5: ("DONE", 60.0, (20, 20)),
            6: ("RUNNING", 80.0, (4, 8)), # Scope grew from 6 to 8!
        })
        state_dict["stages"] = stages_expanded
        t2 = self.estimator.compute_job_telemetry("test_d", state_dict, config={"TARGET_CLIPS": 8})
        pct2 = t2["progressPct"]

        self.assertGreaterEqual(pct2, pct1, "Progress must never jump backwards even when scope expands")

    def test_e_first_stage_shows_calculating(self):
        """(e) First stage shows 'Calculating...' instead of a fake number."""
        stages = self._build_stages_state({
            1: ("RUNNING", 2.0, (0, 0)),
        })
        telemetry = self.estimator.compute_job_telemetry("test_e", {"stages": stages}, start_time_epoch=time.time() - 2.0)
        self.assertTrue(telemetry["isCalculating"])
        self.assertEqual(telemetry["etaFormatted"], "Calculating…")

    def test_f_failed_job_no_eta_timers_stopped(self):
        """(f) Failed job: no ETA, timers stopped, stateLabel is FAILED."""
        stages = self._build_stages_state({
            1: ("DONE", 1.0, (0, 0)),
            2: ("DONE", 1.0, (0, 0)),
            3: ("FAILED", 1.0, (0, 0)),
        })
        telemetry = self.estimator.compute_job_telemetry("test_f", {"stages": stages}, status="failed", start_time_epoch=time.time() - 45.0)
        self.assertEqual(telemetry["etaSeconds"], 0)
        self.assertEqual(telemetry["etaFormatted"], "Failed")
        self.assertEqual(telemetry["stateLabel"], "FAILED")
        self.assertEqual(telemetry["progressPct"], 100)

    def test_g_waiting_state_waiting_time_separate(self):
        """(g) Waiting state: waiting time shown separately, eta formatted as 'Waiting for clips'."""
        stages = self._build_stages_state({
            1: ("RUNNING", 5.0, (0, 0)),
        })
        telemetry = self.estimator.compute_job_telemetry(
            "test_g",
            {"stages": stages},
            status="waiting_for_clips",
            start_time_epoch=time.time() - 60.0,
            waiting_seconds=45.0
        )
        self.assertEqual(telemetry["stateLabel"], "WAITING")
        self.assertEqual(telemetry["etaFormatted"], "Waiting for clips")
        self.assertEqual(telemetry["waitingSeconds"], 45)
        self.assertEqual(telemetry["elapsedSeconds"], 15) # 60 - 45 net elapsed

    def test_h_huge_clip_count_stays_sane(self):
        """(h) Huge clip count (50 clips) stays sane without NaN, Infinity, or zero-division."""
        stages = self._build_stages_state({
            1: ("DONE", 5.0, (0, 0)),
            2: ("DONE", 5.0, (0, 0)),
            3: ("DONE", 10.0, (0, 0)),
            4: ("DONE", 30.0, (0, 0)),
            5: ("DONE", 300.0, (100, 100)),
            6: ("RUNNING", 150.0, (10, 50)),
        })
        telemetry = self.estimator.compute_job_telemetry(
            "test_h",
            {"stages": stages},
            config={"TARGET_CLIPS": 50, "SHORT_CLIP_SEC": 7.5, "VIDEO_TYPE": "compilation"},
            start_time_epoch=time.time() - 500.0
        )
        self.assertGreater(telemetry["etaSeconds"], 0)
        self.assertFalse(telemetry["isCalculating"])
        self.assertIsInstance(telemetry["etaFormatted"], str)
        self.assertIn("min", telemetry["etaFormatted"])

if __name__ == "__main__":
    unittest.main()
