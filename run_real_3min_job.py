#!/usr/bin/env python3
"""
Executes one real 3-minute production job (180s, 16:9 YouTube compilation)
and measures:
1. True Peak (limit <= -1.0 dBTP)
2. Integrated Loudness (target -14.0 +/- 0.5 LUFS)
3. Inter-clip loudness jumps (max jump <= 3.0 LU)
4. Joins click detection (0 clicks)
5. Video frame rate (exactly 30.00 CFR)
6. Video color tags (pure BT.709)
"""

import os
import sys
import time
import json
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from tests.test_audio_video_quality import (
    measure_audio_metrics,
    measure_clip_loudness_jumps,
    detect_boundary_clicks,
    inspect_video_stream
)
import job_options

def main():
    ts = int(time.time())
    job_id = f"job_real_3min_cat_{ts}"
    print(f"=== Starting Real 3-Minute Job: {job_id} ===")

    cfg_raw = {
        "job_id": job_id,
        "VIDEO_TYPE": "long",
        "ASPECT_RATIO": "16:9",
        "SHORT_CLIP_SEC": 7.5,
        "TARGET_DURATION_MIN": 3.0,
        "ALLOW_SHORTER": True,
        "ALLOW_REUSE": True
    }

    valid, norm, err = job_options.normalize_job_options(cfg_raw)
    if not valid:
        raise ValueError(f"Normalization failed: {err}")

    saved_cfg = job_options.load_or_verify_job_config(job_id, norm)
    print(f"Persisted Job Config: {saved_cfg}")

    cmd = [
        sys.executable,
        os.path.join(BASE_DIR, "lion_automate_v97.py"),
        "--mode", "cat",
        "--type", norm["type"],
        "--job-id", job_id,
        "--clips", str(norm["clips"]),
        "--clip-time", str(norm["clip_time"]),
        "--aspect", "16:9",
        "--layout", "smart_crop",
        "--allow-shorter",
        "--allow-reuse"
    ]

    print(f"Executing: {' '.join(cmd)}")
    start_time = time.time()
    proc = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True)
    elapsed = round(time.time() - start_time, 2)
    print(f"Pipeline finished in {elapsed}s with return code {proc.returncode}")

    if proc.returncode != 0:
        print("[STDERR TAIL]\n", proc.stderr[-1000:])
        print("[STDOUT TAIL]\n", proc.stdout[-1000:])

    out_dir = os.path.join(BASE_DIR, "output", job_id)
    mp4_files = [f for f in os.listdir(out_dir) if f.endswith(".mp4")] if os.path.exists(out_dir) else []
    if not mp4_files:
        raise RuntimeError(f"No output MP4 found in {out_dir}")

    master_mp4 = os.path.join(out_dir, mp4_files[0])
    print(f"\n=== Output Master Video: {master_mp4} ===")

    # 1. Measure Audio Metrics
    metrics = measure_audio_metrics(master_mp4)
    lufs = metrics["integrated_lufs"]
    tp = metrics["true_peak_dbtp"]
    lra = metrics["lra"]
    margin_lufs = round(0.5 - abs(lufs - (-14.0)), 2)
    margin_tp = round(-1.0 - tp, 2)

    print(f"Audio Integrated Loudness: {lufs:.2f} LUFS (target -14.0 +/- 0.5, margin {margin_lufs:+.2f} LU)")
    print(f"Audio True Peak:          {tp:.2f} dBTP (limit <= -1.0 dBTP, margin {margin_tp:+.2f} dB)")
    print(f"Audio Loudness Range:      {lra:.2f} LU")

    # 2. Measure Video Specs
    v_info = inspect_video_stream(master_mp4)
    fps = v_info["fps"]
    duration_s = v_info["duration_s"]
    total_frames = v_info["total_frames"]
    color_tags = v_info["color_tags"]

    print(f"Video Frame Rate:         {fps:.2f} fps ({total_frames} frames / {duration_s:.2f}s)")
    print(f"Video Color Tags:         {color_tags} (required: pure bt709)")

    # 3. Inter-Clip Jumps & Clicks
    mapping_p = os.path.join(out_dir, f"{job_id}_mapping.json")
    if not os.path.exists(mapping_p):
        mapping_p = os.path.join(out_dir, "mapping.json")

    joins = []
    if os.path.exists(mapping_p):
        with open(mapping_p, "r", encoding="utf-8") as f_m:
            m_data = json.load(f_m)
            cum = 0.0
            for cl in m_data.get("clips", [])[:-1]:
                cum += cl.get("duration", 7.5)
                joins.append(round(cum, 3))

    jumps, segs = measure_clip_loudness_jumps(master_mp4, joins) if joins else ([], [])
    max_jump = max(jumps) if jumps else 0.0
    print(f"Inter-Clip Loudness Jumps: max {max_jump:.2f} LU across {len(jumps)} transitions (limit <= 3.0 LU)")

    clicks = detect_boundary_clicks(master_mp4, joins, tolerance_s=0.05) if joins else []
    print(f"Boundary Clicks Detected:  {len(clicks)} clicks at {len(joins)} joins (limit: 0)")

    # Summary table
    res_summary = {
        "job_id": job_id,
        "master_mp4": master_mp4,
        "elapsed_s": elapsed,
        "duration_s": duration_s,
        "total_frames": total_frames,
        "fps": fps,
        "fps_compliant": bool(abs(fps - 30.0) < 0.1),
        "color_tags": color_tags,
        "color_compliant": bool(color_tags == "bt709"),
        "integrated_lufs": lufs,
        "lufs_compliant": bool(-14.5 <= lufs <= -13.5),
        "margin_lufs": margin_lufs,
        "true_peak_dbtp": tp,
        "tp_compliant": bool(tp <= -1.0),
        "margin_tp": margin_tp,
        "max_clip_jump_lu": max_jump,
        "jumps_compliant": bool(max_jump <= 3.0),
        "boundary_clicks": len(clicks),
        "clicks_compliant": bool(len(clicks) == 0)
    }

    result_json_path = os.path.join(BASE_DIR, "analysis", "real_3min_job_results.json")
    with open(result_json_path, "w", encoding="utf-8") as f_res:
        json.dump(res_summary, f_res, indent=2)

    print(f"\nResults successfully written to: {result_json_path}")
    print(json.dumps(res_summary, indent=2))

if __name__ == "__main__":
    main()
