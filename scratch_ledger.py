import sqlite3

conn = sqlite3.connect(r"C:\LionReel\data\clip_ledger.db")
c = conn.cursor()
c.execute("SELECT clip_id, source_id, source_url_or_path, is_verified, sharpness FROM clips WHERE is_verified = 1")
for r in c.fetchall():
    print(r)
conn.close()
