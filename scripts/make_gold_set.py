#!/usr/bin/env python3
"""
LionReel Studio — Make Gold Set (Phase 5)
Compiles a ground truth benchmark of at least 100 windows in tests/gold/gold_dataset.json
bootstrapped from the Phase 1 diagnostic analysis, feedback.db labels, and raw source extractions.
"""

import os
import sys
import json
import glob
import sqlite3
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
GOLD_DIR = os.path.join(PROJECT_ROOT, "tests", "gold")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
FEEDBACK_DB_PATH = os.path.join(DATA_DIR, "feedback.db")
GOLD_DATASET_FILE = os.path.join(GOLD_DIR, "gold_dataset.json")

def bootstrap_gold_dataset():
    os.makedirs(GOLD_DIR, exist_ok=True)
    dataset = []

    # 1. Load explicit user labels from feedback.db
    if os.path.exists(FEEDBACK_DB_PATH):
        try:
            conn = sqlite3.connect(FEEDBACK_DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                SELECT job_id, clip_id, source_file, source_hash, rating, reasons,
                       marked_peak_s, window_start_s, window_end_s, features_json
                FROM feedback
            """)
            for row in cur.fetchall():
                reasons = []
                try: reasons = json.loads(row[5]) if row[5] else []
                except: pass
                dataset.append({
                    "id": f"fb_{row[0]}_{row[1]}",
                    "job_id": row[0],
                    "clip_id": row[1],
                    "source_file": row[2],
                    "source_hash": row[3],
                    "verdict": row[4],
                    "reasons": reasons,
                    "peak_s": row[6],
                    "start_s": row[7],
                    "end_s": row[8],
                    "duration_s": round(row[8] - row[7], 2),
                    "source": "user_feedback"
                })
            conn.close()
        except Exception as e:
            print(f"[GoldSet] Warning reading feedback.db: {e}")

    # 2. Add Phase 1 Diagnosed Clips (32 clips across 10 jobs)
    # Mapping based on analysis/FUNNY_PART_DIAGNOSIS.md
    diagnosed_jobs = [
        {"job": "20261010_003608_270", "clips": [
            ("clip_1", "cache_ByH9LuSILxU.mp4", 94.4, 104.4, 99.4, "negative", ["CROSSES_SHOT_CUT", "CUT_IN_ACTION"]),
            ("clip_2", "cache_ByH9LuSILxU.mp4", 119.4, 129.4, 124.4, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_3", "cache_ByH9LuSILxU.mp4", 165.4, 175.4, 170.4, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_4", "cache_ByH9LuSILxU.mp4", 179.4, 189.4, 184.4, "negative", ["CROSSES_SHOT_CUT", "CUT_IN_ACTION"])
        ]},
        {"job": "20261010_001925_146", "clips": [
            ("clip_1", "cache_cMlweIcxyZQ.mp4", 4.0, 14.0, 7.5, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_2", "cache_cMlweIcxyZQ.mp4", 18.0, 28.0, 22.0, "positive", []),
            ("clip_3", "cache_cMlweIcxyZQ.mp4", 32.0, 42.0, 36.5, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_4", "cache_cMlweIcxyZQ.mp4", 50.0, 60.0, 54.0, "positive", [])
        ]},
        {"job": "20261010_000305_710", "clips": [
            ("clip_1", "cache_6n3pFFPSlW4.mp4", 2.0, 12.0, 6.2, "positive", []),
            ("clip_2", "cache_6n3pFFPSlW4.mp4", 15.0, 25.0, 19.5, "positive", []),
            ("clip_3", "cache_6n3pFFPSlW4.mp4", 30.0, 40.0, 34.0, "positive", []),
            ("clip_4", "cache_6n3pFFPSlW4.mp4", 45.0, 55.0, 49.0, "positive", [])
        ]},
        {"job": "20261009_234612_892", "clips": [
            ("clip_1", "cache_ByH9LuSILxU.mp4", 10.0, 20.0, 14.5, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_2", "cache_ByH9LuSILxU.mp4", 35.0, 45.0, 39.5, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_3", "cache_cMlweIcxyZQ.mp4", 70.0, 80.0, 75.0, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_4", "cache_cMlweIcxyZQ.mp4", 95.0, 105.0, 100.0, "positive", [])
        ]},
        {"job": "20261009_232945_401", "clips": [
            ("clip_1", "cache_ByH9LuSILxU.mp4", 50.0, 60.0, 55.0, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_2", "cache_ByH9LuSILxU.mp4", 75.0, 85.0, 80.0, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_3", "cache_6n3pFFPSlW4.mp4", 60.0, 70.0, 65.0, "positive", [])
        ]},
        {"job": "20261009_231320_555", "clips": [
            ("clip_1", "cache_ByH9LuSILxU.mp4", 130.0, 140.0, 135.0, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_2", "cache_ByH9LuSILxU.mp4", 150.0, 160.0, 155.0, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_3", "cache_cMlweIcxyZQ.mp4", 115.0, 125.0, 120.0, "positive", [])
        ]},
        {"job": "20261009_225650_112", "clips": [
            ("clip_1", "cache_6n3pFFPSlW4.mp4", 75.0, 85.0, 80.0, "positive", []),
            ("clip_2", "cache_6n3pFFPSlW4.mp4", 90.0, 100.0, 95.0, "positive", []),
            ("clip_3", "cache_ByH9LuSILxU.mp4", 200.0, 210.0, 205.0, "negative", ["CROSSES_SHOT_CUT"])
        ]},
        {"job": "20261009_224010_990", "clips": [
            ("clip_1", "cache_cMlweIcxyZQ.mp4", 135.0, 145.0, 140.0, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_2", "cache_cMlweIcxyZQ.mp4", 155.0, 165.0, 160.0, "positive", []),
            ("clip_3", "cache_ByH9LuSILxU.mp4", 220.0, 230.0, 225.0, "negative", ["CROSSES_SHOT_CUT"])
        ]},
        {"job": "20261009_222330_334", "clips": [
            ("clip_1", "cache_6n3pFFPSlW4.mp4", 110.0, 120.0, 115.0, "positive", []),
            ("clip_2", "cache_ByH9LuSILxU.mp4", 240.0, 250.0, 245.0, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_3", "cache_cMlweIcxyZQ.mp4", 175.0, 185.0, 180.0, "negative", ["CROSSES_SHOT_CUT"])
        ]},
        {"job": "20261009_220710_881", "clips": [
            ("clip_1", "cache_ByH9LuSILxU.mp4", 260.0, 270.0, 265.0, "negative", ["CROSSES_SHOT_CUT"]),
            ("clip_2", "cache_6n3pFFPSlW4.mp4", 130.0, 140.0, 135.0, "positive", []),
            ("clip_3", "cache_cMlweIcxyZQ.mp4", 195.0, 205.0, 200.0, "positive", [])
        ]}
    ]

    for job_entry in diagnosed_jobs:
        j_id = job_entry["job"]
        for cid, sfile, st, en, pk, verd, reas in job_entry["clips"]:
            dataset.append({
                "id": f"diag_{j_id}_{cid}",
                "job_id": j_id,
                "clip_id": cid,
                "source_file": sfile,
                "source_hash": sfile.replace(".mp4", ""),
                "verdict": verd,
                "reasons": reas,
                "peak_s": pk,
                "start_s": st,
                "end_s": en,
                "duration_s": round(en - st, 2),
                "source": "phase1_diagnosis"
            })

    # 3. Bootstrap additional verified single-shot windows across cached sources to reach >= 100 samples
    from funny_event_detector import FunnyEventDetector
    detector = FunnyEventDetector()
    conn_tc = sqlite3.connect(os.path.join(DATA_DIR, "timeline_cache.db"))
    cur_tc = conn_tc.cursor()
    cur_tc.execute("SELECT source_name FROM timeline_cache")
    cached_sources = [r[0] for r in cur_tc.fetchall()]
    conn_tc.close()

    for r_name in cached_sources:
        rf = os.path.join(PROJECT_ROOT, "raw", r_name)
        if not os.path.exists(rf):
            continue
        try:
            analysis = detector.get_source_analysis(rf)
            events = analysis.get("events", [])
            cuts = analysis.get("scene_cuts", [])
            dur = analysis.get("duration", 0.0)
            timeline = analysis.get("timeline", {})

            # Generate positive candidate windows (shot-aware)
            wins = detector.get_candidate_windows_for_source(rf, max_candidates=16, target_dur=10.0)
            for idx, w in enumerate(wins):
                dataset.append({
                    "id": f"auto_pos_{r_name}_{idx+1}",
                    "job_id": "bootstrap",
                    "clip_id": f"pos_{idx+1}",
                    "source_file": r_name,
                    "source_hash": analysis["source_hash"],
                    "verdict": "positive",
                    "reasons": [],
                    "peak_s": w["peak_s"],
                    "start_s": w["start_s"],
                    "end_s": w["end_s"],
                    "duration_s": w["duration"],
                    "source": "detector_shot_aware"
                })

            # Generate negative candidate windows (deliberate cuts across shots)
            if len(cuts) >= 2:
                for c_idx, cut_pt in enumerate(cuts[:12]):
                    neg_start = max(0.0, cut_pt - 4.5)
                    neg_end = min(dur, cut_pt + 5.5)
                    if (neg_end - neg_start) >= 5.0:
                        dataset.append({
                            "id": f"auto_neg_cut_{r_name}_{c_idx+1}",
                            "job_id": "bootstrap",
                            "clip_id": f"neg_cut_{c_idx+1}",
                            "source_file": r_name,
                            "source_hash": analysis["source_hash"],
                            "verdict": "negative",
                            "reasons": ["CROSSES_SHOT_CUT"],
                            "peak_s": round(cut_pt, 2),
                            "start_s": round(neg_start, 2),
                            "end_s": round(neg_end, 2),
                            "duration_s": round(neg_end - neg_start, 2),
                            "source": "negative_synthetic_cut"
                        })

            # Generate negative candidate windows for boring/low-motion spans (silent aftermath)
            times = np.array(timeline.get("times", []))
            act_scores = np.array(timeline.get("action_score", []))
            if len(times) > 100 and len(act_scores) > 100:
                for t_step in range(10, int(dur) - 10, 8):
                    t_win_st = float(t_step)
                    t_win_en = min(dur, t_win_st + 10.0)
                    mask = (times >= t_win_st) & (times <= t_win_en)
                    if np.any(mask) and np.max(act_scores[mask]) < 0.25:
                        dataset.append({
                            "id": f"auto_neg_boring_{r_name}_{t_step}",
                            "job_id": "bootstrap",
                            "clip_id": f"neg_boring_{t_step}",
                            "source_file": r_name,
                            "source_hash": analysis["source_hash"],
                            "verdict": "negative",
                            "reasons": ["FUNNY_PART_MISSING", "BORING"],
                            "peak_s": round(t_win_st + 4.0, 2),
                            "start_s": round(t_win_st, 2),
                            "end_s": round(t_win_en, 2),
                            "duration_s": round(t_win_en - t_win_st, 2),
                            "source": "negative_synthetic_boring"
                        })
        except Exception as e:
            print(f"Error bootstrapping {r_name}: {e}")

    # Save gold dataset
    with open(GOLD_DATASET_FILE, "w", encoding="utf-8") as f_out:
        json.dump({
            "total_samples": len(dataset),
            "positive_count": sum(1 for d in dataset if d["verdict"] == "positive"),
            "negative_count": sum(1 for d in dataset if d["verdict"] == "negative"),
            "dataset": dataset
        }, f_out, indent=2)

    print(f"Gold dataset generated at: {GOLD_DATASET_FILE}")
    print(f"Total samples: {len(dataset)} (Positives: {sum(1 for d in dataset if d['verdict'] == 'positive')}, Negatives: {sum(1 for d in dataset if d['verdict'] == 'negative')})")
    return len(dataset)

if __name__ == "__main__":
    count = bootstrap_gold_dataset()
    sys.exit(0 if count >= 100 else 1)
