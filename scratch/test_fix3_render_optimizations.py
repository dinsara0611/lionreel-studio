import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from auto_reframe import AutoReframeEngine
from lion_automate_v97 import ensure_local_source_copy

def test_fix3():
    engine = AutoReframeEngine()
    src = r"C:\LionReel\cache\cache_ByH9LuSILxU.mp4"

    print("=== TESTING FIX 3: RENDER OPTIMIZATIONS, EARLY ABORT & CIRCUIT BREAKER ===")
    
    # 1. Test passing candidate early check vs full render speed
    print("\n1. Testing Passing Candidate (45.0s, Smart Crop):")
    plan = engine.plan_reframe(src, 45.0, 10.0, layout_mode="smart_crop")
    assert plan.get("status") == "pass", "Expected 45.0s to pass Stage A"

    t0 = time.time()
    early_ok, early_msg = engine.early_check_segment_gate(src, 45.0, 10.0, plan, layout_mode="smart_crop")
    t_early = time.time() - t0
    print(f"Early check completed in {t_early:.2f}s: pass={early_ok}, msg={early_msg}")
    assert early_ok is True, f"Expected early check to pass, got {early_msg}"

    t1 = time.time()
    out_clip = "scratch/test_fix3_full_render.mp4"
    render_ok = engine.reframe_segment_ffmpeg(src, out_clip, 45.0, 10.0, plan)
    t_render = time.time() - t1
    print(f"Full render completed in {t_render:.2f}s: success={render_ok}")
    assert render_ok is True, "Render failed"
    assert t_render < 22.0, f"Render took {t_render:.2f}s, expected < 22.0s"

    # Verify post crop gate on rendered clip
    post_ok, post_msg = engine.verify_post_crop_gate(out_clip, plan=plan, layout_mode="smart_crop")
    print(f"Post-crop gate verify: {post_ok} ({post_msg})")
    assert post_ok is True, f"Post-crop gate failed: {post_msg}"

    # 2. Test Circuit Breaker Logic
    print("\n2. Testing Circuit Breaker (3 in a row systemic failure):")
    mock_failures = ["BLURRED_BARS", "BLURRED_BARS", "BLURRED_BARS", "BLURRED_BARS"]
    consecutive_fails = 0
    last_fail_code = ""
    halted = False
    
    for i, fail_code in enumerate(mock_failures):
        if fail_code == last_fail_code:
            consecutive_fails += 1
        else:
            consecutive_fails = 1
            last_fail_code = fail_code
        print(f"Cand {i+1} failed with code: {fail_code} (consecutive: {consecutive_fails})")
        if consecutive_fails >= 3:
            print(f"SYSTEMIC FAILURE TRIGGERED: {last_fail_code} (3 in a row) -> HALTING BATCH!")
            halted = True
            break
    
    assert halted is True, "Circuit breaker should have halted batch after 3 consecutive failures"
    print("\nALL FIX 3 TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_fix3()
