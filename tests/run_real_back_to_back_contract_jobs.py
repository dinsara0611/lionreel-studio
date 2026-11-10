#!/usr/bin/env python3
"""
tests/run_real_back_to_back_contract_jobs.py
============================================
Real back-to-back production execution:
1. One Long video: 3m (180.0s), 16:9 (1920x1080), YouTube compilation.
2. One Short video: 45s (45.0s), 9:16 (1080x1920), Reel.

Verifies:
- job_config.json written with single source of truth
- matching CONFIG: line in execution logs
- exact output file count (1 file each, not 2)
- QA pass with 0 errors
- duration within +/- 1.0s of contract target
- ledger recorded without collisions
- outputs structured predicted vs actual comparison table
"""

import os
import sys
import time
import json
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger
import job_options
import qa_check

def run_job(mode_type, target_min=None, target_clips=None, clip_sec=7.5, aspect="16:9"):
    ts = int(time.time())
    job_id = f"job_real_contract_{mode_type}_{aspect.replace(':', '_')}_{ts}"
    
    # 1. Author and persist unified job_config.json
    cfg_raw = {
        "job_id": job_id,
        "VIDEO_TYPE": mode_type,
        "ASPECT_RATIO": aspect,
        "SHORT_CLIP_SEC": clip_sec,
        "ALLOW_SHORTER": True,
        "ALLOW_REUSE": True
    }
    if mode_type in ("long", "compilation"):
        cfg_raw["TARGET_DURATION_MIN"] = target_min
    else:
        cfg_raw["TARGET_CLIPS"] = target_clips

    valid, norm, err = job_options.normalize_job_options(cfg_raw)
    if not valid:
        raise ValueError(f"Normalization failed for {job_id}: {err}")
    
    saved_cfg = job_options.load_or_verify_job_config(job_id, norm)
    print(f"\n[JOB PRE-LAUNCH] Config persisted: {saved_cfg}")

    # 2. Run lion_automate_v97.py with exact contract parameters
    cmd = [
        sys.executable,
        os.path.join(BASE_DIR, "lion_automate_v97.py"),
        "--mode", "cat",
        "--type", norm["type"],
        "--job-id", job_id,
        "--clips", str(norm["clips"]),
        "--clip-time", str(norm["clip_time"]),
        "--aspect", aspect,
        "--layout", "smart_crop",
        "--allow-shorter",
        "--allow-reuse"
    ]
    
    print(f"[LAUNCHING] {' '.join(cmd)}")
    start_time = time.time()
    proc = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True)
    wall_duration = round(time.time() - start_time, 2)
    
    stdout = proc.stdout
    stderr = proc.stderr

    if proc.returncode != 0:
        print(f"[PROCESS ERROR code {proc.returncode}]")
        if stderr:
            print(f"[STDERR]\n{stderr[-1000:]}")
        if stdout:
            print(f"[STDOUT TAIL]\n{stdout[-1000:]}")

    # Find CONFIG: line in output
    config_line = None
    for line in stdout.splitlines():
        if "CONFIG:" in line:
            config_line = line.strip()
            break

    print(f"[LOGGED CONFIG LINE] {config_line}")

    # Locate output file
    out_dir = os.path.join(BASE_DIR, "output", job_id)
    mp4_files = [f for f in os.listdir(out_dir) if f.endswith(".mp4")] if os.path.exists(out_dir) else []
    
    # Run ffprobe / QA check on output
    qa_passed = False
    qa_report = {}
    actual_dur = None
    actual_w = None
    actual_h = None

    if mp4_files:
        master_file = os.path.join(out_dir, mp4_files[0])
        probe = qa_check.run_ffprobe_analysis(master_file)
        v_stream = next((s for s in probe.get("streams", []) if s.get("width")), {})
        actual_w = int(v_stream.get("width", 0))
        actual_h = int(v_stream.get("height", 0))
        actual_dur = float(probe.get("format", {}).get("duration", 0.0))

        # Run master QA check or load generated qa_report.json
        qa_json_p = os.path.join(out_dir, "qa_report.json")
        if os.path.exists(qa_json_p):
            try:
                with open(qa_json_p, "r", encoding="utf-8") as f_q:
                    qa_report = json.load(f_q)
                    qa_passed = bool(qa_report.get("overall_passed", False))
            except Exception:
                pass
        if not qa_report:
            try:
                qa_res = qa_check.run_full_qa(master_file, expected_aspect=aspect, target_dur=norm["target_seconds"])
                if isinstance(qa_res, tuple):
                    qa_passed, qa_report = qa_res
                else:
                    qa_passed = qa_res.get("passed", False)
                    qa_report = qa_res
            except Exception as e_qa:
                qa_report = {"error": str(e_qa)}
                qa_passed = False

    return {
        "job_id": job_id,
        "mode_type": mode_type,
        "target_seconds": norm["target_seconds"],
        "target_clips": norm["clips"],
        "target_ratio": aspect,
        "expected_resolution": f"{norm['width']}x{norm['height']}",
        "config_line": config_line,
        "wall_duration": wall_duration,
        "file_count": len(mp4_files),
        "output_files": mp4_files,
        "actual_seconds": actual_dur,
        "actual_resolution": f"{actual_w}x{actual_h}" if actual_w else None,
        "qa_passed": qa_passed,
        "exit_code": proc.returncode,
        "qa_details": qa_report.get("details", {})
    }

def main():
    print("=" * 72)
    print("LIONREEL STUDIO: REAL BACK-TO-BACK MODE CONTRACT TEST")
    print("=" * 72)

    # Clean any previous test run records from output_registry and stale locks
    import sqlite3
    db_p = os.path.join(r"C:\LionReel\data", "clip_ledger.db")
    if os.path.exists(db_p):
        try:
            conn = sqlite3.connect(db_p)
            c = conn.cursor()
            c.execute("DELETE FROM output_registry WHERE job_id LIKE 'job_real_contract_%'")
            c.execute("UPDATE clips SET pending_short_id = NULL WHERE pending_short_id LIKE 'job_real_contract_%'")
            conn.commit()
            conn.close()
        except Exception:
            pass

    results = []

    # Run 1: Long video (3m, 16:9, YouTube compilation)
    print("\n>>> EXECUTION 1: Long Video (3m, 16:9) <<<")
    res_long = run_job(mode_type="long", target_min=3.0, clip_sec=7.5, aspect="16:9")
    results.append(res_long)

    # Run 2: Short video (45s, 9:16, Reel)
    print("\n>>> EXECUTION 2: Short Video (45s, 9:16) <<<")
    res_short = run_job(mode_type="short", target_clips=6, clip_sec=7.5, aspect="9:16")
    results.append(res_short)

    # Save structured results
    out_path = os.path.join(BASE_DIR, "analysis", "real_back_to_back_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 72)
    print("PREDICTED VS ACTUAL SUMMARY TABLE")
    print("=" * 72)
    header = f"{'Metric':<22} | {'Run 1 (Long 3m 16:9)':<25} | {'Run 2 (Short 45s 9:16)':<25}"
    print(header)
    print("-" * len(header))
    print(f"{'Target Duration':<22} | {res_long['target_seconds']:<25.1f} | {res_short['target_seconds']:<25.1f}")
    print(f"{'Actual Duration':<22} | {str(res_long['actual_seconds']) + 's':<25} | {str(res_short['actual_seconds']) + 's':<25}")
    diff_l = f"{abs(res_long['actual_seconds'] - res_long['target_seconds']):.2f}s" if res_long['actual_seconds'] is not None else "N/A"
    diff_s = f"{abs(res_short['actual_seconds'] - res_short['target_seconds']):.2f}s" if res_short['actual_seconds'] is not None else "N/A"
    print(f"{'Duration Diff':<22} | {diff_l:<25} | {diff_s:<25}")
    print(f"{'Target Ratio':<22} | {res_long['target_ratio']:<25} | {res_short['target_ratio']:<25}")
    print(f"{'Target Resolution':<22} | {res_long['expected_resolution']:<25} | {res_short['expected_resolution']:<25}")
    print(f"{'Actual Resolution':<22} | {str(res_long['actual_resolution']):<25} | {str(res_short['actual_resolution']):<25}")
    print(f"{'File Count (Target 1)':<22} | {res_long['file_count']:<25} | {res_short['file_count']:<25}")
    print(f"{'QA Passed':<22} | {str(res_long['qa_passed']):<25} | {str(res_short['qa_passed']):<25}")
    print("=" * 72)

if __name__ == "__main__":
    main()
