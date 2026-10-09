import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from auto_reframe import AutoReframeEngine
from pet_detector import PetDetector

def run_test():
    engine = AutoReframeEngine()
    src = r"C:\LionReel\cache\cache_ByH9LuSILxU.mp4"

    print("=== TESTING FIX 2: REAL STAGE A MEASUREMENTS ===")
    for layout in ["smart_crop", "blur_fit"]:
        print(f"\n--- Layout: {layout.upper()} ---")
        for start in [10.0, 60.0, 165.0]:
            t0 = time.time()
            plan = engine.plan_reframe(src, start, 10.0, layout_mode=layout)
            t_el = time.time() - t0
            st = plan.get("status", "unknown")
            score = plan.get("framing_score", 0.0)
            sharp = plan.get("sharpness", 0.0)
            pet_ratio = plan.get("pet_detected_ratio", 0.0)
            det = plan.get("details", {})
            vis = det.get("vis", 0.0)
            h = det.get("horiz", 0.0)
            v = det.get("vert", 0.0)
            s = det.get("size", 0.0)

            print(f"Start {start:5.1f}s ({t_el:.2f}s) -> status: {st.upper():<6} | Score: {score*100:5.1f}% | Sharp: {sharp:5.1f} | Pet: {pet_ratio*100:5.1f}% | Vis: {vis*100:5.1f}% | H: {h*100:5.1f}% | V: {v*100:5.1f}% | S: {s*100:5.1f}%")
            assert not (st == "pass" and score == 0.0 and sharp == 0.0), "FAIL: pass with 0.0 score and 0.0 sharpness"
            assert sharp > 0.0, "FAIL: sharpness was 0.0"
            if st == "pass":
                assert score >= 0.88, f"FAIL: pass score {score} < 0.88"

    print("\nALL STAGE A ASSERTIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_test()
