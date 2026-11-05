"""
Read-only audit: asks the platform what licence and creator each bank source shows.

Reads the ledger, never writes it. Fetches metadata only, downloads no video.
Results go to data/source_licenses.json and analysis/SOURCE_LICENSE_AUDIT.md.

    python scripts/audit_source_licenses.py
"""
import collections
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import clip_ledger
import source_licenses as sl


def main():
    db = sqlite3.connect(f"file:{clip_ledger.get_ledger_db_path()}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    verified = collections.Counter()
    used = collections.Counter()
    ids = set()
    for r in db.execute("SELECT source_url_or_path p, is_verified v FROM clips"):
        vid = sl.video_id_from(r["p"])
        if vid:
            ids.add(vid)
            verified[vid] += int(r["v"] or 0)
    for r in db.execute("SELECT source_id, source_url_or_path p FROM finished_video_windows WHERE is_production = 1"):
        vid = sl.video_id_from(r["p"]) or sl.video_id_from(r["source_id"])
        if vid:
            ids.add(vid)
            used[vid] += 1

    lines = ["# Source licence audit", "", "| Video | Creator | Licence shown | Status | Verified windows | Windows in finished videos |", "|---|---|---|---|---|---|"]
    for vid in sorted(ids):
        try:
            rec = sl.fetch_record(vid)
            sl.save_record(vid, rec)
        except Exception as e:
            rec = {"status": f"lookup failed: {str(e)[:60]}", "creator": None, "license": None}
        lines.append(f"| {vid} | {rec.get('creator') or sl.NOT_RECORDED} | {rec.get('license') or 'none'} | {rec['status']} | {verified[vid]} | {used[vid]} |")
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "analysis", "SOURCE_LICENSE_AUDIT.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{len(ids)} sources checked, wrote {out}")


if __name__ == "__main__":
    main()
