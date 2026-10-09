import os, sys, json, time

sys.path.insert(0, r"g:\My Drive\Cat make")
from lion_automate_v97 import LionReelV97Pipeline
from qa_check import run_full_qa

print("="*80)
print("LIONREEL BLUR-FIT LAYOUT VERIFICATION TEST")
print("="*80)

pipeline = LionReelV97Pipeline()
t0 = time.time()
job_id = f"lionreel_cat_blurfit_test_{int(time.time())}"

out_video = pipeline.render_one_video(
    animal_mode="cat",
    video_type="short",
    language="en",
    job_id=job_id,
    use_cache=False,
    layout_mode="blur_fit",
    clips_count=2,
    clip_time=10.0,
    allow_reuse=True
)
total_elapsed = round(time.time() - t0, 1)

print("\n" + "="*80)
print("BLUR-FIT TEST EXECUTION SUMMARY")
print("="*80)

if out_video and os.path.exists(out_video):
    print(f"\nFinal Blur-Fit Video Generated: {out_video} ({os.path.getsize(out_video)/1024/1024:.2f} MB)")
    qa_ok, qa_rep = run_full_qa(out_video, layout_mode="blur_fit")
    print(f"\nAutomated QA Result: {'PASS ✅' if qa_ok else 'FAIL ❌'}")
    lf = qa_rep.get("layout_fill", {})
    print(f"Layout Fill Check: {lf.get('reason', '')} -> {'PASS ✅' if lf.get('passed') else 'FAIL ❌'}")
    cent = qa_rep.get("pet_centering", {})
    print(f"Centering Check: Compliance {cent.get('compliance_ratio', 0.0):.1%} -> {'PASS ✅' if cent.get('passed') else 'FAIL ❌'}")
    if qa_ok:
        print(f"\nBLUR-FIT TEST SUCCESS: {out_video}")
    else:
        print(f"\nBLUR-FIT TEST FAILED: QA validation failed on {out_video}")
else:
    print(f"\nBLUR-FIT TEST FAILED: No output video generated")
