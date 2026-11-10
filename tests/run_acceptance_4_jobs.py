#!/usr/bin/env python3
"""
tests/run_acceptance_4_jobs.py
==============================
Executes acceptance jobs across the 4 core formats/modes:
1. Feline Long (Cat Compilation): tests --type compilation (and alias --type long)
2. Canine Short (Dog Short): tests --mode dog --type short
3. Mixed/Duo Short (Duo Short): tests --mode duo --type short
4. Both Job (Dual Render): tests --type both (long compilation + teaser short)

Collects for each run:
- Exact CLI invocation
- Return code and duration
- Exit status (zero exit code 2!)
- Last 40 lines of execution output / log
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

JOBS = [
    {
        "name": "Feline Long",
        "desc": "Cat Long Compilation (tests previously failing format)",
        "args": [
            sys.executable, "lion_automate_v97.py",
            "--mode", "cat",
            "--type", "compilation",
            "--clips", "4",
            "--clip-time", "10.0",
            "--layout", "smart_crop",
            "--allow-shorter",
            "--allow-reuse"
        ]
    },
    {
        "name": "Canine Short",
        "desc": "Dog Short Video (tests canine pipeline compatibility)",
        "args": [
            sys.executable, "lion_automate_v97.py",
            "--mode", "dog",
            "--type", "short",
            "--clips", "4",
            "--clip-time", "10.0",
            "--layout", "smart_crop",
            "--allow-shorter",
            "--allow-reuse"
        ]
    },
    {
        "name": "Mixed/Duo Short",
        "desc": "Cat & Dog Duo Short (tests duo mode alias compatibility)",
        "args": [
            sys.executable, "lion_automate_v97.py",
            "--mode", "duo",
            "--type", "short",
            "--clips", "4",
            "--clip-time", "10.0",
            "--layout", "smart_crop",
            "--allow-shorter",
            "--allow-reuse"
        ]
    },
    {
        "name": "Both Job",
        "desc": "Dual Render: Long compilation + linked teaser short",
        "args": [
            sys.executable, "lion_automate_v97.py",
            "--mode", "cat",
            "--type", "both",
            "--clips", "4",
            "--clip-time", "10.0",
            "--layout", "smart_crop",
            "--allow-shorter",
            "--allow-reuse"
        ]
    }
]

def run_acceptance_suite():
    print("=" * 70)
    print("  RUNNING 4-JOB ACCEPTANCE SUITE (FELINE LONG, CANINE SHORT, DUO, BOTH)")
    print("=" * 70)

    try:
        ClipLedger().cleanup_stale_reservations()
    except Exception:
        pass

    results = []

    for idx, job_cfg in enumerate(JOBS, 1):
        name = job_cfg["name"]
        print(f"\n[{idx}/4] Starting: {name} - {job_cfg['desc']}")
        print(f"Command: {' '.join(job_cfg['args'])}")

        t0 = time.time()
        proc = subprocess.run(
            job_cfg["args"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True
        )
        elapsed = round(time.time() - t0, 2)

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        combined = stdout + ("\n--- STDERR ---\n" + stderr if stderr else "")
        all_lines = combined.strip().splitlines()
        last_40_lines = all_lines[-40:] if len(all_lines) >= 40 else all_lines

        print(f"Result: returncode={proc.returncode} in {elapsed}s")
        assert proc.returncode != 2, f"FATAL REGRESSION: Job {name} failed with exit code 2 (unrecognized argument)!"

        job_result = {
            "name": name,
            "desc": job_cfg["desc"],
            "command": " ".join(job_cfg["args"]),
            "returncode": proc.returncode,
            "elapsed_sec": elapsed,
            "success": proc.returncode == 0,
            "last_40_lines": last_40_lines
        }
        results.append(job_result)

    report_path = os.path.join(BASE_DIR, "tests", "acceptance_4_jobs_results.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 70)
    print("  ACCEPTANCE SUITE SUMMARY")
    print("=" * 70)
    for r in results:
        status_str = "PASS [0]" if r["returncode"] == 0 else f"EXIT [{r['returncode']}]"
        print(f"  * {r['name']:<20}: {status_str:<10} ({r['elapsed_sec']}s)")

    print(f"\nSaved detailed log outputs to: {report_path}")
    return results

if __name__ == "__main__":
    run_acceptance_suite()
