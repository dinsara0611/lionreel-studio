import os, sys
sys.path.insert(0, os.path.abspath("."))
from clip_ledger import ClipLedger

ledger = ClipLedger()
with ledger._get_conn() as conn:
    rows = conn.execute("SELECT clip_id, source_id, source_url_or_path, times_used, pool_cycle, pending_short_id FROM clips WHERE animal_type = 'cat'").fetchall()
    print(f"Total clips for cat: {len(rows)}")
    source_counts = {}
    for r in rows:
        s = r["source_id"]
        used = r["times_used"]
        source_counts.setdefault(s, {"total": 0, "unused": 0, "used": 0, "path": r["source_url_or_path"]})
        source_counts[s]["total"] += 1
        if used > 0:
            source_counts[s]["used"] += 1
        else:
            source_counts[s]["unused"] += 1

    for s, counts in source_counts.items():
        print(f"  Source: {s} => total: {counts['total']}, unused: {counts['unused']}, used: {counts['used']}")
        print(f"    Path: {counts['path']} (exists: {os.path.exists(counts['path'])})")
