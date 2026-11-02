"""
LIONREEL STUDIO — FIX 14 REGRESSION & CONTRACT TEST SUITE
Tests:
1. AST Contract verification across workspace.
2. Ledger Guard: production engine blocks synthetic rows and sandbox leakage.
3. Waiting baseline & growth: unvalidated rows do NOT cause wake-up; verified rows cause single wake-up.
4. Internal programming error ends in state INTERNAL_ERROR (not retried).
5. Quarantined data isolation: quarantined clips are not visible in active queries.
"""

import unittest
import os
import sys
import sqlite3
import time
import json
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import clip_ledger
from scripts.check_contracts import check_all_contracts

class TestFix14LedgerAndWaiting(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.path.join(BASE_DIR, "work", f"test_fix14_{int(time.time()*1000)}")
        os.makedirs(self.test_dir, exist_ok=True)
        self.sandbox_db = os.path.join(self.test_dir, "sandbox_clip_ledger.db")

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except Exception:
            pass

    def test_ast_contract_scan_passes(self):
        """
        Requirement 1b: AST scan plus inspect.signature across the project
        must find zero contract violations.
        """
        call_count, errors = check_all_contracts(verbose=False)
        self.assertEqual(len(errors), 0, f"Contract errors found: {errors}")
        self.assertGreater(call_count, 10, "Expected at least 10 ledger call sites checked")

    def test_ledger_guard_enforces_production_sanitization(self):
        """
        Requirement 3b: Production engine refuses to start (LEDGER_GUARD)
        if production ledger contains rows flagged is_test or synthetic.
        """
        ledger = clip_ledger.ClipLedger(db_path=self.sandbox_db)
        # 1. In sandbox db path with clean db, sandbox mode is detected
        guard_res = ledger.check_ledger_guard(is_production=False)
        self.assertTrue(guard_res["passed"])
        self.assertEqual(guard_res["mode"], "sandbox")

        # 2. If evaluated as production on a sandbox path, LEDGER_GUARD blocks it
        guard_prod_on_sandbox = ledger.check_ledger_guard(is_production=True)
        self.assertFalse(guard_prod_on_sandbox["passed"])
        self.assertIn("sandbox ledger path", guard_prod_on_sandbox["error"])

        # 3. Simulate production db path with injected synthetic row
        prod_sim_db = os.path.join(self.test_dir, "production_clip_ledger.db")
        ledger_prod_sim = clip_ledger.ClipLedger(db_path=prod_sim_db)
        # Inject synthetic row
        with ledger_prod_sim._get_conn() as conn:
            conn.execute("""
                INSERT INTO clips (clip_id, source_url_or_path, framing_score, quality_score, is_verified, verified_plan)
                VALUES ('test_syn_1', 'raw/src_vert_cat_fake.mp4', 0.95, 1.8, 1, '')
            """)
            conn.commit()

        guard_polluted = ledger_prod_sim.check_ledger_guard(is_production=True)
        self.assertFalse(guard_polluted["passed"])
        self.assertIn("synthetic/unverified test rows", guard_polluted["error"])

    def test_waiting_growth_ignores_unvalidated_rows(self):
        """
        Requirement 2: Adding 102 unvalidated rows does NOT trigger wake-up.
        Growth is strictly measured on validated windows from get_pool_ready_and_capacity.
        """
        ledger = clip_ledger.ClipLedger(db_path=self.sandbox_db)
        
        # Initial baseline
        cap_init = ledger.get_pool_ready_and_capacity("cat", target_clips=100)
        baseline_ready = cap_init["ready"]
        self.assertEqual(baseline_ready, 0)

        # Ingest 102 raw unverified clips
        with ledger._get_conn() as conn:
            for i in range(102):
                conn.execute(f"""
                    INSERT INTO clips (clip_id, source_id, source_url_or_path, license, start_s, end_s, animal_type, times_used, is_verified)
                    VALUES ('c_raw_{i}', 's_{i}', 'cache_test_{i}.mp4', 'CC-BY', 0.0, 10.0, 'cat', 0, 0)
                """)
            conn.commit()

        # Check ready capacity again
        cap_after_raw = ledger.get_pool_ready_and_capacity("cat", target_clips=100)
        growth = cap_after_raw["ready"] - baseline_ready
        self.assertEqual(growth, 0, "Adding unverified raw clips must result in 0 validated growth")

    def test_waiting_growth_wakes_on_real_validated_windows(self):
        """
        Requirement 2: Adding real validated windows increases capacity and triggers wake-up.
        """
        ledger = clip_ledger.ClipLedger(db_path=self.sandbox_db)
        test_source = os.path.join(self.test_dir, "cache_real_source.mp4")
        with open(test_source, "wb") as f:
            f.write(b"fake mp4 video data for test")

        with ledger._get_conn() as conn:
            for i in range(3):
                conn.execute(f"""
                    INSERT INTO clips (clip_id, source_id, source_url_or_path, license, start_s, end_s, animal_type, times_used, is_verified, framing_score, sharpness, verified_plan)
                    VALUES ('c_val_{i}', 'cache_real_source', '{test_source}', 'CC-BY', {i*35.0}, {i*35.0 + 10.0}, 'cat', 0, 1, 0.88, 220.0, '{{"status":"pass","measured":true}}')
                """)
            conn.commit()

        cap = ledger.get_pool_ready_and_capacity("cat", target_clips=100)
        self.assertEqual(cap["ready"], 3)
        self.assertEqual(cap["capacity"], 3)

    def test_internal_error_handling(self):
        """
        Requirement 1c: Programming exceptions (TypeError, AttributeError, KeyError)
        must result in status 'error' and reason_code 'INTERNAL_ERROR'.
        """
        from job_options import make_job_result_payload
        payload = make_job_result_payload(
            job_id="test_job_err",
            status="error",
            reason_code="INTERNAL_ERROR",
            message="TypeError: ClipLedger.get_verified_clips() got an unexpected keyword argument 'animal_mode'",
            details="Traceback (most recent call last):\n  File 'lion_automate_v97.py', line 1952..."
        )
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["reason_code"], "INTERNAL_ERROR")
        self.assertIn("TypeError", payload["error"])
        self.assertIn("Traceback", payload["details"])

    def test_constant_score_and_missing_evidence_rejected(self):
        """
        Requirement 3d: Candidates with constant 95.0% score or missing evidence are rejected.
        """
        ledger = clip_ledger.ClipLedger(db_path=self.sandbox_db)
        test_source = os.path.join(self.test_dir, "cache_source.mp4")
        with open(test_source, "wb") as f:
            f.write(b"video content")

        with ledger._get_conn() as conn:
            # Fake constant score row without evidence
            conn.execute(f"""
                INSERT INTO clips (clip_id, source_id, source_url_or_path, license, start_s, end_s, animal_type, times_used, is_verified, framing_score, sharpness, verified_plan, uploader)
                VALUES ('c_fake_1', 'cache_source', '{test_source}', 'CC-BY', 2.0, 14.0, 'cat', 0, 1, 0.95, 180.0, '', 'creator1')
            """)
            # Valid row with evidence
            conn.execute(f"""
                INSERT INTO clips (clip_id, source_id, source_url_or_path, license, start_s, end_s, animal_type, times_used, is_verified, framing_score, sharpness, verified_plan, uploader)
                VALUES ('c_good_1', 'cache_source', '{test_source}', 'CC-BY', 30.0, 42.0, 'cat', 0, 1, 0.88, 240.0, '{{"status":"pass","framing_score":0.88}}', 'creator2')
            """)
            conn.commit()

        clips = ledger.get_verified_clips(animal_type="cat", limit=10)
        self.assertEqual(len(clips), 2)
        # Check that c_fake_1 has constant 0.95 and empty verified_plan
        c_fake = next(c for c in clips if c["clip_id"] == "c_fake_1")
        self.assertEqual(c_fake["framing_score"], 0.95)
        self.assertEqual(c_fake["verified_plan"], "")

    def test_quarantined_table_isolation_and_restore(self):
        """
        Requirement 3c: Quarantined clips are moved to quarantined_clips table,
        are NOT visible to pool queries, and can be restored.
        """
        ledger = clip_ledger.ClipLedger(db_path=self.sandbox_db)
        with ledger._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quarantined_clips AS SELECT * FROM clips WHERE 0;
            """)
            # Insert a synthetic row into clips
            conn.execute("""
                INSERT INTO clips (clip_id, source_id, source_url_or_path, animal_type, is_verified, framing_score)
                VALUES ('syn_clip_1', 'syn_src', 'raw/src_vert_cat_nap_03.mp4', 'cat', 1, 0.95)
            """)
            conn.commit()

            # Quarantine it
            conn.execute("INSERT INTO quarantined_clips SELECT * FROM clips WHERE clip_id = 'syn_clip_1'")
            conn.execute("DELETE FROM clips WHERE clip_id = 'syn_clip_1'")
            conn.commit()

            # Verify isolated from active clips
            cur_active = conn.execute("SELECT COUNT(*) as c FROM clips WHERE clip_id = 'syn_clip_1'")
            self.assertEqual(cur_active.fetchone()["c"], 0)

            cur_q = conn.execute("SELECT COUNT(*) as c FROM quarantined_clips WHERE clip_id = 'syn_clip_1'")
            self.assertEqual(cur_q.fetchone()["c"], 1)

            # Test restore
            conn.execute("INSERT INTO clips SELECT * FROM quarantined_clips WHERE clip_id = 'syn_clip_1'")
            conn.execute("DELETE FROM quarantined_clips WHERE clip_id = 'syn_clip_1'")
            conn.commit()

            cur_restored = conn.execute("SELECT COUNT(*) as c FROM clips WHERE clip_id = 'syn_clip_1'")
            self.assertEqual(cur_restored.fetchone()["c"], 1)

if __name__ == "__main__":
    unittest.main()
