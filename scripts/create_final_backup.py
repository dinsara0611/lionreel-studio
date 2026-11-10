import os
import sys
import shutil
import hashlib
import json
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_ROOT = r"C:\LionReel\backups"
BACKUP_DIR = os.path.join(BACKUP_ROOT, f"final_before_cleanup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}")
LOCAL_DATA_DIR = r"C:\LionReel"

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def run():
    print(f"=== CREATING FRESH FULL BACKUP OUTSIDE GOOGLE DRIVE ===")
    print(f"Target Backup Directory: {BACKUP_DIR}")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    
    # 1. Collect files to back up:
    files_to_copy = []
    
    # A. Code and project config
    for root, dirs, files in os.walk(BASE_DIR):
        # Exclude git internals, old backup folders inside project, large finished video files (we list them), raw cache
        low = root.lower()
        if "\\.git" in low or "\\raw" in low or "\\finished" in low or "\\work" in low or "\\backups" in low or "\\quarantine" in low or "\\lionreel_backup" in low:
            continue
        for fn in files:
            fp = os.path.join(root, fn)
            # Exclude large video binaries or scratch temp dumps
            if fn.lower().endswith((".mp4", ".mkv", ".webm", ".mov", ".avi", ".tar", ".zip")):
                continue
            rel = os.path.relpath(fp, BASE_DIR)
            files_to_copy.append(("project", fp, os.path.join(BACKUP_DIR, "project", rel)))

    # B. Active clip_ledger.db & feedback.db from C:\LionReel and data/
    local_dbs = [
        os.path.join(LOCAL_DATA_DIR, "data", "clip_ledger.db"),
        os.path.join(BASE_DIR, "data", "clip_ledger.db"),
        os.path.join(LOCAL_DATA_DIR, "data", "feedback.db"),
        os.path.join(BASE_DIR, "data", "feedback.db"),
        os.path.join(BASE_DIR, "credits_registry.csv"),
        os.path.join(BASE_DIR, "config.json"),
        os.path.join(BASE_DIR, "ui_freeze_manifest.json")
    ]
    for ldb in local_dbs:
        if os.path.isfile(ldb):
            fn = os.path.basename(ldb)
            files_to_copy.append(("db_config", ldb, os.path.join(BACKUP_DIR, "data_config", fn)))

    # C. Models in use
    for mdir in [os.path.join(BASE_DIR, "models"), os.path.join(LOCAL_DATA_DIR, "models")]:
        if os.path.isdir(mdir):
            for root, _, files in os.walk(mdir):
                for fn in files:
                    fp = os.path.join(root, fn)
                    rel = os.path.relpath(fp, mdir)
                    files_to_copy.append(("models", fp, os.path.join(BACKUP_DIR, "models", rel)))

    # D. List of finished outputs with hashes and sizes
    finished_manifest = []
    finished_dir = os.path.join(BASE_DIR, "finished")
    if os.path.isdir(finished_dir):
        for fn in os.listdir(finished_dir):
            fp = os.path.join(finished_dir, fn)
            if os.path.isfile(fp):
                sz = os.path.getsize(fp)
                # For small files, compute sha256; for large mp4 compute first 10MB sha256
                if sz < 20 * 1024 * 1024:
                    h = sha256_file(fp)
                else:
                    h_obj = hashlib.sha256()
                    with open(fp, "rb") as f:
                        h_obj.update(f.read(10 * 1024 * 1024))
                    h = f"partial_10mb_{h_obj.hexdigest()}"
                finished_manifest.append({
                    "filename": fn,
                    "size_bytes": sz,
                    "size_mb": round(sz / (1024 * 1024), 2),
                    "hash": h
                })
                # If it's a credits or report file, copy it directly into backup
                if fn.endswith((".txt", ".json", ".csv")):
                    files_to_copy.append(("finished_credits", fp, os.path.join(BACKUP_DIR, "finished_metadata", fn)))

    with open(os.path.join(BACKUP_DIR, "finished_outputs_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(finished_manifest, f, indent=2)

    # Execute copy and verify checksums
    print(f"Total files queued for backup: {len(files_to_copy)}")
    checksum_manifest = {}
    verified_count = 0
    
    for category, src, dst in files_to_copy:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        src_hash = sha256_file(src)
        dst_hash = sha256_file(dst)
        assert src_hash == dst_hash, f"Checksum verification failed for {src} vs {dst}!"
        checksum_manifest[os.path.relpath(dst, BACKUP_DIR).replace("\\", "/")] = {
            "category": category,
            "sha256": src_hash,
            "size": os.path.getsize(dst)
        }
        verified_count += 1

    manifest_path = os.path.join(BACKUP_DIR, "backup_checksums.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(checksum_manifest, f, indent=2)

    print(f"\nFresh full backup created successfully! ✅")
    print(f"Location: {BACKUP_DIR}")
    print(f"Files backed up & 100% checksum-verified: {verified_count}")
    print(f"Checksum manifest: {manifest_path}")
    return True

if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
