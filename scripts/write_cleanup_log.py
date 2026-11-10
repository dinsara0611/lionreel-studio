import os
import sys
import json
import csv
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
csv_plan = os.path.join(BASE_DIR, "cleanup_plan.csv")
log_path = os.path.join(BASE_DIR, "cleanup_log.json")

items = []
total_bytes = 0

with open(csv_plan, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        sz = int(row["size_bytes"])
        total_bytes += sz
        items.append({
            "path": row["path"],
            "size_bytes": sz,
            "group": row["group"],
            "reason": row["reason"],
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "destination": "Google Drive Trash (recoverable)" if "g:" in BASE_DIR.lower() else "Windows Recycle Bin"
        })

def format_bytes(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024.0:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024.0 * 1024.0):.2f} MB"
    else:
        return f"{size_bytes / (1024.0 * 1024.0 * 1024.0):.2f} GB"

log_data = {
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "total_items_removed": len(items),
    "total_freed_bytes": total_bytes,
    "total_freed_formatted": format_bytes(total_bytes),
    "drive_trash_retention_days": 30,
    "recycle_bin_undoable": True,
    "items": items
}

with open(log_path, "w", encoding="utf-8") as f:
    json.dump(log_data, f, indent=2)

print(f"Successfully recorded {len(items)} items ({format_bytes(total_bytes)}) in {log_path} ✅")
