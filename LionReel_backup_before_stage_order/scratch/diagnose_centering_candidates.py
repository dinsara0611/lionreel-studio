import os
import sys
import json
import cv2
import numpy as np

# Ensure root is in sys.path
sys.path.insert(0, r"g:\My Drive\Cat make")

from pet_detector import PetDetector
from auto_reframe import AutoReframeEngine
from qa_check import check_pet_centering

detector = PetDetector()
reframer = AutoReframeEngine(detector=detector)

source_path = r"g:\My Drive\Cat make\raw\cache_ByH9LuSILxU.mp4"
candidates = [
    {"id": 1, "start": 106.4, "dur": 5.2, "orig_score": "54.2% -> 58.3%"},
    {"id": 2, "start": 166.1, "dur": 5.2, "orig_score": "37.5% -> 37.5%"},
    {"id": 3, "start": 180.0, "dur": 5.2, "orig_score": "82.4% -> 82.4%"},
    {"id": 4, "start": 16.9,  "dur": 5.2, "orig_score": "66.7% -> 72.2%"},
    {"id": 5, "start": 121.3, "dur": 5.2, "orig_score": "PASS 94.1%"},
    {"id": 6, "start": 135.3, "dur": 5.2, "orig_score": "65.0% -> 70.0%"},
    {"id": 7, "start": 112.9, "dur": 5.2, "orig_score": "75.0% -> 75.0%"}
]

out_dir = r"C:\LionReel\work\centering_diagnosis"
os.makedirs(out_dir, exist_ok=True)

results = []

for cand in candidates:
    cid = cand["id"]
    start_s = cand["start"]
    dur_s = cand["dur"]
    
    print(f"\n==========================================")
    print(f"Diagnosing Candidate {cid}: [{start_s}s - {start_s + dur_s}s]")
    print(f"==========================================")
    
    # 1. Get plan from AutoReframer
    plan = reframer.plan_reframe(source_path, start_s, dur_s, animal_mode="cat", layout_mode="smart_crop")
    
    # 2. Extract frames from source
    cap = cv2.VideoCapture(source_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    start_frame = int(start_s * fps)
    total_segment_frames = int(dur_s * fps)
    
    n_samples = 24
    sample_indices = [int(start_frame + (i + 0.5) * (total_segment_frames / n_samples)) for i in range(n_samples)]
    
    frame_records = []
    contact_sheet_frames = []
    
    sub_failures = {
        "no_detection": 0,
        "wrong_subject": 0,
        "box_cut_by_edge": 0,
        "x_center_outside": 0,
        "y_center_outside": 0,
        "box_size_invalid": 0,
        "passed": 0
    }
    
    kf_times = plan.get("keyframes_t", [0.0])
    kf_x = plan.get("keyframes_x", [orig_w // 2])
    kf_y = plan.get("keyframes_y", [0])
    crop_w = plan.get("crop_w", int(orig_h * 9 / 16))
    crop_h = plan.get("crop_h", orig_h)
    
    for idx_num, frame_idx in enumerate(sample_indices):
        t_rel = (frame_idx - start_frame) / fps
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
            
        # Run detection
        all_dets = detector.detect(frame)
        cat_dets = [d for d in all_dets if d["class_name"] in ["cat", "dog"]]
        
        # Interpolate crop window at t_rel
        cur_crop_x = int(np.interp(t_rel, kf_times, kf_x)) if len(kf_times) > 1 else int(kf_x[0])
        cur_crop_y = int(np.interp(t_rel, kf_times, kf_y)) if len(kf_times) > 1 else int(kf_y[0])
        
        # Sub-check evaluation
        fails = []
        chosen_subject = None
        
        if not cat_dets:
            if all_dets:
                sub_failures["wrong_subject"] += 1
                fails.append("wrong_subject")
            else:
                sub_failures["no_detection"] += 1
                fails.append("no_detection")
        else:
            # Pick best cat
            chosen_subject = max(cat_dets, key=lambda d: d["area_frac"] * 2.0 + d["conf"])
            bx1, by1, bx2, by2 = chosen_subject["box"]
            
            # Map box to crop coordinates
            cbx1 = bx1 - cur_crop_x
            cby1 = by1 - cur_crop_y
            cbx2 = bx2 - cur_crop_x
            cby2 = by2 - cur_crop_y
            
            # Sub-check: fully inside crop
            is_inside = (cbx1 >= 0 and cby1 >= 0 and cbx2 <= crop_w and cby2 <= crop_h)
            if not is_inside:
                sub_failures["box_cut_by_edge"] += 1
                fails.append("box_cut_by_edge")
                
            # Normalized center and height relative to crop
            cx = ((cbx1 + cbx2) / 2.0) / float(crop_w)
            cy = ((cby1 + cby2) / 2.0) / float(crop_h)
            box_h_frac = (cby2 - cby1) / float(crop_h)
            
            # Sub-check: x center
            if not (0.38 <= cx <= 0.62):
                sub_failures["x_center_outside"] += 1
                fails.append("x_center_outside")
                
            # Sub-check: y center
            if not (0.30 <= cy <= 0.62):
                sub_failures["y_center_outside"] += 1
                fails.append("y_center_outside")
                
            # Sub-check: size
            if not (0.28 <= box_h_frac <= 0.72):
                sub_failures["box_size_invalid"] += 1
                fails.append("box_size_invalid")
                
            if is_inside and (0.38 <= cx <= 0.62) and (0.30 <= cy <= 0.62) and (0.28 <= box_h_frac <= 0.72):
                sub_failures["passed"] += 1
                
        # Draw on frame for contact sheet
        draw_frame = frame.copy()
        # Draw crop window in neon green
        cv2.rectangle(draw_frame, (cur_crop_x, cur_crop_y), (cur_crop_x + crop_w, cur_crop_y + crop_h), (0, 255, 0), 3)
        # Draw all detections
        for d in all_dets:
            dbx1, dby1, dbx2, dby2 = [int(v) for v in d["box"]]
            color = (0, 165, 255) if d["class_name"] == "cat" else (0, 0, 255)
            cv2.rectangle(draw_frame, (dbx1, dby1), (dbx2, dby2), color, 2)
            cv2.putText(draw_frame, f"{d['class_name']} {d['conf']:.2f}", (dbx1, max(15, dby1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                        
        if chosen_subject:
            sbx1, sby1, sbx2, sby2 = [int(v) for v in chosen_subject["box"]]
            cv2.rectangle(draw_frame, (sbx1, sby1), (sbx2, sby2), (255, 255, 0), 3)
            status_txt = "PASS" if not fails else "+".join(fails)
            color_txt = (0, 255, 0) if not fails else (0, 0, 255)
            cv2.putText(draw_frame, f"t={t_rel:.2f}s | cx={cx:.2f} cy={cy:.2f} | {status_txt}",
                        (cur_crop_x + 10, max(30, cur_crop_y + 30)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_txt, 2)
                        
        # Save every 2nd or 3rd sampled frame for contact sheet (total 8 frames)
        if idx_num % 3 == 0:
            thumb = cv2.resize(draw_frame, (480, 270))
            contact_sheet_frames.append(thumb)
            
    cap.release()
    
    # Build contact sheet (2 rows x 4 cols = 8 frames)
    if contact_sheet_frames:
        while len(contact_sheet_frames) < 8:
            contact_sheet_frames.append(np.zeros_like(contact_sheet_frames[0]))
        row1 = np.hstack(contact_sheet_frames[:4])
        row2 = np.hstack(contact_sheet_frames[4:8])
        contact_sheet = np.vstack([row1, row2])
        cs_path = os.path.join(out_dir, f"candidate_{cid}_contact_sheet.png")
        cv2.imwrite(cs_path, contact_sheet)
        print(f"Saved contact sheet: {cs_path}")
        
    total_evaluated = n_samples
    pass_ratio = sub_failures["passed"] / float(total_evaluated)
    
    cand_summary = {
        "candidate": cid,
        "start": start_s,
        "end": round(start_s + dur_s, 2),
        "orig_score": cand["orig_score"],
        "simulated_pass_rate": f"{pass_ratio:.1%}",
        "crop_w": crop_w,
        "crop_h": crop_h,
        "orig_h": orig_h,
        "has_vertical_slack": bool(crop_h < orig_h),
        "pct_no_detection": round(sub_failures["no_detection"] / total_evaluated * 100, 1),
        "pct_wrong_subject": round(sub_failures["wrong_subject"] / total_evaluated * 100, 1),
        "pct_box_cut_by_edge": round(sub_failures["box_cut_by_edge"] / total_evaluated * 100, 1),
        "pct_x_center_outside": round(sub_failures["x_center_outside"] / total_evaluated * 100, 1),
        "pct_y_center_outside": round(sub_failures["y_center_outside"] / total_evaluated * 100, 1),
        "pct_box_size_invalid": round(sub_failures["box_size_invalid"] / total_evaluated * 100, 1),
        "contact_sheet": os.path.join(out_dir, f"candidate_{cid}_contact_sheet.png")
    }
    results.append(cand_summary)

# Write summary JSON
with open(os.path.join(out_dir, "diagnosis_summary.json"), "w") as f:
    json.dump(results, f, indent=2)

print("\n" + "="*80)
print("DIAGNOSIS RESULTS TABLE")
print("="*80)
print(f"{'Cand':<5} | {'Orig Score':<15} | {'NoDet%':<7} | {'CutEdge%':<9} | {'X-Out%':<7} | {'Y-Out%':<7} | {'Size%':<7} | {'Vert Slack?'}")
print("-" * 80)
for r in results:
    print(f"{r['candidate']:<5} | {r['orig_score']:<15} | {r['pct_no_detection']:<7} | {r['pct_box_cut_by_edge']:<9} | {r['pct_x_center_outside']:<7} | {r['pct_y_center_outside']:<7} | {r['pct_box_size_invalid']:<7} | {r['has_vertical_slack']}")
print("="*80)
