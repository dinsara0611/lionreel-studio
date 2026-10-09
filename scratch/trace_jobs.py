import os
import sys
import time
import json

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from lion_automate_v97 import LionReelV97Pipeline

def run_traced_job(name, use_cache=False):
    print(f"\n{'='*80}\nRUNNING TRACED JOB: {name} (use_cache={use_cache})\n{'='*80}")
    t0 = time.time()
    pipeline = LionReelV97Pipeline()
    job_id = f"trace_{name}_{int(time.time())}"
    
    # We trace start and completion
    res = pipeline.render_one_video(
        animal_mode="cat",
        video_type="short",
        language="en",
        job_id=job_id,
        use_cache=use_cache,
        layout_mode="smart_crop",
        clips_count=2,
        clip_time=10.0,
        allow_shorter=True
    )
    t1 = time.time()
    print(f"Job {job_id} finished in {t1 - t0:.2f}s with result: {res}")
    
    # Read job result and timings
    work_dir = os.path.join(r"C:\LionReel\work", job_id)
    timings_p = os.path.join(work_dir, "timings.json")
    if not os.path.exists(timings_p):
        timings_p = os.path.join(work_dir, f"{job_id}_timings.json")
    if not os.path.exists(timings_p):
        timings_p = os.path.join(BASE_DIR, "finished", f"{job_id}_timings.json")
        
    timings = {}
    if os.path.exists(timings_p):
        with open(timings_p, "r", encoding="utf-8") as f:
            timings = json.load(f)
            
    job_res_p = os.path.join(BASE_DIR, "job_result.json")
    job_res = {}
    if os.path.exists(job_res_p):
        with open(job_res_p, "r", encoding="utf-8") as f:
            job_res = json.load(f)
            
    log_p = os.path.join(work_dir, "job.log")
    log_lines = []
    if os.path.exists(log_p):
        with open(log_p, "r", encoding="utf-8", errors="ignore") as f:
            log_lines = f.readlines()
            
    return {
        "job_id": job_id,
        "name": name,
        "duration": t1 - t0,
        "res": res,
        "timings": timings,
        "job_res": job_res,
        "log_lines": log_lines
    }

if __name__ == "__main__":
    # 1. Normal job (with use_cache=True)
    normal_data = run_traced_job("normal", use_cache=True)
    
    # 2. Force fresh analysis job (with use_cache=False)
    fresh_data = run_traced_job("fresh", use_cache=False)
    
    with open("scratch/trace_results.json", "w", encoding="utf-8") as f_out:
        json.dump({
            "normal": {k: v for k, v in normal_data.items() if k != "log_lines"},
            "fresh": {k: v for k, v in fresh_data.items() if k != "log_lines"}
        }, f_out, indent=2)
    print("\nSaved trace results to scratch/trace_results.json")
