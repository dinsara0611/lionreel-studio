import os
import re
import json

def parse_job_log(jid):
    p = os.path.join(r"C:\LionReel\work", jid, "job.log")
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    return lines

for jid in ["trace_normal_1791527853", "trace_fresh_1791528140"]:
    lines = parse_job_log(jid)
    print(f"=== {jid} ({len(lines)} lines) ===")
    for l in lines:
        if any(k in l for k in ["[STAGE", "STAGE A", "STAGE B", "Mastering audio", "Rendering final", "QA", "Starting production", "BATCH COMPLETE", "Post-Crop"]):
            print(l.strip())
