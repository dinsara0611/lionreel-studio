"""
tests/test_safe_cleanup.py — Phase 5 Safe Clean-Up Unit & Integration Tests.

Verifies all Phase 5e requirements:
1. Protected files are never in the candidate list (tested against a fake production tree):
   - finished production videos & their reports/mapping/credits/qa files
   - clip ledger database (clip_ledger.db, feedback.db)
   - verified bank clips and sources with licence and creator data
   - config files (config.json, config/*.json)
   - channel analytics
   - thumbnails of finished videos
   - the current active job
2. A resumable job's clips ("Waiting" or "Interrupted") are kept.
3. Dry run mode deletes nothing (dry_run=True).
4. Confirmation is required (confirmed=False refuses to delete).
5. The audit log (cleanup_log.json) lists every removed path.
6. Undo works with the Recycle Bin option (moves a real temp file to Windows Recycle Bin and restores it).
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from safe_cleanup import SafeCleanupManager, send_to_recycle_bin


def _build_fake_production_tree(root: str):
    """Build a realistic fake production workspace tree with protected and candidate items."""
    os.makedirs(root, exist_ok=True)

    # --- PROTECTED ASSETS ---
    # 1. Config files & analytics & credits registry
    os.makedirs(os.path.join(root, "config"), exist_ok=True)
    p_config_main = os.path.join(root, "config.json")
    p_config_sub = os.path.join(root, "config", "platform_limits.json")
    p_analytics = os.path.join(root, "channel_analytics.json")
    p_credits_reg = os.path.join(root, "credits_registry.csv")
    for fp in (p_config_main, p_config_sub, p_analytics, p_credits_reg):
        with open(fp, "w", encoding="utf-8") as f:
            f.write('{"protected": true}')

    # 2. Clip ledger DB & verified bank sources
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    p_ledger = os.path.join(root, "data", "clip_ledger.db")
    p_feedback = os.path.join(root, "data", "feedback.db")
    with open(p_feedback, "wb") as f:
        f.write(b"SQLite format 3\x00feedback")

    os.makedirs(os.path.join(root, "raw"), exist_ok=True)
    os.makedirs(os.path.join(root, "cache"), exist_ok=True)
    p_verified_src = os.path.join(root, "cache", "cache_VERIFIED123.mp4")
    p_verified_meta = os.path.join(root, "cache", "cache_VERIFIED123.info.json")
    with open(p_verified_src, "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypmp42_verified_source_content" * 100)
    with open(p_verified_meta, "w", encoding="utf-8") as f:
        json.dump({"creator": "CatChannel", "license": "CC-BY"}, f)

    # Rejected source in cache (should be a candidate!)
    c_rejected_src = os.path.join(root, "cache", "cache_REJECTED999.mp4")
    with open(c_rejected_src, "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypmp42_rejected_source" * 50)

    # Populate SQLite clip_ledger.db
    conn = sqlite3.connect(p_ledger)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE sources (source_id TEXT PRIMARY KEY, local_path TEXT, rejection_reason TEXT, status TEXT, creator TEXT, license TEXT)"
    )
    cur.execute(
        "CREATE TABLE clip_windows (window_id TEXT PRIMARY KEY, source_id TEXT, local_path TEXT, status TEXT, qa_passed INTEGER)"
    )
    cur.execute(
        "INSERT INTO sources VALUES ('VERIFIED123', ?, NULL, 'verified', 'CatCreator', 'CC-BY-3.0')",
        (p_verified_src,),
    )
    cur.execute(
        "INSERT INTO clip_windows VALUES ('w1', 'VERIFIED123', ?, 'verified', 1)",
        (p_verified_src,),
    )
    cur.execute(
        "INSERT INTO sources VALUES ('REJECTED999', ?, 'low_sharpness', 'rejected', '', '')",
        (c_rejected_src,),
    )
    conn.commit()
    conn.close()

    # 3. Finished production video + reports, mapping, credits, qa, thumbnail
    os.makedirs(os.path.join(root, "finished"), exist_ok=True)
    prod_job_id = "lionreel_cat_20261031_120000_prod1111"
    p_prod_vid = os.path.join(root, "finished", f"{prod_job_id}.mp4")
    p_prod_thumb = os.path.join(root, "finished", f"{prod_job_id}_thumb.jpg")
    p_prod_credits = os.path.join(root, "finished", f"{prod_job_id}.txt")
    for fp in (p_prod_vid, p_prod_thumb, p_prod_credits):
        with open(fp, "wb") as f:
            f.write(b"PRODUCTION_ASSET_" * 80)

    p_out_dir = os.path.join(root, "output", prod_job_id)
    os.makedirs(p_out_dir, exist_ok=True)
    p_qa = os.path.join(p_out_dir, "qa_report.json")
    p_map = os.path.join(p_out_dir, "clip_mapping.json")
    p_rep_html = os.path.join(p_out_dir, "production_report.html")
    p_rep_pdf = os.path.join(p_out_dir, "production_report.pdf")
    p_jc = os.path.join(p_out_dir, "job_config.json")
    for fp in (p_qa, p_map, p_rep_html, p_rep_pdf):
        with open(fp, "w", encoding="utf-8") as f:
            f.write('{"verdict": "PASSED"}')
    with open(p_jc, "w", encoding="utf-8") as f:
        json.dump({"job_id": prod_job_id, "is_test": False}, f)

    # 4. Current running job
    current_job_id = "lionreel_cat_20261101_140000_active22"
    p_active_work = os.path.join(root, "work", current_job_id)
    os.makedirs(os.path.join(p_active_work, "clips"), exist_ok=True)
    p_active_clip = os.path.join(p_active_work, "clips", "clip_00.mp4")
    with open(p_active_clip, "wb") as f:
        f.write(b"ACTIVE_JOB_CLIP" * 50)

    # 5. Resumable Waiting / Interrupted job (rendered clips MUST be kept!)
    resumable_job_id = "lionreel_cat_20261101_130000_waiting3"
    p_resumable_work = os.path.join(root, "work", resumable_job_id)
    os.makedirs(os.path.join(p_resumable_work, "clips"), exist_ok=True)
    p_resumable_clip = os.path.join(p_resumable_work, "clips", "clip_01_rendered.mp4")
    with open(p_resumable_clip, "wb") as f:
        f.write(b"RESUMABLE_RENDERED_CLIP_DATA" * 100)
    p_resumable_manifest = os.path.join(p_resumable_work, "clips_rendered.json")
    with open(p_resumable_manifest, "w", encoding="utf-8") as f:
        json.dump({"rendered": ["clip_01_rendered.mp4"]}, f)
    p_resumable_jr = os.path.join(p_resumable_work, "job_result.json")
    with open(p_resumable_jr, "w", encoding="utf-8") as f:
        json.dump({"status": "waiting_for_footage", "resumable": True}, f)

    # --- CANDIDATE (DELETABLE) ITEMS ---
    # a) Finished/failed job work folder
    c_failed_work = os.path.join(root, "work", "lionreel_cat_20261020_failed99")
    os.makedirs(c_failed_work, exist_ok=True)
    with open(os.path.join(c_failed_work, "job_result.json"), "w", encoding="utf-8") as f:
        json.dump({"status": "failed"}, f)
    with open(os.path.join(c_failed_work, "temp_chunk.mp4"), "wb") as f:
        f.write(b"FAILED_WORK_TEMP" * 60)

    # b) Intermediate render files
    c_inter_1 = os.path.join(root, "assembled_temp_123.mp4")
    c_inter_2 = os.path.join(root, "raw", "master_audio_mix.wav")
    c_inter_3 = os.path.join(root, "TEMP_MPY_wvf_snd.mp4")
    for fp in (c_inter_1, c_inter_2, c_inter_3):
        with open(fp, "wb") as f:
            f.write(b"INTERMEDIATE_RENDER_BYTES" * 40)

    # c) Test/sandbox outputs
    c_test_vid = os.path.join(root, "finished", "sandbox_test_short_30s.mp4")
    with open(c_test_vid, "wb") as f:
        f.write(b"SANDBOX_TEST_VIDEO" * 40)

    # d) Preview & contact-sheet caches older than 14 days
    os.makedirs(os.path.join(root, "previews"), exist_ok=True)
    c_old_preview = os.path.join(root, "previews", "old_preview_clip.mp4")
    with open(c_old_preview, "wb") as f:
        f.write(b"OLD_PREVIEW_DATA" * 30)
    old_20d = time.time() - (20 * 86400)
    os.utime(c_old_preview, (old_20d, old_20d))

    # e) Old logs older than 30 days (with 12 total logs so 10 newest are kept, oldest >30d is candidate)
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    kept_logs = []
    for i in range(10):
        lp = os.path.join(root, "logs", f"job_recent_{i:02d}.log")
        with open(lp, "w", encoding="utf-8") as f:
            f.write(f"recent log {i}")
        t = time.time() - (i * 3600)
        os.utime(lp, (t, t))
        kept_logs.append(lp)

    c_old_log = os.path.join(root, "logs", "job_ancient_45days.log")
    with open(c_old_log, "w", encoding="utf-8") as f:
        f.write("ancient log content")
    old_45d = time.time() - (45 * 86400)
    os.utime(c_old_log, (old_45d, old_45d))

    # f) Duplicate file with identical SHA-256 hash
    os.makedirs(os.path.join(root, "duplicates"), exist_ok=True)
    c_dup_copy = os.path.join(root, "duplicates", "cache_VERIFIED123_copy.mp4")
    shutil.copy2(p_verified_src, c_dup_copy)

    # g) Empty folder
    c_empty_dir = os.path.join(root, "work", "empty_leftover_dir")
    os.makedirs(c_empty_dir, exist_ok=True)

    # h) Python cache folder
    c_pycache = os.path.join(root, "some_pkg", "__pycache__")
    os.makedirs(c_pycache, exist_ok=True)
    with open(os.path.join(c_pycache, "mod.cpython-312.pyc"), "wb") as f:
        f.write(b"PYC_BYTECODE" * 20)

    protected_paths = [
        p_config_main,
        p_config_sub,
        p_analytics,
        p_credits_reg,
        p_ledger,
        p_feedback,
        p_verified_src,
        p_verified_meta,
        p_prod_vid,
        p_prod_thumb,
        p_prod_credits,
        p_qa,
        p_map,
        p_rep_html,
        p_rep_pdf,
        p_jc,
        p_active_clip,
        p_resumable_clip,
        p_resumable_manifest,
        p_resumable_jr,
    ] + kept_logs

    candidate_paths = {
        "temp_work_folders": c_failed_work,
        "intermediate_renders": c_inter_1,
        "rejected_unreferenced_cache": c_rejected_src,
        "test_sandbox_outputs": c_test_vid,
        "old_preview_caches": c_old_preview,
        "old_logs": c_old_log,
        "duplicate_files": c_dup_copy,
        "empty_folders": c_empty_dir,
        "python_cache": c_pycache,
    }

    return current_job_id, protected_paths, candidate_paths


class TestSafeCleanupSuite(unittest.TestCase):
    def test_protected_files_never_in_candidate_list_and_resumable_kept(self):
        tmp_dir = tempfile.mkdtemp(prefix="lionreel_cleanup_test1_")
        try:
            current_job_id, protected_paths, candidate_paths = _build_fake_production_tree(tmp_dir)
            mgr = SafeCleanupManager(base_dir=tmp_dir, local_data_dir=tmp_dir, current_job_id=current_job_id)
            scan = mgr.scan_candidates()
            self.assertTrue(scan["success"])

            all_candidate_files = set()
            group_by_id = {}
            for g in scan["groups"]:
                group_by_id[g["group_id"]] = g
                for item in g["files"]:
                    all_candidate_files.add(os.path.normcase(os.path.abspath(item["path"])))

            # Verify EVERY protected file is strictly excluded from candidates
            for pp in protected_paths:
                norm_pp = os.path.normcase(os.path.abspath(pp))
                self.assertNotIn(norm_pp, all_candidate_files, f"Protected path leaked into candidates: {pp}")
                for cand in all_candidate_files:
                    self.assertFalse(
                        norm_pp.startswith(cand + os.sep),
                        f"Parent directory {cand} of protected file {pp} was offered for deletion!",
                    )

            # Verify all 9 candidate groups detected their expected candidate item
            for gid, expected_path in candidate_paths.items():
                norm_exp = os.path.normcase(os.path.abspath(expected_path))
                group_paths = {
                    os.path.normcase(os.path.abspath(x["path"])) for x in group_by_id[gid]["files"]
                }
                self.assertIn(norm_exp, group_paths, f"Expected candidate {expected_path} missing from group {gid}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_dry_run_deletes_nothing_and_confirm_required(self):
        tmp_dir = tempfile.mkdtemp(prefix="lionreel_cleanup_test2_")
        try:
            current_job_id, protected_paths, candidate_paths = _build_fake_production_tree(tmp_dir)
            mgr = SafeCleanupManager(base_dir=tmp_dir, local_data_dir=tmp_dir, current_job_id=current_job_id)

            # 1. Unconfirmed execution must be rejected without deleting anything
            res_unconfirmed = mgr.execute_cleanup(dry_run=False, confirmed=False)
            self.assertFalse(res_unconfirmed["success"])
            for gid, cpath in candidate_paths.items():
                self.assertTrue(os.path.exists(cpath), f"Unconfirmed run deleted {cpath}")

            # 2. Dry run must simulate and log paths, but delete nothing on disk
            res_dry = mgr.execute_cleanup(dry_run=True, confirmed=False)
            self.assertTrue(res_dry["success"])
            self.assertTrue(res_dry["dry_run"])
            self.assertGreaterEqual(res_dry["removed_count"], 9)
            for gid, cpath in candidate_paths.items():
                self.assertTrue(os.path.exists(cpath), f"Dry run deleted {cpath}!")

            log_path = os.path.join(tmp_dir, "cleanup_log.json")
            self.assertTrue(os.path.isfile(log_path))
            with open(log_path, "r", encoding="utf-8") as f:
                log_data = json.load(f)
            self.assertTrue(log_data["last_run"]["dry_run"])
            self.assertEqual(len(log_data["last_run"]["removed_paths"]), res_dry["removed_count"])

            # 3. Confirmed real run removes candidates, keeps all protected
            res_real = mgr.execute_cleanup(dry_run=False, use_recycle_bin=False, confirmed=True)
            self.assertTrue(res_real["success"])
            self.assertGreaterEqual(res_real["removed_count"], 9)

            for pp in protected_paths:
                self.assertTrue(os.path.exists(pp), f"Protected file was deleted during cleanup: {pp}")

            for gid, cpath in candidate_paths.items():
                self.assertFalse(os.path.exists(cpath), f"Candidate {cpath} in {gid} was not removed")

            with open(log_path, "r", encoding="utf-8") as f:
                log_data2 = json.load(f)
            logged_paths = {os.path.normcase(os.path.abspath(p)) for p in log_data2["last_run"]["removed_paths"]}
            for gid, cpath in candidate_paths.items():
                self.assertIn(os.path.normcase(os.path.abspath(cpath)), logged_paths)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_recycle_bin_undo_roundtrip(self):
        test_dir = r"C:\LionReel\work\recycle_undo_test"
        os.makedirs(test_dir, exist_ok=True)
        unique_name = f"lionreel_recycle_undo_{int(time.time() * 1000)}.txt"
        test_file = os.path.join(test_dir, unique_name)
        payload = "RECYCLE_BIN_ROUNDTRIP_VERIFICATION_CONTENT"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(payload)

        self.assertTrue(os.path.isfile(test_file))

        ok, msg = send_to_recycle_bin(test_file)
        self.assertTrue(ok, f"send_to_recycle_bin failed: {msg}")
        self.assertFalse(os.path.exists(test_file), "File still exists after send_to_recycle_bin")

        ps_restore = f"""
        $shell = New-Object -ComObject Shell.Application
        $rb = $shell.Namespace(10)
        $item = $rb.Items() | Where-Object {{ $_.Name -like '{unique_name}*' }} | Select-Object -First 1
        if ($null -eq $item) {{
            Write-Error "Item not found in Recycle Bin"
            exit 1
        }}
        $destFolder = $shell.Namespace('{test_dir}')
        $destFolder.MoveHere($item, 16)
        """
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_restore],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, f"Recycle bin restore failed: {proc.stderr}")
        self.assertTrue(os.path.isfile(test_file), "File was not restored from Recycle Bin")
        with open(test_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), payload)

        os.remove(test_file)
        try:
            os.rmdir(test_dir)
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
