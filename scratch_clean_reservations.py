import sqlite3

conn = sqlite3.connect(r"C:\LionReel\data\clip_ledger.db")
c = conn.cursor()
c.execute("SELECT clip_id, pending_short_id FROM clips WHERE pending_short_id IS NOT NULL")
rows = c.fetchall()
print("Pending reservations:", rows)
if rows:
    c.execute("UPDATE clips SET pending_short_id = NULL WHERE pending_short_id = 'lionreel_cat_acceptance_3min'")
    conn.commit()
    print("Cleaned up reservations for lionreel_cat_acceptance_3min")
conn.close()
