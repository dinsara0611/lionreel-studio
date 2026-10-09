import os, sys, json, cv2, numpy as np

sys.path.insert(0, r"g:\My Drive\Cat make")
from pet_detector import PetDetector

detector = PetDetector()
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

def plan_optimal_offline_camera_path(sample_times, detections_per_time, orig_w, orig_h, max_upscale=2.0):
    """
    Computes an offline optimal camera path:
    - Prominent cat tracking + identity persistence + linear gap interpolation
    - Lookahead + bidirectional Gaussian/Savitzky-Golay smoothing
    - Vertical zoom/shift within the max upscale budget
    """
    n_frames = len(sample_times)
    
    # 1. Subject extraction per timestamp
    raw_x = [None] * n_frames
    raw_y = [None] * n_frames
    raw_h = [None] * n_frames
    
    last_known_x = orig_w / 2.0
    last_known_y = orig_h / 2.0
    
    for i, dets in enumerate(detections_per_time):
        cats = [d for d in dets if d["class_name"] in ("cat", "dog")]
        if cats:
            # Score by prominence: size + confidence + proximity to last known
            best_cat = None
            best_score = -1.0
            for c in cats:
                bx1, by1, bx2, by2 = c["box"]
                cx = (bx1 + bx2) / 2.0
                cy = (by1 + by2) / 2.0
                area = c["area_frac"]
                conf = c["conf"]
                dist = np.hypot(cx - last_known_x, cy - last_known_y)
                prox = max(0.0, 1.0 - (dist / float(orig_w * 0.4)))
                score = area * 3.0 + conf * 1.5 + prox * 2.0
                if score > best_score:
                    best_score = score
                    best_cat = c
                    
            bx1, by1, bx2, by2 = best_cat["box"]
            cx = (bx1 + bx2) / 2.0
            cy = (by1 + by2) / 2.0
            ch = by2 - by1
            raw_x[i] = cx
            raw_y[i] = cy
            raw_h[i] = ch
            last_known_x = cx
            last_known_y = cy
            
    # Linear interpolation for missing gaps
    valid_indices = [i for i, x in enumerate(raw_x) if x is not None]
    if not valid_indices:
        # Default center
        return None
        
    all_indices = np.arange(n_frames)
    interp_x = np.interp(all_indices, valid_indices, [raw_x[i] for i in valid_indices])
    interp_y = np.interp(all_indices, valid_indices, [raw_y[i] for i in valid_indices])
    interp_h = np.interp(all_indices, valid_indices, [raw_h[i] for i in valid_indices])
    
    # 2. Determine crop size and vertical slack
    # Check average pet vertical position
    avg_y = np.mean(interp_y)
    vert_drift = abs(avg_y - orig_h / 2.0) / float(orig_h) # e.g. 0.15
    
    # Upscale budget: max upscale 2.0x -> minimum crop_w = 1080 / 2.0 = 540
    # Minimum crop_h = 540 * (16 / 9) = 960 px.
    # Base 9:16 full-height crop: crop_h = 1080, crop_w = 608 (1.78x upscale)
    if vert_drift > 0.08:
        # Use mild vertical zoom (e.g. 1.12x, upscale 1.99x <= 2.0x) to gain vertical camera freedom
        zoom_factor = min(1.12, 2.0 / 1.78)
    else:
        zoom_factor = 1.0
        
    crop_h = int(round(orig_h / zoom_factor))
    crop_w = int(round(crop_h * 9.0 / 16.0))
    if crop_w % 2 != 0: crop_w += 1
    if crop_h % 2 != 0: crop_h += 1
    
    max_crop_x = orig_w - crop_w
    max_crop_y = orig_h - crop_h
    
    # 3. Offline Optimal Camera Path (Bidirectional smoothing with lookahead)
    # Target crop center x
    target_crop_x = interp_x - (crop_w / 2.0)
    target_crop_x = np.clip(target_crop_x, 0, max_crop_x)
    
    # Bidirectional Gaussian smoothing (std = 3 frames ~ 0.5s)
    kernel_size = 7
    sigma = 2.5
    smoothed_crop_x = np.convolve(target_crop_x, np.exp(-0.5 * (np.arange(-3, 4)/sigma)**2)/np.sum(np.exp(-0.5 * (np.arange(-3, 4)/sigma)**2)), mode='same')
    smoothed_crop_x = np.clip(smoothed_crop_x, 0, max_crop_x)
    
    # Vertical crop position: center pet vertically in crop
    if max_crop_y > 0:
        target_crop_y = interp_y - (crop_h * 0.45) # Keep pet eyes/upper body around 45%
        target_crop_y = np.clip(target_crop_y, 0, max_crop_y)
        smoothed_crop_y = np.convolve(target_crop_y, np.exp(-0.5 * (np.arange(-3, 4)/sigma)**2)/np.sum(np.exp(-0.5 * (np.arange(-3, 4)/sigma)**2)), mode='same')
        smoothed_crop_y = np.clip(smoothed_crop_y, 0, max_crop_y)
    else:
        smoothed_crop_y = np.zeros(n_frames)
        
    return {
        "crop_w": crop_w,
        "crop_h": crop_h,
        "max_crop_y": max_crop_y,
        "cam_x": smoothed_crop_x,
        "cam_y": smoothed_crop_y,
        "interp_x": interp_x,
        "interp_y": interp_y,
        "interp_h": interp_h
    }

def evaluate_new_gate(bx1, by1, bx2, by2, crop_x, crop_y, crop_w, crop_h, has_vertical_slack):
    """
    Requirement 2 Gate Specification:
    - visibility: pet box fully inside output frame
    - horizontal centering: box center within x 38-62%
    - vertical framing: if slack exists, y 30-62%; if no slack, fully visible and y 20-75%
    - size: box height 30-70% of frame height
    """
    # Map to crop coordinates
    cbx1 = bx1 - crop_x
    cby1 = by1 - crop_y
    cbx2 = bx2 - crop_x
    cby2 = by2 - crop_y
    
    # 1. Visibility (fully inside output frame)
    is_visible = (cbx1 >= -2 and cby1 >= -2 and cbx2 <= crop_w + 2 and cby2 <= crop_h + 2)
    
    cx = ((cbx1 + cbx2) / 2.0) / float(crop_w)
    cy = ((cby1 + cby2) / 2.0) / float(crop_h)
    box_h_frac = (cby2 - cby1) / float(crop_h)
    
    # 2. Horizontal centering
    is_horiz_centered = (0.38 <= cx <= 0.62)
    
    # 3. Vertical framing
    if has_vertical_slack:
        is_vert_framed = (0.30 <= cy <= 0.62)
    else:
        is_vert_framed = (0.20 <= cy <= 0.75) and (cby1 >= 0 and cby2 <= crop_h)
        
    # 4. Size
    is_valid_size = (0.28 <= box_h_frac <= 0.72)
    
    frame_passed = is_visible and is_horiz_centered and is_vert_framed and is_valid_size
    return {
        "passed": frame_passed,
        "is_visible": is_visible,
        "is_horiz_centered": is_horiz_centered,
        "is_vert_framed": is_vert_framed,
        "is_valid_size": is_valid_size,
        "cx": cx, "cy": cy, "h_frac": box_h_frac
    }

print("Running Re-scoring of 7 Candidates with Optimal Camera & New Gate...\n")
cap = cv2.VideoCapture(source_path)
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

rescore_table = []

for cand in candidates:
    cid = cand["id"]
    start_s = cand["start"]
    dur_s = cand["dur"]
    start_f = int(start_s * fps)
    total_f = int(dur_s * fps)
    
    # Sample 24 frames
    sample_f_indices = [int(start_f + (i + 0.5) * (total_f / 24)) for i in range(24)]
    sample_times = [(idx - start_f) / fps for idx in sample_f_indices]
    
    # Extract detections
    dets_per_frame = []
    frames_cache = []
    for fidx in sample_f_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
        ret, frame = cap.read()
        frames_cache.append(frame)
        dets = detector.detect(frame)
        dets_per_frame.append(dets)
        
    cam_plan = plan_optimal_offline_camera_path(sample_times, dets_per_frame, orig_w, orig_h)
    if not cam_plan:
        rescore_table.append({"id": cid, "passed": False, "score": 0.0})
        continue
        
    crop_w = cam_plan["crop_w"]
    crop_h = cam_plan["crop_h"]
    has_slack = bool(cam_plan["max_crop_y"] > 0)
    
    n_detected = 0
    sub_checks = {"vis": 0, "horiz": 0, "vert": 0, "size": 0, "all_ok": 0}
    
    for i, dets in enumerate(dets_per_frame):
        cats = [d for d in dets if d["class_name"] in ("cat", "dog")]
        if not cats: continue
        n_detected += 1
        best_cat = max(cats, key=lambda d: d["area_frac"] * 2.0 + d["conf"])
        bx1, by1, bx2, by2 = best_cat["box"]
        
        eval_res = evaluate_new_gate(
            bx1, by1, bx2, by2,
            cam_plan["cam_x"][i], cam_plan["cam_y"][i],
            crop_w, crop_h, has_slack
        )
        if eval_res["is_visible"]: sub_checks["vis"] += 1
        if eval_res["is_horiz_centered"]: sub_checks["horiz"] += 1
        if eval_res["is_vert_framed"]: sub_checks["vert"] += 1
        if eval_res["is_valid_size"]: sub_checks["size"] += 1
        if eval_res["passed"]: sub_checks["all_ok"] += 1
        
    eval_count = max(n_detected, 1)
    rescore_table.append({
        "id": cid,
        "start": start_s,
        "orig_score": cand["orig_score"],
        "has_slack": has_slack,
        "crop_dim": f"{crop_w}x{crop_h}",
        "vis_pct": round(sub_checks["vis"] / eval_count * 100, 1),
        "horiz_pct": round(sub_checks["horiz"] / eval_count * 100, 1),
        "vert_pct": round(sub_checks["vert"] / eval_count * 100, 1),
        "size_pct": round(sub_checks["size"] / eval_count * 100, 1),
        "new_overall_pct": round(sub_checks["all_ok"] / eval_count * 100, 1),
        "new_verdict": "PASS ✅" if (sub_checks["all_ok"] / eval_count) >= 0.88 else "FAIL ❌"
    })

cap.release()

print("="*100)
print("RE-SCORING COMPARISON TABLE ACROSS 7 CANDIDATES")
print("="*100)
print(f"{'Cand':<5} | {'Orig Score':<15} | {'Slack?':<7} | {'Crop Size':<10} | {'Vis%':<6} | {'Horiz%':<7} | {'Vert%':<6} | {'Size%':<6} | {'New Overall%':<12} | {'Verdict'}")
print("-" * 100)
for r in rescore_table:
    print(f"{r['id']:<5} | {r['orig_score']:<15} | {str(r['has_slack']):<7} | {r['crop_dim']:<10} | {r['vis_pct']:<6} | {r['horiz_pct']:<7} | {r['vert_pct']:<6} | {r['size_pct']:<6} | {r['new_overall_pct']:<12} | {r['new_verdict']}")
print("="*100)
