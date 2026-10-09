import sqlite3

conn = sqlite3.connect(r'C:\LionReel\data\clip_ledger.db')
cur = conn.cursor()
cur.execute('SELECT source_url_or_path, count(*) FROM clips WHERE animal_type="cat" GROUP BY source_url_or_path')
print("Clips by source:")
for r in cur.fetchall():
    print(r)

cur.execute('SELECT count(*) FROM clips WHERE pending_short_id IS NOT NULL')
print('Pending / Reserved clips:', cur.fetchone()[0])

cur.execute('SELECT count(*) FROM clips WHERE times_used > 0')
print('Used clips:', cur.fetchone()[0])

cur.execute('SELECT count(*) FROM clips WHERE pending_short_id IS NULL AND times_used = 0 AND animal_type="cat"')
print('Available fresh cat clips:', cur.fetchone()[0])

cur.execute('SELECT * FROM blocked_sources')
print("Blocked sources:")
for r in cur.fetchall():
    print(r)
