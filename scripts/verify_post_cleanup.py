import os
import sys
import json
import hashlib
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def verify_ui_freeze():
    print("=== 1. VERIFYING UI FREEZE MANIFEST INTEGRITY ===")
    manifest_p = os.path.join(BASE_DIR, "ui_freeze_manifest.json")
    with open(manifest_p, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    all_ok = True
    for rel_path, meta in manifest.items():
        fp = os.path.join(BASE_DIR, rel_path)
        if not os.path.exists(fp):
            print(f"FAILED: Frozen file {rel_path} is MISSING!")
            all_ok = False
            continue
        cur_hash = sha256_file(fp)
        cur_sz = os.path.getsize(fp)
        if cur_hash != meta["sha256"]:
            print(f"FAILED: Hash mismatch on {rel_path}! Expected {meta['sha256']}, got {cur_hash}")
            all_ok = False
        elif cur_sz != meta["size"]:
            print(f"FAILED: Size mismatch on {rel_path}! Expected {meta['size']}, got {cur_sz}")
            all_ok = False
        else:
            print(f"PASS: {rel_path} (size={cur_sz}, sha256={cur_hash[:12]}...)")
    
    return all_ok

def verify_production_deliverables():
    print("\n=== 2. VERIFYING PRODUCTION DELIVERABLES IN finished/ ===")
    finished_dir = os.path.join(BASE_DIR, "finished")
    masters = [
        "lionreel_cat_proof_short_30s.mp4",
        "lionreel_cat_proof_long_3m.mp4",
        "lionreel_cat_proof_both.mp4",
        "lionreel_cat_proof_both_teaser.mp4"
    ]
    all_ok = True
    for m in masters:
        fp = os.path.join(finished_dir, m)
        if os.path.isfile(fp) and os.path.getsize(fp) > 1024 * 1024:
            sz_mb = os.path.getsize(fp) / (1024 * 1024)
            print(f"PASS: {m} exists ({sz_mb:.2f} MB)")
        else:
            print(f"FAILED: Master {m} missing or truncated!")
            all_ok = False
    return all_ok

def verify_ledger():
    print("\n=== 3. VERIFYING CLIP LEDGER INTEGRITY ===")
    import sqlite3
    db_path = r"C:\LionReel\data\clip_ledger.db"
    if not os.path.exists(db_path):
        db_path = os.path.join(BASE_DIR, "data", "clip_ledger.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM clips WHERE is_verified=1")
    v_clips = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM finished_video_windows")
    f_win = cur.fetchone()[0]
    print(f"PASS: clip_ledger.db accessible: {v_clips} verified clips, {f_win} finished video windows")
    return v_clips > 0

if __name__ == "__main__":
    ok1 = verify_ui_freeze()
    ok2 = verify_production_deliverables()
    ok3 = verify_ledger()
    if ok1 and ok2 and ok3:
        print("\nALL POST-CLEANUP INTEGRITY CHECKS PASSED 100% ✅")
        sys.exit(0)
    else:
        print("\nPOST-CLEANUP INTEGRITY CHECK FAILED ❌")
        sys.exit(1)
