import sqlite3
conn = sqlite3.connect(r'C:\LionReel\data\clip_ledger.db')
cur = conn.execute("""
    SELECT clip_id, source_url_or_path FROM clips
    WHERE source_url_or_path LIKE '%src_vert%'
       OR source_url_or_path LIKE '%src_horiz%'
       OR clip_id LIKE 'test_syn_%'
       OR clip_id LIKE '%synthetic%'
""")
rows = cur.fetchall()
print('Found test rows:', len(rows))
for r in rows:
    print(' ', r[0], ':', r[1])

conn.execute("""
    DELETE FROM clips
    WHERE source_url_or_path LIKE '%src_vert%'
       OR source_url_or_path LIKE '%src_horiz%'
       OR clip_id LIKE 'test_syn_%'
       OR clip_id LIKE '%synthetic%'
""")
conn.commit()
print('Deleted test rows successfully.')
