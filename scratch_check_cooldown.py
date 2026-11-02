from clip_ledger import ClipLedger

l = ClipLedger()
cd_sources = l.get_cooldown_sources('cat', last_n_jobs=3)
print('Recent source IDs in cooldown:', cd_sources)

with l._get_conn() as conn:
    rows = conn.execute("SELECT source_id, COUNT(*) as cnt FROM clips WHERE is_verified = 1 AND animal_type = 'cat' GROUP BY source_id").fetchall()
    print('Verified clips per source:')
    for r in rows:
        sid = r["source_id"]
        cnt = r["cnt"]
        status = "(cooldown)" if sid in cd_sources else "(USABLE)"
        print(f"  {sid}: {cnt} clips {status}")

    # Check unverified rows
    unver = conn.execute("SELECT clip_id, source_id, status FROM clips WHERE is_verified = 0 AND animal_type = 'cat' AND (rejection_reason IS NULL OR rejection_reason = '')").fetchall()
    print('Pending unverified rows:', len(unver))
    for u in unver:
        print(f"  {u['clip_id']}: source={u['source_id']} status={u['status']}")
