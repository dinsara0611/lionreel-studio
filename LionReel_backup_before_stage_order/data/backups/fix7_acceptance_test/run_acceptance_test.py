import os, sys, json, time, shutil

sys.path.insert(0, r"g:\My Drive\Cat make")
from lion_automate_v97 import LionReelV97Pipeline
from qa_check import run_full_qa

print("="*80)
print("LIONREEL ACCEPTANCE TEST: RUNNING END-TO-END PIPELINE WITH NEW GATE & CAMERA")
print("="*80)

pipeline = LionReelV97Pipeline()
t0 = time.time()
job_id = f"lionreel_cat_acceptance_fix7_{int(time.time())}"

out_video = pipeline.render_one_video(
    animal_mode="cat",
    video_type="short",
    language="en",
    job_id=job_id,
    use_cache=False,
    layout_mode="smart_crop",
    clips_count=4,
    clip_time=10.0
)
total_elapsed = round(time.time() - t0, 1)

print("\n" + "="*80)
print("ACCEPTANCE TEST EXECUTION SUMMARY")
print("="*80)

# Check job_result.json
job_res_file = r"g:\My Drive\Cat make\job_result.json"
job_res = {}
if os.path.exists(job_res_file):
    try:
        with open(job_res_file, "r", encoding="utf-8") as f:
            job_res = json.load(f)
    except Exception:
        pass

# Read timings
work_dir = os.path.join(r"C:\LionReel\work", job_id)
timings_file = os.path.join(work_dir, "timings.json")
if not os.path.exists(timings_file):
    timings_file = os.path.join(work_dir, f"{job_id}_timings.json")
if not os.path.exists(timings_file):
    timings_file = os.path.join(r"g:\My Drive\Cat make\finished", f"{job_id}_timings.json")
if not os.path.exists(timings_file):
    timings_file = os.path.join(r"g:\My Drive\Cat make\output", job_id, f"{job_id}_timings.json")
timings_data = {}
if os.path.exists(timings_file):
    try:
        with open(timings_file, "r", encoding="utf-8") as f:
            timings_data = json.load(f)
    except Exception:
        pass
timings = timings_data.get("stages", timings_data)

# Print Candidate Reports Table
candidate_reports = job_res.get("candidate_reports", [])
if candidate_reports:
    print("\n--- CANDIDATE GATE EVALUATION TABLE ---")
    print(f"{'CAND':<6} | {'SOURCE':<28} | {'START (s)':<9} | {'SCORE':<8} | {'RESULT':<8} | {'REASON'}")
    print("-" * 88)
    for c in candidate_reports:
        sc = f"{c.get('score', 0.0)*100:.1f}%" if isinstance(c.get('score'), (int, float)) else str(c.get('score', '-'))
        print(f"{c.get('candidate', 0):<6} | {c.get('source', '')[:28]:<28} | {c.get('start_s', 0.0):<9.1f} | {sc:<8} | {c.get('result', ''):<8} | {c.get('reason', '')}")
    print("-" * 88)

# Print Timing Comparison Table
print("\n--- BEFORE vs AFTER TIMING TABLE ---")
print(f"{'STAGE':<20} | {'BEFORE (FAILED RUN)':<22} | {'AFTER (NEW PIPELINE)':<22} | {'IMPROVEMENT'}")
print("-" * 78)
before_timings = {
    "total": 451.0,
    "reframe": 329.0,
    "tracking": 100.5,
    "watermark": 11.0,
    "startup_imports": 9.0
}
def get_sec(s_key):
    v = timings.get(s_key, 0.0)
    return v.get("duration_sec", 0.0) if isinstance(v, dict) else (v if isinstance(v, (int, float)) else 0.0)

after_reframe = get_sec("reframe")
after_tracking = get_sec("tracking")
after_wm = get_sec("watermark")
after_startup = get_sec("startup_imports")

for stg, b_val in before_timings.items():
    if stg == "total":
        a_val = total_elapsed
    elif stg == "reframe":
        a_val = after_reframe
    elif stg == "tracking":
        a_val = after_tracking
    elif stg == "watermark":
        a_val = after_wm
    elif stg == "startup_imports":
        a_val = after_startup
    diff = b_val - a_val
    pct = (diff / b_val) * 100 if b_val > 0 else 0
    print(f"{stg:<20} | {b_val:<22.1f}s | {a_val:<22.1f}s | -{diff:.1f}s ({pct:.0f}% faster)")
print("-" * 78)

# Verify Output and QA
if out_video and os.path.exists(out_video):
    print(f"\nFinal Video File Generated: {out_video} ({os.path.getsize(out_video)/1024/1024:.2f} MB)")
    qa_ok, qa_rep = run_full_qa(out_video)
    print(f"\nAutomated QA Result: {'PASS ✅' if qa_ok else 'FAIL ❌'}")
    print("QA Checks Summary:")
    check_keys = ["stream_specs", "defects", "loudness", "pet_centering", "layout_fill", "watermark_gate", "cartoon_classifier", "sharpness", "captions", "source_guard"]
    for ck in check_keys:
        val = qa_rep.get(ck, {})
        p = val.get("passed") if isinstance(val, dict) else val
        print(f"  - {ck}: {'PASS ✅' if p else 'FAIL ❌'}")
    
    # Check contact sheet
    cs_path = os.path.join(work_dir, f"{job_id}_contact_sheet.png")
    if os.path.exists(cs_path):
        print(f"Contact Sheet Generated: {cs_path}")

    if qa_ok:
        print(f"\nJOB SUCCESS: {out_video}")
    else:
        print(f"\nJOB FAILED: QA validation failed on {out_video}")
else:
    err = job_res.get("error", "Unknown pipeline error")
    print(f"\nJOB FAILED: {err}")
