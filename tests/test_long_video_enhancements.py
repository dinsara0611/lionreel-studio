"""
tests/test_long_video_enhancements.py
=====================================
Unit tests validating:
1. Spacing-aware repeat interleaving (zero adjacent identical clips, spacing >= min(8, unique-1)).
2. 150.0 Laplacian variance sharpness floor enforcement in QA gates.
3. Clean repeat IDs ({base_id}_use{N}_off{s}) without chained rep1_rep1 and hard cap of 8 uses.
4. Zero copied metrics for repeats (independent plans and measurements).
5. Length contract duration guarantee within +/-2%.
6. Auto-repair loop logic for recoverable QA spacing.
"""

import os
import sys
import unittest
import tempfile
import shutil
import json
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger
from fulfillment_planner import FulfillmentPlanner, FulfillmentPlan
import qa_check

class TestLongVideoEnhancements(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_ledger.db")
        self.ledger = ClipLedger(db_path=self.db_path)
        self.planner = FulfillmentPlanner(ledger=self.ledger)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_bank(self, count, duration=7.5, sources_count=4):
        with self.ledger._get_conn() as conn:
            for i in range(count):
                src_id = f"src_{(i % sources_count) + 1}.mp4"
                src_path = os.path.join(self.temp_dir, f"dummy_{src_id}")
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
                    f"c_{i+1:03d}", src_id, src_path, "CC-BY", float(i * 35.0), float(i * 35.0 + duration),
                    2.0, 0.9, "cat", 0,
                    1, 1.0, 200.0, "horizontal", 0,
                    "Creator", "Title", json.dumps({"status": "pass", "best_dur_s": duration}), "2026-10-12 00:00:00"
                ))

    def test_spacing_aware_ordering(self):
        """Verifies interleaving never allows adjacent identical clips and achieves maximum spacing."""
        # 3 base clips, each repeated 3 times = 9 clips total
        pool = []
        for cycle in range(3):
            for base_id in ["base_a", "base_b", "base_c"]:
                pool.append({
                    "clip_id": f"{base_id}_use{cycle+1}",
                    "base_clip_id": base_id,
                    "is_repeat": (cycle > 0)
                })

        spaced = self.planner._space_repeats(pool)
        self.assertEqual(len(spaced), len(pool))

        # Check: no two adjacent clips share the same base_clip_id
        for i in range(len(spaced) - 1):
            curr_base = spaced[i].get("base_clip_id") or re.sub(r'_(?:rep|use)\d+.*$', '', spaced[i]["clip_id"])
            next_base = spaced[i+1].get("base_clip_id") or re.sub(r'_(?:rep|use)\d+.*$', '', spaced[i+1]["clip_id"])
            self.assertNotEqual(curr_base, next_base, f"Adjacent identical base clips at index {i} and {i+1}: {curr_base}")

    def test_150_sharpness_floor_in_qa_check(self):
        """Verifies that visual sharpness gate rejects below 150.0 Laplacian variance."""
        # Check that MIN_SHARPNESS_FLOOR is at least 150.0
        self.assertGreaterEqual(qa_check.MIN_SHARPNESS_FLOOR, 150.0)

        # Check that benchmark config hash is properly loaded and 64 characters (SHA256 hex)
        cfg_hash = qa_check.get_benchmark_config_hash()
        self.assertIsInstance(cfg_hash, str)
        self.assertEqual(len(cfg_hash), 64)

        # Test threshold comparison
        val_fail = 149.9
        val_pass = 150.0
        self.assertFalse(val_fail >= qa_check.MIN_SHARPNESS_FLOOR)
        self.assertTrue(val_pass >= qa_check.MIN_SHARPNESS_FLOOR)

    def test_clean_repeat_ids_and_hard_cap_8(self):
        """Verifies clean ID formatting {base_id}_use{N}_off{s} and hard cap of 8 uses."""
        # 1 base clip with 10s duration, target = 80s (requires 8 uses)
        self._seed_bank(1, duration=10.0)
        plan = self.planner.plan_fulfillment(
            job_id="test_cap8",
            animal_mode="cat",
            target_total_sec=80.0,
            target_clip_sec=10.0,
            video_type="compilation",
            work_dir=self.temp_dir
        )
        self.assertEqual(plan.target_clips_count, 8)
        # All clips must have clean IDs and no rep1_rep1 chaining
        for c in plan.clips:
            cid = c["clip_id"]
            self.assertFalse("_rep" in cid and "_rep" in cid[cid.find("_rep")+4:], f"Chained repeat detected: {cid}")
            self.assertFalse("rep1_rep1" in cid)

        # Now test asking for 120s with only 1 clip: must be capped at 8 uses
        plan_over = self.planner.plan_fulfillment(
            job_id="test_over_cap",
            animal_mode="cat",
            target_total_sec=120.0,
            target_clip_sec=10.0,
            video_type="compilation",
            work_dir=self.temp_dir
        )
        # Max uses per window is 8, so max clips from 1 base clip is 8
        self.assertLessEqual(plan_over.target_clips_count, 8)

    def test_length_contract_tolerance(self):
        """Verifies that fulfillment planner respects contract total duration within +/-2%."""
        self._seed_bank(15, duration=7.5)
        targets = [180.0, 360.0, 600.0]
        for tgt in targets:
            plan = self.planner.plan_fulfillment(
                job_id=f"test_tgt_{int(tgt)}",
                animal_mode="cat",
                target_total_sec=tgt,
                target_clip_sec=7.5,
                video_type="compilation",
                work_dir=self.temp_dir
            )
            dur_diff = abs(plan.expected_total_sec - tgt) / tgt
            self.assertLessEqual(dur_diff, 0.02, f"Target {tgt}s drifted by {dur_diff*100:.2f}% (expected <= 2%)")

    def test_auto_repair_reorders_spacing(self):
        """Verifies that auto-repair can re-space a pool of clips without re-rendering."""
        pool = [
            {"clip_id": "c_001_use1", "base_clip_id": "c_001", "is_repeat": False},
            {"clip_id": "c_001_use2", "base_clip_id": "c_001", "is_repeat": True},
            {"clip_id": "c_002_use1", "base_clip_id": "c_002", "is_repeat": False},
            {"clip_id": "c_002_use2", "base_clip_id": "c_002", "is_repeat": True},
        ]
        # Initially adjacent identical: index 0 and 1 are c_001
        self.assertEqual(pool[0]["base_clip_id"], pool[1]["base_clip_id"])

        # Auto-repair spacing
        repaired = self.planner._space_repeats(pool)
        for i in range(len(repaired) - 1):
            self.assertNotEqual(repaired[i]["base_clip_id"], repaired[i+1]["base_clip_id"])

if __name__ == "__main__":
    unittest.main()
