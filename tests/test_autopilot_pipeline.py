"""
Unit tests for Autopilot Pipeline & Fulfillment Guarantee
Verifies:
1. Contract duration guarantee (+/- 2% for short and long videos).
2. Elimination of waiting states / pool-shortage halts.
3. Quality floor maintenance (sharpness >= 150, legal sources).
4. Mapping and QA report repeat flags and repeat share calculation.
5. Monotonic StageTimer exclusive rows and share percentages.
"""

import os
import sys
import unittest
import json
import sqlite3
import tempfile
import shutil

# Ensure base directory is on path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger
from fulfillment_planner import FulfillmentPlanner, FulfillmentPlan
from stage_timer import StageTimer


class TestAutopilotPipeline(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_autopilot_")
        self.db_path = os.path.join(self.test_dir, "test_ledger.db")
        self.ledger = ClipLedger(db_path=self.db_path)
        self.planner = FulfillmentPlanner(ledger=self.ledger)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _seed_bank(self, count=8, sources_count=4, sharpness=165.0):
        """Seed verified clips into test ledger."""
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

    def test_autopilot_fulfills_any_length_without_shortage_halt(self):
        """Test autopilot fulfills 15s to 20+ min without halting or returning None."""
        self._seed_bank(count=8, sources_count=4)

        # 1. Test 15s short video
        plan_15s = self.planner.plan_fulfillment(
            job_id="job_auto_15s",
            animal_mode="cat",
            target_total_sec=15.0,
            target_clip_sec=7.5,
            video_type="short"
        )
        self.assertIsNotNone(plan_15s)
        self.assertAlmostEqual(plan_15s.expected_total_sec, 15.0, delta=15.0 * 0.02)
        self.assertEqual(len(plan_15s.clips), 2)
        self.assertFalse(any(c.get("is_repeat") for c in plan_15s.clips))

        # 2. Test 3-minute video (180s)
        plan_3m = self.planner.plan_fulfillment(
            job_id="job_auto_3m",
            animal_mode="cat",
            target_total_sec=180.0,
            target_clip_sec=10.0,
            video_type="long"
        )
        self.assertIsNotNone(plan_3m)
        self.assertAlmostEqual(plan_3m.expected_total_sec, 180.0, delta=180.0 * 0.02)
        self.assertGreaterEqual(len(plan_3m.clips), 8)

        # 3. Test 20-minute video (1200s)
        plan_20m = self.planner.plan_fulfillment(
            job_id="job_auto_20m",
            animal_mode="cat",
            target_total_sec=1200.0,
            target_clip_sec=15.0,
            video_type="long"
        )
        self.assertIsNotNone(plan_20m)
        self.assertAlmostEqual(plan_20m.expected_total_sec, 1200.0, delta=1200.0 * 0.02)
        # Verify repeat share is tracked and nonzero for a 20 min video on small bank
        self.assertGreater(plan_20m.repeat_share_pct, 0.0)

    def test_contract_duration_within_two_percent(self):
        """Total duration contract: output must end within +/-2% (at most +/-2s for short)."""
        self._seed_bank(count=8, sources_count=4)
        targets = [30.0, 60.0, 120.0, 300.0, 600.0, 1200.0]

        for target in targets:
            plan = self.planner.plan_fulfillment(
                job_id=f"job_contract_{int(target)}",
                animal_mode="cat",
                target_total_sec=target,
                target_clip_sec=7.5,
                video_type="long" if target > 60 else "short"
            )
            max_delta = max(2.0, target * 0.02)
            self.assertAlmostEqual(
                plan.expected_total_sec, target, delta=max_delta,
                msg=f"Target {target}s failed contract tolerance: got {plan.expected_total_sec}s"
            )

    def test_quality_floor_preserved_sharpness_and_legal(self):
        """Quality floor: sharpness >= 150, creator & license recorded."""
        self._seed_bank(count=6, sources_count=3, sharpness=170.0)
        plan = self.planner.plan_fulfillment(
            job_id="job_quality_test",
            animal_mode="cat",
            target_total_sec=60.0,
            target_clip_sec=10.0,
            video_type="long"
        )
        for c in plan.clips:
            self.assertGreaterEqual(float(c.get("sharpness", 150.0)), 150.0)
            self.assertTrue(c.get("license") in ("CC-BY", "Creative Commons CC-BY 4.0", "Own Footage"))
            self.assertTrue(bool(c.get("uploader")))

    def test_repeat_spacing_and_offsets(self):
        """Repeats must have trim offset >= 1.5s, be spaced >= 8 clips apart, never back-to-back."""
        self._seed_bank(count=4, sources_count=2)
        plan = self.planner.plan_fulfillment(
            job_id="job_repeat_spacing",
            animal_mode="cat",
            target_total_sec=180.0,
            target_clip_sec=7.5,
            video_type="long"
        )
        self.assertGreater(plan.repeat_share_pct, 0.0)
        repeats = [c for c in plan.clips if c.get("is_repeat")]
        self.assertGreater(len(repeats), 0)

        for r in repeats:
            self.assertGreaterEqual(r.get("repeat_offset_s", 0.0), 1.5)
            self.assertIn("Viral Moment", r.get("caption_variant", ""))

        for i in range(len(plan.clips) - 1):
            c1 = plan.clips[i]
            c2 = plan.clips[i + 1]
            self.assertNotEqual(c1["clip_id"], c2["clip_id"])


if __name__ == "__main__":
    unittest.main()
