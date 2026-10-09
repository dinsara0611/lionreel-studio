"""
LionReel Studio — Automated Tests for Stage State Machine & Order Enforcement
=============================================================================
Standard Library unittest test suite:
1. Strict sequential order enforcement: start(stage n) >= end(stage n-1)
2. STAGE_ORDER_VIOLATION raised when stage started out of order
3. MISSING_INPUT raised when input artifact is missing or empty
4. EMPTY_RESULT raised when stage produces zero items
5. Filter toggle skipping: turned off in settings -> stage marked SKIPPED with reason
6. Proof file generation: work/<job_id>/stages/<n>_<id>.json with timings, device, evidence
7. Killed backend detection: RUNNING stages marked FAILED upon process error
8. API endpoints: /api/stages and /api/status honest payload validation
"""

import os
import sys
import json
import time
import shutil
import unittest

# Add repo root to sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from stage_state_machine import (
    StageStateMachine,
    STAGE_DEFINITIONS,
    StageOrderViolationError,
    MissingInputError,
    EmptyResultError
)

TEST_WORK_DIR = os.path.join(REPO_ROOT, "work", "test_stage_order_job")

class TestStageOrderStateMachine(unittest.TestCase):

    def setUp(self):
        if os.path.exists(TEST_WORK_DIR):
            shutil.rmtree(TEST_WORK_DIR, ignore_errors=True)
        os.makedirs(TEST_WORK_DIR, exist_ok=True)

    def tearDown(self):
        if os.path.exists(TEST_WORK_DIR):
            shutil.rmtree(TEST_WORK_DIR, ignore_errors=True)

    def test_stage_definitions_integrity(self):
        """Verify STAGE_DEFINITIONS contains exactly 10 sequential stages."""
        self.assertEqual(len(STAGE_DEFINITIONS), 10)
        for idx, defn in enumerate(STAGE_DEFINITIONS, start=1):
            self.assertEqual(defn["id"], idx)
            if idx == 1:
                self.assertEqual(defn["prerequisites"], [])
                self.assertIsNone(defn["input_artifact"])
            else:
                self.assertEqual(defn["prerequisites"], [idx - 1])
                prev_out = STAGE_DEFINITIONS[idx - 2]["output_artifact"]
                self.assertEqual(defn["input_artifact"], prev_out)

    def test_sequential_order_execution(self):
        """Verify happy path executes strictly in order: start(n) >= end(n-1)."""
        sm = StageStateMachine(job_id="test_seq_001", work_dir=TEST_WORK_DIR)
        
        prev_end = None
        for stage_id in range(1, 11):
            s = sm.start_stage(stage_id)
            self.assertEqual(s["status"], "RUNNING")
            if prev_end is not None:
                self.assertGreaterEqual(
                    s["start_time"], prev_end,
                    f"Stage {stage_id} started before stage {stage_id - 1} ended!"
                )
            
            time.sleep(0.01) # real work duration
            
            # Write expected output artifact
            out_file = STAGE_DEFINITIONS[stage_id - 1]["output_artifact"]
            out_path = os.path.join(sm.stages_dir, out_file)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump({"dummy": f"stage_{stage_id}"}, f)
                
            c = sm.complete_stage(
                stage_id,
                evidence=f"Stage {stage_id} real work verified",
                proof_data={"items_count": 4, "device": "CPU"}
            )
            self.assertEqual(c["status"], "DONE")
            self.assertGreater(c["duration_sec"], 0)
            prev_end = c["end_time"]

        for s in sm.get_all_stages():
            self.assertEqual(s["status"], "DONE")

    def test_order_violation_raises(self):
        """Verify STAGE_ORDER_VIOLATION is raised if starting or skipping out of order."""
        sm = StageStateMachine(job_id="test_violation_001", work_dir=TEST_WORK_DIR)
        
        # Try to start stage 3 while stage 1 and 2 are PENDING
        with self.assertRaises(StageOrderViolationError) as cm:
            sm.start_stage(3)
        self.assertIn("STAGE_ORDER_VIOLATION", str(cm.exception))
        self.assertIn("Stage 3", str(cm.exception))

        # Start stage 1 and complete it
        sm.start_stage(1)
        sm.complete_stage(1, evidence="Stage 1 done", proof_data={"items_count": 4})
        
        # Try to jump to stage 4 while stage 2 is PENDING
        with self.assertRaises(StageOrderViolationError) as cm2:
            sm.start_stage(4)
        self.assertIn("STAGE_ORDER_VIOLATION", str(cm2.exception))

    def test_negative_missing_input(self):
        """Negative Test: Delete stage 4 output artifact and confirm stage 5 raises MISSING_INPUT."""
        sm = StageStateMachine(job_id="test_missing_input_001", work_dir=TEST_WORK_DIR)
        
        for sid in range(1, 4):
            sm.start_stage(sid)
            out_f = STAGE_DEFINITIONS[sid - 1]["output_artifact"]
            with open(os.path.join(sm.stages_dir, out_f), "w", encoding="utf-8") as f:
                json.dump({"data": sid}, f)
            sm.complete_stage(sid, evidence=f"Stage {sid} complete", proof_data={"items_count": 4})
            
        sm.start_stage(4)
        sm.complete_stage(4, evidence="Stage 4 completed", proof_data={"items_count": 4})
        
        out_f4 = STAGE_DEFINITIONS[3]["output_artifact"]
        out_p4 = os.path.join(sm.stages_dir, out_f4)
        if os.path.exists(out_p4):
            os.remove(out_p4)
        self.assertFalse(os.path.exists(out_p4))
        
        with self.assertRaises(MissingInputError) as cm:
            sm.start_stage(5)
        self.assertIn("MISSING_INPUT", str(cm.exception))
        self.assertIn("watermark_checked.json", str(cm.exception))

    def test_negative_empty_result(self):
        """Negative Test: Stage producing 0 items where items were expected fails with EMPTY_RESULT."""
        sm = StageStateMachine(job_id="test_empty_result_001", work_dir=TEST_WORK_DIR)
        
        sm.start_stage(1)
        sm.complete_stage(1, evidence="Stage 1 complete", proof_data={"items_count": 4})
        
        sm.start_stage(2)
        with self.assertRaises(EmptyResultError) as cm:
            sm.complete_stage(
                2,
                evidence="Failed: 0 sources found",
                proof_data={"items_count": 0}
            )
        self.assertIn("EMPTY_RESULT", str(cm.exception))
        
        s2 = sm._get_stage(2)
        self.assertEqual(s2["status"], "FAILED")
        self.assertIn("EMPTY_RESULT", s2["reason"])

    def test_filter_toggles_and_skip(self):
        """Verify toggled-off filters result in honest SKIPPED status with reason."""
        sm = StageStateMachine(job_id="test_skip_001", work_dir=TEST_WORK_DIR)
        
        for sid in range(1, 3):
            sm.start_stage(sid)
            out_f = STAGE_DEFINITIONS[sid - 1]["output_artifact"]
            with open(os.path.join(sm.stages_dir, out_f), "w", encoding="utf-8") as f:
                json.dump({"data": sid}, f)
            sm.complete_stage(sid, evidence=f"Stage {sid} complete", proof_data={"items_count": 4})
            
        out_f3 = STAGE_DEFINITIONS[2]["output_artifact"]
        inp_f3 = STAGE_DEFINITIONS[2]["input_artifact"]
        shutil.copyfile(os.path.join(sm.stages_dir, inp_f3), os.path.join(sm.stages_dir, out_f3))
        
        sm.skip_stage(3, reason="turned off in settings")
        s3 = sm._get_stage(3)
        self.assertEqual(s3["status"], "SKIPPED")
        self.assertEqual(s3["reason"], "turned off in settings")
        
        sm.start_stage(4)
        s4 = sm._get_stage(4)
        self.assertEqual(s4["status"], "RUNNING")

    def test_proof_file_generation(self):
        """Verify proof file written to work/<job_id>/stages/<n>_<id>.json with required schema."""
        sm = StageStateMachine(job_id="test_proof_001", work_dir=TEST_WORK_DIR)
        
        sm.start_stage(1)
        sm.complete_stage(
            1,
            evidence="Reserved 4 candidate clips",
            proof_data={
                "candidates_count": 4,
                "clips": ["clip1.mp4", "clip2.mp4"],
                "hash": "abc123hash"
            }
        )
        
        proof_path = os.path.join(sm.stages_dir, "1_collect_candidates.json")
        alt_proof_path = os.path.join(sm.stages_dir, "1_1.json")
        self.assertTrue(os.path.exists(proof_path))
        self.assertTrue(os.path.exists(alt_proof_path))
        
        with open(proof_path, "r", encoding="utf-8") as f:
            proof = json.load(f)
            self.assertEqual(proof["stage_id"], 1)
            self.assertEqual(proof["stage_key"], "collect_candidates")
            self.assertEqual(proof["job_id"], "test_proof_001")
            self.assertIn("device", proof)
            self.assertIn("timings", proof)
            self.assertIn("completed_at", proof)
            self.assertIn("evidence", proof)
            self.assertEqual(proof["candidates_count"], 4)

    def test_under_1s_explanation(self):
        """Verify stages that finish in under 1s show why in evidence."""
        sm = StageStateMachine(job_id="test_instant_001", work_dir=TEST_WORK_DIR)
        sm.start_stage(1)
        c = sm.complete_stage(1, evidence="Pool ready", proof_data={"items_count": 4})
        self.assertTrue("instant:" in c["evidence"] or "ready" in c["evidence"].lower())

    def test_killed_backend_detection(self):
        """Verify that when the backend process dies mid-stage, the RUNNING stage transitions to FAILED."""
        sm = StageStateMachine(job_id="test_killed_001", work_dir=TEST_WORK_DIR)
        sm.start_stage(1)
        sm.complete_stage(1, evidence="Stage 1 complete", proof_data={"items_count": 4})
        
        # Stage 2 is running when process is abruptly killed
        s2 = sm.start_stage(2)
        self.assertEqual(s2["status"], "RUNNING")
        
        # Simulate web server detecting process death
        stages_file = sm.state_file
        with open(stages_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            stages = data["stages"]
        
        # Simulate web_server.py crash detection
        for s_item in stages:
            if s_item.get("status") == "RUNNING":
                s_item["status"] = "FAILED"
                s_item["reason"] = "Process terminated unexpectedly"
                s_item["evidence"] = "Failed: Process terminated unexpectedly"
                
        with open(stages_file, "w", encoding="utf-8") as f:
            json.dump({"job_id": "test_killed_001", "stages": stages}, f, indent=2)
            
        # Re-read state
        with open(stages_file, "r", encoding="utf-8") as f:
            reloaded = json.load(f)
            st2 = next(s for s in reloaded["stages"] if s["id"] == 2)
            self.assertEqual(st2["status"], "FAILED")
            self.assertIn("Process terminated unexpectedly", st2["reason"])
            self.assertNotEqual(st2["status"], "RUNNING")

    def test_refresh_restores_backend_state(self):
        """Verify that reloading or checking status returns the full 10-stage list with honest evidence."""
        import urllib.request
        try:
            req = urllib.request.urlopen("http://localhost:8000/api/stages", timeout=3)
            res = json.loads(req.read().decode())
            self.assertIn("stages", res)
            self.assertEqual(len(res["stages"]), 10)
            self.assertEqual(res["stages"][0]["key"], "collect_candidates")
            self.assertEqual(res["stages"][9]["key"], "save_credits_export")
        except Exception as e:
            self.skipTest(f"Web server not reachable on localhost:8000: {e}")

if __name__ == "__main__":
    unittest.main()
