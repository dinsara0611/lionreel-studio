import sqlite3
import os

db = r"C:\LionReel\data\clip_ledger.db"
conn = sqlite3.connect(db)
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM clips WHERE is_verified=1")
v_count = cur.fetchone()[0]

cur.execute("SELECT COUNT(DISTINCT source_id) FROM clips WHERE is_verified=1")
v_sources = cur.fetchone()[0]

cur.execute("SELECT SUM(end_s - start_s) FROM clips WHERE is_verified=1")
v_sec = cur.fetchone()[0] or 0.0

cur.execute("SELECT COUNT(*) FROM clips WHERE is_verified=1 AND times_used=0")
unused_v_count = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM blocked_sources")
b_count = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM clips")
total_clips = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM finished_video_windows")
fvw_count = cur.fetchone()[0]

# Average clip duration
avg_clip_dur = (v_sec / v_count) if v_count else 7.5

print(f"Total Clips in Ledger: {total_clips}")
print(f"Verified Clips in Bank: {v_count} (across {v_sources} distinct sources)")
print(f"Total Bank Verified Duration: {v_sec:.1f} s ({v_sec/60.0:.2f} min)")
print(f"Fresh Unused Verified Clips: {unused_v_count}")
print(f"Finished Video Windows Logged: {fvw_count}")
print(f"Blocked Sources: {b_count}")
print(f"Average Verified Clip Duration: {avg_clip_dur:.2f} s")
