import json

with open("job_result.json", "r", encoding="utf-8") as f:
    jr = json.load(f)

reports = jr.get("candidate_reports", [])
print(f"Total candidate reports in job_result.json: {len(reports)}")
pass_count = 0
for r in reports:
    print(f"Cand {r.get('candidate')}: {r.get('clip_id')} [{r.get('start_s')}s] score={r.get('score')} => {r.get('result')}: {r.get('reason')}")
    if r.get("result") == "PASS":
        pass_count += 1

print(f"Total passing: {pass_count}")
