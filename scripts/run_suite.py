"""
Runs each test file in its own pytest process with a time limit, so one hung test
cannot end the run (pytest-timeout kills the whole process on Windows).

    python scripts/run_suite.py [--limit SEC] [--out results.json] [--only substr] [file ...]

Writes per-test results as JSON. Exit code is 0 only if nothing failed.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def run_file(path, limit, junit):
    if os.path.exists(junit):
        os.remove(junit)
    cmd = [sys.executable, "-m", "pytest", path, "-q", "--tb=line", "-p", "no:cacheprovider",
           "--timeout=0", f"--junitxml={junit}"]
    started = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    try:
        out, _ = proc.communicate(timeout=limit)
        timed_out = False
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        out, _ = proc.communicate()
        timed_out = True
    tests = []
    if os.path.exists(junit) and not timed_out:
        for case in ET.parse(junit).getroot().iter("testcase"):
            status = "passed"
            message = ""
            for child in case:
                if child.tag in ("failure", "error", "skipped"):
                    status = {"failure": "failed", "error": "error", "skipped": "skipped"}[child.tag]
                    message = (child.get("message") or child.text or "")[:300]
            tests.append({"name": case.get("name"), "class": case.get("classname"), "status": status, "message": message})
    return {"file": path, "seconds": round(time.time() - started, 1), "timed_out": timed_out,
            "exit_code": proc.returncode, "tests": tests, "tail": out[-1500:] if not tests else ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--limit", type=float, default=240.0)
    ap.add_argument("--out", default="suite_results.json")
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    files = args.files or sorted(glob.glob("tests/test_*.py"))
    if args.only:
        files = [f for f in files if args.only in f]
    results = []
    junit = os.path.abspath(args.out + ".junit.xml")
    for i, path in enumerate(files, 1):
        r = run_file(path, args.limit, junit)
        results.append(r)
        n = {}
        for t in r["tests"]:
            n[t["status"]] = n.get(t["status"], 0) + 1
        print(f"[{i}/{len(files)}] {os.path.basename(path)}: {n or 'NO RESULTS'}{' TIMED OUT' if r['timed_out'] else ''} ({r['seconds']}s)", flush=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)
    total = {}
    for r in results:
        for t in r["tests"]:
            total[t["status"]] = total.get(t["status"], 0) + 1
    hung = [os.path.basename(r["file"]) for r in results if r["timed_out"] or not r["tests"]]
    print("TOTAL", total, "files with no results:", hung, flush=True)
    return 1 if total.get("failed") or total.get("error") or hung else 0


if __name__ == "__main__":
    sys.exit(main())
