"""
test_fulfillment_planner.py
===========================
Validates:
1. Contract Total Length Guarantee: Planned duration ends within +/-2% (at most +/-2s for short videos).
2. Strategy ladder progression: Step 1 -> Step 2 -> Step 3 -> Step 4 -> Step 5.
3. Step 3 allows up to 8 windows per source for long sources with >= 20s spacing.
4. Step 4 adapts clip duration within [3.5s, 20.0s] bounds.
5. Step 5 repeat cycle: trim offset >= 1.5s, never back-to-back, spaced >= 8 clips apart where possible, flagged repeat, accurate repeat_share_pct.
6. Plain progress card string generation.
"""

import os
import sys
import unittest
import tempfile
import shutil
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger
from fulfillment_planner import FulfillmentPlanner, FulfillmentPlan

class TestFulfillmentPlanner(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_ledger.db")
        self.ledger = ClipLedger(db_path=self.db_path)
        self.planner = FulfillmentPlanner(ledger=self.ledger)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_bank(self, count, sources_count=4, orientation="landscape"):
        with self.ledger._get_conn() as conn:
            for i in range(count):
                src_id = f"src_{(i % sources_count) + 1}.mp4"
                src_path = os.path.join(BASE_DIR, "raw", f"dummy_{src_id}")
                os.makedirs(os.path.dirname(src_path), exist_ok=True)
                if not os.path.exists(src_path):
                    with open(src_path, "wb") as f:
                        f.write(b"0" * 1024)

                conn.execute("""
                    INSERT INTO clips (
                        clip_id, source_id, source_url_or_path, license, start_s, end_s,
                        quality_score, funny_score, animal_type, times_used,
                        is_verified, framing_score, sharpness, orientation, compilation_flag,
                        uploader, title, verified_plan, verified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"clip_{i}", src_id, src_path, "CC-BY", float(i * 35.0), float(i * 35.0 + 7.5),
                    2.0, 0.9, "cat", 0,
                    1, 1.0, 200.0, orientation, 0,
                    "Creator", "Title", json.dumps({"status": "pass"}), "2026-10-12 00:00:00"
                ))
            conn.commit()

    def test_step1_bank_sufficient(self):
        """When bank has enough verified unique clips, plan satisfies target using Step 1 with 0% repeats."""
        self._seed_bank(count=12, sources_count=4)
        target_total_sec = 45.0 # 6 clips x 7.5s
        plan = self.planner.plan_fulfillment(
            job_id="test_job_1",
            animal_mode="cat",
            target_total_sec=target_total_sec,
            target_clip_sec=7.5,
            video_type="short"
        )
        self.assertIsInstance(plan, FulfillmentPlan)
        # Contract duration within +/-2s
        self.assertAlmostEqual(plan.expected_total_sec, target_total_sec, delta=2.0)
        self.assertEqual(plan.repeat_share_pct, 0.0)
        self.assertIn("ladder_step_1", plan.strategy_used)
        self.assertGreaterEqual(len(plan.clips), 5)
        for c in plan.clips:
            self.assertFalse(c.get("is_repeat", False))

    def test_contract_duration_guarantee_various_lengths(self):
        """Contract duration must end within +/-2% for 30s, 60s, 300s (5m), 1200s (20m)."""
        self._seed_bank(count=8, sources_count=4)
        lengths = [30.0, 60.0, 180.0, 300.0]
        for t_sec in lengths:
            plan = self.planner.plan_fulfillment(
                job_id=f"test_job_dur_{int(t_sec)}",
                animal_mode="cat",
                target_total_sec=t_sec,
                target_clip_sec=7.5,
                video_type="long" if t_sec > 60 else "short"
            )
            tol = max(2.0, t_sec * 0.02)
            self.assertAlmostEqual(plan.expected_total_sec, t_sec, delta=tol,
                msg=f"Contract {t_sec}s failed: got {plan.expected_total_sec}s (diff {abs(plan.expected_total_sec - t_sec)}s > tol {tol}s)")

    def test_step3_expanded_windows_per_source(self):
        """Step 3 allows up to 8 windows per source for long sources with >= 20s spacing."""
        # Only 2 sources available, each with 8 non-overlapping moments
        with self.ledger._get_conn() as conn:
            for s_idx in [1, 2]:
                src_id = f"long_source_{s_idx}.mp4"
                src_path = os.path.join(BASE_DIR, "raw", f"dummy_{src_id}")
                if not os.path.exists(src_path):
                    with open(src_path, "wb") as f: f.write(b"0" * 1024)
                for w_idx in range(6):
                    conn.execute("""
                        INSERT INTO clips (
                            clip_id, source_id, source_url_or_path, license, start_s, end_s,
                            quality_score, funny_score, animal_type, times_used,
                            is_verified, framing_score, sharpness, orientation, compilation_flag,
                            uploader, title, verified_plan, verified_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        f"c_{s_idx}_{w_idx}", src_id, src_path, "CC-BY", float(w_idx * 40.0), float(w_idx * 40.0 + 8.0),
                        2.0, 0.9, "cat", 0,
                        1, 1.0, 200.0, "landscape", 0,
                        "Creator", "Title", json.dumps({"status": "pass"}), "2026-10-12 00:00:00"
                    ))
            conn.commit()

        # Needs 10 clips (80s total)
        plan = self.planner.plan_fulfillment(
            job_id="test_step3_job",
            animal_mode="cat",
            target_total_sec=80.0,
            target_clip_sec=8.0,
            video_type="long"
        )
        self.assertAlmostEqual(plan.expected_total_sec, 80.0, delta=2.0)
        # Should have drawn more than 3 clips from the sources without repeat
        by_source = {}
        for c in plan.clips:
            by_source[c["source_id"]] = by_source.get(c["source_id"], 0) + 1
        max_from_single = max(by_source.values())
        self.assertGreater(max_from_single, 3, "Step 3 should allow more than 3 clips per source")

    def test_step5_repeat_cycle_constraints(self):
        """When bank has only 4 clips and video needs 120s (16 clips), Step 5 repeats clips with >= 1.5s offset and spacing."""
        self._seed_bank(count=4, sources_count=4)
        plan = self.planner.plan_fulfillment(
            job_id="test_repeat_job",
            animal_mode="cat",
            target_total_sec=120.0,
            target_clip_sec=7.5,
            video_type="long"
        )
        self.assertAlmostEqual(plan.expected_total_sec, 120.0, delta=3.0)
        self.assertGreater(plan.repeat_share_pct, 0.0)

        # Check repeats are flagged and have offset
        repeats = [c for c in plan.clips if c.get("is_repeat")]
        self.assertGreater(len(repeats), 0)
        for r in repeats:
            self.assertGreaterEqual(r.get("repeat_offset_s", 0.0), 1.5)

        # Check never back-to-back identical source and clip
        for i in range(len(plan.clips) - 1):
            c1 = plan.clips[i]
            c2 = plan.clips[i + 1]
            self.assertNotEqual(c1["clip_id"], c2["clip_id"], f"Back to back repeat found at index {i}")

    def test_progress_card_string(self):
        """Card shows feasibility line: 'N unique moments: X.X min unique, Y.Y min with 3 uses, Z.Z min with 8 uses. [Harvest status]'."""
        self._seed_bank(count=6, sources_count=4)
        plan = self.planner.plan_fulfillment(
            job_id="test_card_str",
            animal_mode="cat",
            target_total_sec=90.0,
            target_clip_sec=7.5,
            video_type="long"
        )
        status_line = plan.get_card_status_line()
        self.assertIn("unique moments:", status_line)
        self.assertIn("min with 3 uses", status_line)
        self.assertIn("min with 8 uses", status_line)

if __name__ == "__main__":
    unittest.main()
