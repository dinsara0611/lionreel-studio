import os
import sys
import shutil
import sqlite3
import csv
import json
import time

db_path = r'C:\LionReel\data\clip_ledger.db'
credits_path = 'credits_registry.csv'
date_str = time.strftime('%Y%m%d')
ts_iso = time.strftime('%Y-%m-%dT%H:%M:%S')
quarantine_dir = os.path.join(r'C:\LionReel_quarantine', f'synthetic_{date_str}')
os.makedirs(quarantine_dir, exist_ok=True)
files_quarantine_dir = os.path.join(quarantine_dir, 'files')
os.makedirs(files_quarantine_dir, exist_ok=True)

manifest = {
    'timestamp': ts_iso,
    'quarantine_dir': quarantine_dir,
    'database': db_path,
    'quarantined_db_rows': [],
    'quarantined_files': [],
    'quarantined_credits': []
}

# 1. Database Quarantine
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Create quarantined_clips table if not exists
cur.execute("""
CREATE TABLE IF NOT EXISTS quarantined_clips (
    clip_id TEXT PRIMARY KEY,
    source_id TEXT,
    source_url_or_path TEXT,
    license TEXT,
    start_s REAL,
    end_s REAL,
    fingerprint TEXT,
    quality_score REAL,
    funny_score REAL,
    animal_type TEXT,
    times_used INTEGER,
    last_used_short_id TEXT,
    pending_short_id TEXT,
    pool_cycle INTEGER,
    is_verified INTEGER,
    framing_score REAL,
    sharpness REAL,
    orientation TEXT,
    compilation_flag INTEGER,
    uploader TEXT,
    title TEXT,
    verified_plan TEXT,
    verified_at TEXT,
    quarantine_date TEXT,
    quarantine_reason TEXT
)
""")

# Find rows to quarantine:
# Criteria: source_url_or_path contains 'src_' OR (framing_score == 0.95 and (verified_plan IS NULL OR verified_plan = ''))
cur.execute("""
SELECT * FROM clips
WHERE source_url_or_path LIKE '%src_%'
   OR (framing_score = 0.95 AND (verified_plan IS NULL OR verified_plan = ''))
""")
rows_to_quarantine = [dict(r) for r in cur.fetchall()]
print(f"Found {len(rows_to_quarantine)} database rows to quarantine.")

for r in rows_to_quarantine:
    r['quarantine_date'] = ts_iso
    r['quarantine_reason'] = "SYNTHETIC_DATA_NO_EVIDENCE"
    manifest['quarantined_db_rows'].append(r['clip_id'])
    
    # Insert into quarantined_clips
    cols = list(r.keys())
    placeholders = ", ".join(["?"] * len(cols))
    col_str = ", ".join(cols)
    vals = [r[c] for c in cols]
    cur.execute(f"INSERT OR REPLACE INTO quarantined_clips ({col_str}) VALUES ({placeholders})", vals)
    
    # Delete from active clips table
    cur.execute("DELETE FROM clips WHERE clip_id = ?", (r['clip_id'],))

# Also clean any stale reservations
cur.execute("UPDATE clips SET pending_short_id = NULL WHERE pending_short_id = 'lionreel_cat_20261012_001844_49a37061'")
conn.commit()

# Check remaining verified rows
remaining_verified = cur.execute("SELECT count(*) FROM clips WHERE is_verified = 1").fetchone()[0]
total_remaining = cur.execute("SELECT count(*) FROM clips").fetchone()[0]
print(f"Database quarantine complete. Total remaining: {total_remaining}, Remaining verified: {remaining_verified}")
conn.close()

# 2. File Quarantine: Move matching src_* files from raw/
raw_dir = "raw"
for f in os.listdir(raw_dir):
    if f.startswith("src_vert_cat_") or f.startswith("src_horiz_cat_"):
        src_f = os.path.join(raw_dir, f)
        dst_f = os.path.join(files_quarantine_dir, f)
        shutil.move(src_f, dst_f)
        manifest['quarantined_files'].append({
            'filename': f,
            'original_path': os.path.abspath(src_f),
            'quarantine_path': os.path.abspath(dst_f)
        })
        print(f"Quarantined file: {f} -> {dst_f}")

# 3. Credits Registry Quarantine
credits_bak = "credits_registry.csv.bak"
shutil.copy2(credits_path, credits_bak)
quarantined_credits_file = "credits_registry_quarantined.csv"

kept_rows = []
quarantined_rows = []

with open(credits_path, 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    for row in reader:
        if row and any("src_" in cell for cell in row):
            quarantined_rows.append(row)
            manifest['quarantined_credits'].append(row)
        else:
            kept_rows.append(row)

with open(quarantined_credits_file, 'w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerows(quarantined_rows)

with open(credits_path, 'w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerows(kept_rows)

print(f"Credits registry cleaned: {len(quarantined_rows)} rows moved to {quarantined_credits_file}, {len(kept_rows)} kept.")

# 4. Save manifest
manifest_path = os.path.join(quarantine_dir, "quarantine_manifest.json")
with open(manifest_path, 'w', encoding='utf-8') as f:
    json.dump(manifest, f, indent=2)

# Also save copy in root for easy discovery
shutil.copy2(manifest_path, "quarantine_manifest.json")

# 5. Create restore script
restore_script_content = f'''"""
RESTORE SCRIPT FOR QUARANTINE: {quarantine_dir}
"""
import os, sys, shutil, sqlite3, csv, json

quarantine_dir = r"{quarantine_dir}"
db_path = r"{db_path}"
credits_path = r"{os.path.abspath(credits_path)}"
quarantined_credits_file = r"{os.path.abspath(quarantined_credits_file)}"

with open(os.path.join(quarantine_dir, "quarantine_manifest.json"), "r", encoding="utf-8") as f:
    manifest = json.load(f)

# 1. Restore database rows
conn = sqlite3.connect(db_path)
cur = conn.cursor()
for cid in manifest["quarantined_db_rows"]:
    row = cur.execute("SELECT * FROM quarantined_clips WHERE clip_id = ?", (cid,)).fetchone()
    if row:
        # Get column names except quarantine_date, quarantine_reason
        col_names = [d[0] for d in cur.description if d[0] not in ("quarantine_date", "quarantine_reason")]
        val_placeholders = ", ".join(["?"] * len(col_names))
        col_str = ", ".join(col_names)
        vals = [row[i] for i, d in enumerate(cur.description) if d[0] in col_names]
        cur.execute(f"INSERT OR REPLACE INTO clips ({{col_str}}) VALUES ({{val_placeholders}})", vals)
        cur.execute("DELETE FROM quarantined_clips WHERE clip_id = ?", (cid,))
conn.commit()
conn.close()
print(f"Restored {{len(manifest['quarantined_db_rows'])}} database rows.")

# 2. Restore files
for item in manifest["quarantined_files"]:
    if os.path.exists(item["quarantine_path"]):
        shutil.move(item["quarantine_path"], item["original_path"])
        print(f"Restored file: {{item['filename']}}")

# 3. Restore credits
if os.path.exists(quarantined_credits_file):
    with open(quarantined_credits_file, "r", encoding="utf-8") as f_q:
        q_rows = list(csv.reader(f_q))
    with open(credits_path, "a", encoding="utf-8", newline="") as f_c:
        writer = csv.writer(f_c)
        writer.writerows(q_rows)
    print(f"Restored {{len(q_rows)}} credits entries.")

print("Restore complete.")
'''

with open(os.path.join(quarantine_dir, "restore_quarantine.py"), "w", encoding="utf-8") as f:
    f.write(restore_script_content)

with open("restore_quarantine.py", "w", encoding="utf-8") as f:
    f.write(restore_script_content)

print(f"Quarantine completed successfully in {quarantine_dir}")
