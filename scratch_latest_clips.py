from clip_ledger import ClipLedger

l = ClipLedger()
with l._get_conn() as conn:
    rows = conn.execute("SELECT rowid, clip_id, source_id, is_verified, verified_at, rejection_reason FROM clips ORDER BY rowid DESC LIMIT 10").fetchall()
    print("Latest 10 clips in DB:")
    for r in rows:
        print(f"  rowid={r['rowid']} | id={r['clip_id']} | ver={r['is_verified']} | at={r['verified_at']} | rej={r['rejection_reason']}")
