"""
scripts/rescan_bank_clean_and_types.py
======================================
Re-scans existing clip bank with:
1. Burned-in text and overlay gate (rejects windows with persistent text >3%, boxes >1.5%, top/bottom banners, or black borders).
2. Video Type Classifier (classifies into the 9 canonical cat video types).
Marks failing windows in clip_ledger.db (sets is_verified=0 with rejection_reason; DELETES NOTHING).
Reports remaining verified windows per source and per type.
"""

import os
import sys
import json
import sqlite3
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from overlay_text_detector import check_window_burned_in_text
from video_type_classifier import VideoTypeClassifier
from clip_ledger import get_ledger_db_path

def resolve_source_path(raw_path: str) -> str:
    if os.path.exists(raw_path):
        return raw_path
    bname = os.path.basename(raw_path)
    candidates = [
        os.path.join(PROJECT_ROOT, "raw", bname),
        os.path.join(PROJECT_ROOT, "data", "raw_videos", bname),
        os.path.join("C:\\", "LionReel", "cache", bname),
        os.path.join("C:\\", "LionReel", "data", "raw_videos", bname)
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return raw_path

def rescan_bank():
    from clip_ledger import ClipLedger
    ledger = ClipLedger()
    db_path = ledger.db_path
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Query all rows in clips
    c.execute("SELECT clip_id, source_id, source_url_or_path, start_s, end_s, is_verified, times_used FROM clips")
    rows = c.fetchall()
    print(f"Total rows in clips table: {len(rows)}")

    classifier = VideoTypeClassifier()

    scanned_count = 0
    passed_overlay_count = 0
    failed_overlay_count = 0
    rejection_reasons = defaultdict(int)

    types_summary = defaultdict(int)
    sources_summary = defaultdict(lambda: {"total": 0, "verified_clean": 0, "rejected": 0})

    for r in rows:
        scanned_count += 1
        clip_id = r["clip_id"]
        source_raw = r["source_url_or_path"]
        start_s = float(r["start_s"])
        end_s = float(r["end_s"])
        dur_s = end_s - start_s
        src_path = resolve_source_path(source_raw)

        sources_summary[os.path.basename(src_path)]["total"] += 1

        if not os.path.exists(src_path):
            print(f"[{clip_id}] Source not found: {src_path}")
            continue

        # 1. Overlay & Black Border Gate
        overlay_res = check_window_burned_in_text(src_path, start_s, dur_s, n_samples=8)
        is_clean = overlay_res["passed"]
        reason = overlay_res["reason"]

        # 2. Type Classification
        type_res = classifier.classify_window(src_path, start_s, dur_s, n_samples=8)
        p_type = type_res["primary_type"]
        p_conf = type_res["confidence"]
        s_type = type_res["secondary_type"]

        if is_clean:
            passed_overlay_count += 1
            sources_summary[os.path.basename(src_path)]["verified_clean"] += 1
            types_summary[p_type] += 1
            conn.execute("""
                UPDATE clips
                SET is_verified = 1,
                    rejection_reason = NULL,
                    text_overlay_checked = 1,
                    cat_video_type = ?,
                    cat_video_type_conf = ?,
                    cat_video_type_secondary = ?
                WHERE clip_id = ?
            """, (p_type, p_conf, s_type, clip_id))
        else:
            failed_overlay_count += 1
            rejection_reasons[reason] += 1
            sources_summary[os.path.basename(src_path)]["rejected"] += 1
            conn.execute("""
                UPDATE clips
                SET is_verified = 0,
                    rejection_reason = ?,
                    text_overlay_checked = 1,
                    cat_video_type = ?,
                    cat_video_type_conf = ?,
                    cat_video_type_secondary = ?
                WHERE clip_id = ?
            """, (reason, p_type, p_conf, s_type, clip_id))

        if scanned_count % 10 == 0 or scanned_count == len(rows):
            print(f"Scanned {scanned_count}/{len(rows)} clips (Passed clean: {passed_overlay_count}, Rejected overlays/borders: {failed_overlay_count})...")

    conn.commit()
    conn.close()

    print("\n" + "=" * 72)
    print("BANK RE-SCAN & CLASSIFICATION REPORT")
    print("=" * 72)
    print(f"Total Windows Scanned: {scanned_count}")
    print(f"Passed Clean Windows:  {passed_overlay_count} ({passed_overlay_count/max(1, scanned_count):.1%})")
    print(f"Rejected Overlays:     {failed_overlay_count} ({failed_overlay_count/max(1, scanned_count):.1%})")
    
    print("\n--- Rejection Reasons Breakdown ---")
    for r_reason, count in sorted(rejection_reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"  {r_reason:45s}: {count} windows")

    print("\n--- Verified Clean Windows per Video Type ---")
    for v_type, count in sorted(types_summary.items(), key=lambda x: x[1], reverse=True):
        print(f"  {v_type:25s}: {count} verified windows")

    print("\n--- Windows per Source Breakdown ---")
    for src_name, stats in sorted(sources_summary.items()):
        print(f"  {src_name:32s}: Total={stats['total']}, Clean={stats['verified_clean']}, Rejected={stats['rejected']}")
    print("=" * 72)

if __name__ == "__main__":
    rescan_bank()
