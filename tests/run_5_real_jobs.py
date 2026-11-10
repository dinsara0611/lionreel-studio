#!/usr/bin/env python3
"""
Test Runner: 5 Consecutive Real Production Runs
==============================================
Runs the production pipeline 5 times with:
  --mode cat --type short --clips 4 --clip-time 10.0 --layout smart_crop

Collects:
  - Job ID
  - Execution Duration
  - Clips Rendered & Assembled
  - Centering Scores
  - Sharpness Scores
  - 10-Gate QA Status
  - Final MP4 Filename & Size
  - Contact Sheet Path
  - credits.json Contents
"""

import os
import sys
import time
import json
import subprocess
import glob

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINISHED_DIR = os.path.join(BASE_DIR, "finished")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from clip_ledger import ClipLedger

def run_job(index, total=5):
    try:
        ClipLedger().cleanup_stale_reservations()
    except Exception:
        pass
    print(f"\n========================================================")
    print(f"  STARTING REAL PRODUCTION RUN {index} OF {total}")
    print(f"========================================================")
    
    cmd = [
        sys.executable,
        os.path.join(BASE_DIR, "lion_automate_v97.py"),
        "--mode", "cat",
        "--type", "short",
        "--clips", "4",
        "--clip-time", "10.0",
        "--layout", "smart_crop",
        "--allow-shorter",
        "--allow-reuse"
    ]
    
    start_time = time.time()
    proc = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True)
    duration = round(time.time() - start_time, 2)
    
    stdout = proc.stdout
    stderr = proc.stderr
    
    # Extract Job ID
    job_id = None
    for line in stdout.splitlines():
        if "Starting production:" in line:
            parts = line.split("Starting production:")
            if len(parts) > 1:
                job_id = parts[1].strip().split()[0]
                break
        elif "LIONREEL V97 PIPELINE INITIALIZED" in line:
            pass
        elif "lionreel_cat_" in line:
            import re
            m = re.search(r'(lionreel_cat_\d+_\d+_[a-f0-9]+)', line)
            if m:
                job_id = m.group(1)
                
    if not job_id:
        # Check latest folder in output
        job_dirs = sorted(glob.glob(os.path.join(OUTPUT_DIR, "lionreel_cat_*")), key=os.path.getmtime, reverse=True)
        if job_dirs:
            job_id = os.path.basename(job_dirs[0])
            
    print(f"Run {index}: Completed with code {proc.returncode} in {duration}s. Job ID: {job_id}")
    
    # Collect artifacts
    mp4_path = os.path.join(FINISHED_DIR, f"{job_id}.mp4") if job_id else None
    mp4_exists = os.path.exists(mp4_path) if mp4_path else False
    mp4_size_mb = round(os.path.getsize(mp4_path) / (1024 * 1024), 2) if mp4_exists else 0.0
    
    qa_path = os.path.join(FINISHED_DIR, f"{job_id}_qa_report.json") if job_id else None
    qa_data = {}
    if qa_path and os.path.exists(qa_path):
        try:
            with open(qa_path, "r", encoding="utf-8") as f:
                qa_data = json.load(f)
        except Exception as e:
            print(f"Error loading QA report: {e}")
            
    credits_path = os.path.join(FINISHED_DIR, f"{job_id}_credits.json") if job_id else None
    credits_data = []
    if credits_path and os.path.exists(credits_path):
        try:
            with open(credits_path, "r", encoding="utf-8") as f:
                credits_data = json.load(f)
        except Exception as e:
            print(f"Error loading credits: {e}")

    mapping_path = os.path.join(FINISHED_DIR, f"{job_id}_mapping.json") if job_id else None
    mapping_data = {}
    if mapping_path and os.path.exists(mapping_path):
        try:
            with open(mapping_path, "r", encoding="utf-8") as f:
                mapping_data = json.load(f)
        except Exception as e:
            print(f"Error loading mapping: {e}")

    contact_sheet_path = os.path.join(FINISHED_DIR, f"{job_id}_contact_sheet.png") if job_id else None
    contact_sheet_exists = os.path.exists(contact_sheet_path) if contact_sheet_path else False

    # Extract detailed scores from QA or mapping
    centering_pct = None
    sharpness_median = None
    qa_passed = False
    qa_gates_passed = 0
    total_gates = 10
    
    if qa_data:
        qa_passed = qa_data.get("overall_passed", False)
        gates = qa_data.get("gates", {})
        if gates:
            qa_gates_passed = sum(1 for g in gates.values() if g.get("passed", False))
            pet_gate = gates.get("pet_tracking_and_centering", {})
            centering_pct = pet_gate.get("pet_presence_ratio", None)
            if centering_pct is not None:
                centering_pct = round(centering_pct * 100, 1)
            sharp_gate = gates.get("per_clip_sharpness", {})
            sharpness_median = sharp_gate.get("overall_median_sharpness", None)
        else:
            gate_keys = ["stream_specs", "defects", "loudness", "pet_centering", "layout_fill", "watermark_gate", "cartoon_classifier", "sharpness", "captions", "source_guard"]
            qa_gates_passed = sum(1 for k in gate_keys if qa_data.get(k, {}).get("passed", False))
            c_val = qa_data.get("pet_centering", {}).get("compliance_ratio", None)
            if c_val is not None:
                centering_pct = round(c_val * 100, 1)
            sharpness_median = qa_data.get("sharpness", {}).get("median_sharpness", None)
        
    clips_count = len(mapping_data.get("clips", []))
    
    result = {
        "run_index": index,
        "job_id": job_id,
        "returncode": proc.returncode,
        "duration_sec": duration,
        "mp4_exists": mp4_exists,
        "mp4_path": mp4_path,
        "mp4_size_mb": mp4_size_mb,
        "clips_count": clips_count,
        "qa_passed": qa_passed,
        "qa_gates_passed": qa_gates_passed,
        "total_gates": total_gates,
        "centering_pct": centering_pct,
        "sharpness_median": sharpness_median,
        "contact_sheet_exists": contact_sheet_exists,
        "contact_sheet_path": contact_sheet_path,
        "credits_count": len(credits_data) if isinstance(credits_data, list) else len(credits_data.get("credits", [])),
        "credits": credits_data,
        "stdout_tail": stdout[-2000:] if stdout else "",
        "stderr_tail": stderr[-1000:] if stderr else ""
    }
    
    print(f"Run {index} Summary:")
    print(f"  Job ID: {job_id}")
    print(f"  MP4: {mp4_exists} ({mp4_size_mb} MB)")
    print(f"  Clips: {clips_count} assembled")
    print(f"  Duration: {duration}s")
    print(f"  QA: {'PASS' if qa_passed else 'FAIL'} ({qa_gates_passed}/{total_gates} gates)")
    print(f"  Centering: {centering_pct}%")
    print(f"  Sharpness: {sharpness_median}")
    print(f"  Contact Sheet: {contact_sheet_exists}")
    print(f"  Credits: {result['credits_count']} source creators credited")
    
    return result

def main():
    total_runs = 5
    all_results = []
    
    for i in range(1, total_runs + 1):
        res = run_job(i, total=total_runs)
        all_results.append(res)
        
    # Save results
    results_path = os.path.join(BASE_DIR, "tests", "5_real_jobs_results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
        
    print(f"\n========================================================")
    print(f"  ALL 5 PRODUCTION RUNS COMPLETED")
    print(f"========================================================")
    print(f"{'Run':<5} | {'Job ID':<35} | {'Dur(s)':<8} | {'Clips':<6} | {'QA':<6} | {'Center%':<8} | {'Sharp':<8} | {'Size':<8}")
    print("-" * 95)
    for r in all_results:
        qa_str = f"{r['qa_gates_passed']}/{r['total_gates']}" if r['qa_passed'] else f"FAIL({r['qa_gates_passed']})"
        print(f"{r['run_index']:<5} | {str(r['job_id']):<35} | {r['duration_sec']:<8.1f} | {r['clips_count']:<6} | {qa_str:<6} | {str(r['centering_pct'])+'%':<8} | {str(r['sharpness_median']):<8} | {str(r['mp4_size_mb'])+'MB':<8}")
        
    success_count = sum(1 for r in all_results if r['mp4_exists'] and r['qa_passed'])
    print(f"\nSuccess Rate: {success_count}/{total_runs} ({success_count/total_runs*100:.1f}%)")

if __name__ == "__main__":
    main()
