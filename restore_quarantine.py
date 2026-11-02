r"""
RESTORE SCRIPT FOR QUARANTINE: C:\LionReel_quarantine\synthetic_20261012
"""
import os, sys, shutil, sqlite3, csv, json

quarantine_dir = r"C:\LionReel_quarantine\synthetic_20261012"
db_path = r"C:\LionReel\data\clip_ledger.db"
credits_path = r"G:\My Drive\Cat make\credits_registry.csv"
quarantined_credits_file = r"G:\My Drive\Cat make\credits_registry_quarantined.csv"

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
        cur.execute(f"INSERT OR REPLACE INTO clips ({col_str}) VALUES ({val_placeholders})", vals)
        cur.execute("DELETE FROM quarantined_clips WHERE clip_id = ?", (cid,))
conn.commit()
conn.close()
print(f"Restored {len(manifest['quarantined_db_rows'])} database rows.")

# 2. Restore files
for item in manifest["quarantined_files"]:
    if os.path.exists(item["quarantine_path"]):
        shutil.move(item["quarantine_path"], item["original_path"])
        print(f"Restored file: {item['filename']}")

# 3. Restore credits
if os.path.exists(quarantined_credits_file):
    with open(quarantined_credits_file, "r", encoding="utf-8") as f_q:
        q_rows = list(csv.reader(f_q))
    with open(credits_path, "a", encoding="utf-8", newline="") as f_c:
        writer = csv.writer(f_c)
        writer.writerows(q_rows)
    print(f"Restored {len(q_rows)} credits entries.")

print("Restore complete.")
