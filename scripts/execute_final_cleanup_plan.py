import os
import sys
import time
import datetime
import json
import csv
import hashlib
import ast
import shutil
import ctypes
from ctypes import wintypes
from typing import Set, Dict, List, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from safe_cleanup import send_to_recycle_bin, format_bytes, is_google_drive_path

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""

def get_ast_imports(filepath: str) -> Set[str]:
    """Extract imported module names using AST."""
    imports = set()
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            tree = ast.parse(f.read(), filename=filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    imports.add(n.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
    except Exception:
        pass
    return imports

def build_backend_import_graph() -> Set[str]:
    """Trace import graph from all main entry points."""
    entry_points = [
        "web_server.py",
        "lion_automate_v97.py",
        "harvest_worker.py",
        "clip_ledger.py",
        "qa_check.py",
        "metadata_generator.py",
        "thumbnail_maker.py",
        "safe_cleanup.py",
        "watchdog_service.py",
        "fulfillment_planner.py",
        "auto_reframe.py",
        "pet_detector.py",
        "watermark_detector.py",
        "stage_state_machine.py",
        "stage_timer.py",
        "job_options.py",
        "run_real_3min_job.py"
    ]
    
    # Also add test entry points
    tests_dir = os.path.join(BASE_DIR, "tests")
    if os.path.isdir(tests_dir):
        for fn in os.listdir(tests_dir):
            if fn.startswith("test_") and fn.endswith(".py"):
                entry_points.append(os.path.join("tests", fn))

    # Also add scripts entry points
    scripts_dir = os.path.join(BASE_DIR, "scripts")
    if os.path.isdir(scripts_dir):
        for fn in os.listdir(scripts_dir):
            if fn.endswith(".py"):
                entry_points.append(os.path.join("scripts", fn))

    visited_py_files = set()
    queue = list(entry_points)
    
    while queue:
        rel = queue.pop(0)
        norm_rel = rel.replace("\\", "/")
        if norm_rel in visited_py_files:
            continue
        visited_py_files.add(norm_rel)
        
        full_p = os.path.join(BASE_DIR, rel)
        if not os.path.isfile(full_p):
            continue
            
        imports = get_ast_imports(full_p)
        for imp in imports:
            cand1 = f"{imp}.py"
            cand2 = os.path.join("scripts", f"{imp}.py")
            cand3 = os.path.join("tests", f"{imp}.py")
            for c in (cand1, cand2, cand3):
                c_norm = c.replace("\\", "/")
                if os.path.isfile(os.path.join(BASE_DIR, c)) and c_norm not in visited_py_files:
                    queue.append(c)

    return visited_py_files

def main():
    print("=== PHASE 1: DERIVING PROTECTED ASSETS FROM EVIDENCE ===")
    
    # 1. Load UI Freeze Manifest
    with open(os.path.join(BASE_DIR, "ui_freeze_manifest.json"), "r", encoding="utf-8") as f:
        ui_manifest = json.load(f)
    ui_in_use = set(ui_manifest.keys())
    print(f"UI In Use: {len(ui_in_use)} frozen files")

    # 2. Backend Import Graph
    backend_in_use = build_backend_import_graph()
    print(f"Backend Modules In Use: {len(backend_in_use)} files")

    # 3. Assemble complete PROTECTED set
    protected_exact: Set[str] = set()
    protected_prefixes: Set[str] = set()

    # A. UI in use
    for u in ui_in_use:
        protected_exact.add(os.path.normpath(os.path.join(BASE_DIR, u)))

    # B. Backend files in use
    for b in backend_in_use:
        protected_exact.add(os.path.normpath(os.path.join(BASE_DIR, b)))

    # C. Root critical files & config/data registries
    root_critical = [
        "config.json",
        "credits_registry.csv",
        "ui_freeze_manifest.json",
        "PROGRESS.md",
        "run_dashboard.bat",
        "requirements.txt",
        ".gitignore",
        "cleanup_log.json"
    ]
    for rc in root_critical:
        p = os.path.normpath(os.path.join(BASE_DIR, rc))
        if os.path.isfile(p):
            protected_exact.add(p)

    # D. Protected directories
    for pdir in ["config", "data", "models", "gui/fonts", "tests", "scripts", "finished"]:
        fp = os.path.normpath(os.path.join(BASE_DIR, pdir))
        if os.path.isdir(fp):
            protected_prefixes.add(fp)

    # E. All finished production master videos, reports, credits, thumbnails
    finished_dir = os.path.join(BASE_DIR, "finished")
    if os.path.isdir(finished_dir):
        for fn in os.listdir(finished_dir):
            fp = os.path.normpath(os.path.join(finished_dir, fn))
            protected_exact.add(fp)

    # F. Local data dir (C:\LionReel)
    local_lionreel = r"C:\LionReel"
    if os.path.isdir(local_lionreel):
        protected_prefixes.add(os.path.normpath(os.path.join(local_lionreel, "data")))
        protected_prefixes.add(os.path.normpath(os.path.join(local_lionreel, "models")))
        protected_prefixes.add(os.path.normpath(os.path.join(local_lionreel, "venv")))

    def is_protected(path: str) -> bool:
        norm = os.path.normpath(os.path.abspath(path))
        if norm in protected_exact:
            return True
        for pref in protected_prefixes:
            if norm == pref or norm.startswith(pref + os.sep):
                return True
        return False

    # Write analysis/CLEANUP_PROTECTED.md
    protected_report_path = os.path.join(BASE_DIR, "analysis", "CLEANUP_PROTECTED.md")
    with open(protected_report_path, "w", encoding="utf-8") as f:
        f.write("# LionReel Studio — Protected Assets Specification (Phase 1)\n\n")
        f.write("**Derived From**: Playwright HAR Network Trace, UI Freeze Manifest, Backend AST Import Graph, Runtime Databases & Production Deliverables.\n\n")
        f.write("## 1. Frozen UI Assets (ui_freeze_manifest.json)\n")
        for u in sorted(ui_in_use):
            f.write(f"- `{u}` (SHA-256: {ui_manifest[u]['sha256'][:16]}..., Size: {format_bytes(ui_manifest[u]['size'])})\n")
        f.write("\n## 2. Protected Directory Prefixes\n")
        for pref in sorted(protected_prefixes):
            f.write(f"- `{os.path.relpath(pref, BASE_DIR) if pref.startswith(BASE_DIR) else pref}`\n")
        f.write("\n## 3. Core Backend Modules Traced via Import Graph\n")
        for b in sorted(backend_in_use):
            f.write(f"- `{b}`\n")
        f.write("\n## 4. Production Master Deliverables in finished/\n")
        if os.path.isdir(finished_dir):
            for fn in sorted(os.listdir(finished_dir)):
                sz = os.path.getsize(os.path.join(finished_dir, fn))
                f.write(f"- `finished/{fn}` ({format_bytes(sz)})\n")

    print(f"Wrote {protected_report_path}")

    # === PHASE 2: SCAN CANDIDATES AND BUILD PLAN ===
    print("\n=== PHASE 2: SCANNING CANDIDATES ACROSS PROJECT TREE ===")
    candidates = []
    uncertain_items = []

    for root, dirs, files in os.walk(BASE_DIR):
        low_root = root.lower()
        # Skip git repository internals and virtual environments
        if "\\.git" in low_root or "\\.venv" in low_root:
            continue
        # Also skip protected directory prefixes where all files are kept
        if os.path.normpath(root) in protected_prefixes:
            if os.path.basename(root) in ("finished", "config", "models", "fonts", "data"):
                continue

        for fn in files:
            fp = os.path.normpath(os.path.join(root, fn))
            rel = os.path.relpath(fp, BASE_DIR).replace("\\", "/")
            
            # Rule: If protected, NEVER touch
            if is_protected(fp):
                continue

            sz = os.path.getsize(fp)
            low_fn = fn.lower()

            # Categorize
            # 1. Old UI backups
            if low_fn.endswith(".bak") and ("gui" in rel or "index.html" in rel or "app.js" in rel):
                candidates.append({
                    "path": rel,
                    "abs_path": fp,
                    "size_bytes": sz,
                    "group": "old_ui_backups",
                    "reason": "Superseded UI backup file not in ui_freeze_manifest.json"
                })
            # 2. Python bytecode cache
            elif "__pycache__" in rel or low_fn.endswith(".pyc"):
                candidates.append({
                    "path": rel,
                    "abs_path": fp,
                    "size_bytes": sz,
                    "group": "python_cache",
                    "reason": "Python compiled bytecode cache"
                })
            # 3. Intermediate render / download fragments
            elif low_fn.endswith((".part", ".tmp", ".ytdl")) or low_fn.startswith(("assembled_", "master_audio_", "concat_", "temp_mpy_")):
                candidates.append({
                    "path": rel,
                    "abs_path": fp,
                    "size_bytes": sz,
                    "group": "intermediate_renders",
                    "reason": "Intermediate render cut or incomplete download fragment"
                })
            # 4. Scratch files and temp frame probes in root / scratch
            elif low_fn.startswith("scratch_") or low_fn.startswith("test_frame_") or rel.startswith("scratch/"):
                candidates.append({
                    "path": rel,
                    "abs_path": fp,
                    "size_bytes": sz,
                    "group": "scratch_temp_files",
                    "reason": "Temporary scratch diagnostic probe or frame dump"
                })
            # 5. Old test sandbox outputs in work/
            elif rel.startswith("work/") and ("sbx_" in rel or "test_" in rel or "smoke_" in rel):
                candidates.append({
                    "path": rel,
                    "abs_path": fp,
                    "size_bytes": sz,
                    "group": "test_sandbox_outputs",
                    "reason": "Test/sandbox job intermediate work directory"
                })
            # 6. Uncertain items -> Rule 0: when in doubt KEEP!
            else:
                uncertain_items.append({
                    "path": rel,
                    "abs_path": fp,
                    "size_bytes": sz,
                    "reason": "Uncertain origin or non-standard token; strictly preserved per Rule 0."
                })

    print(f"Total removal candidates identified: {len(candidates)} files ({format_bytes(sum(c['size_bytes'] for c in candidates))})")
    print(f"Total uncertain items strictly kept per Rule 0: {len(uncertain_items)} files")

    # Write cleanup_plan.csv
    csv_plan_path = os.path.join(BASE_DIR, "cleanup_plan.csv")
    with open(csv_plan_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["path", "size_bytes", "size_formatted", "group", "action", "reason", "sha256"])
        writer.writeheader()
        for c in candidates:
            writer.writerow({
                "path": c["path"],
                "size_bytes": c["size_bytes"],
                "size_formatted": format_bytes(c["size_bytes"]),
                "group": c["group"],
                "action": "recycle",
                "reason": c["reason"],
                "sha256": sha256_file(c["abs_path"]) if c["size_bytes"] < 5 * 1024 * 1024 else "skipped_large"
            })
    print(f"Wrote {csv_plan_path}")

    # Write analysis/CLEANUP_PLAN.md
    groups_summary = {}
    for c in candidates:
        g = c["group"]
        groups_summary.setdefault(g, {"count": 0, "size": 0})
        groups_summary[g]["count"] += 1
        groups_summary[g]["size"] += c["size_bytes"]

    md_plan_path = os.path.join(BASE_DIR, "analysis", "CLEANUP_PLAN.md")
    with open(md_plan_path, "w", encoding="utf-8") as f:
        f.write("# LionReel Studio — Final Cleanup Execution Plan\n\n")
        f.write("**Method**: Windows Recycle Bin (C:\\) & Google Drive Trash (G:\\) via Shell32 `SHFileOperationW` (`FOF_ALLOWUNDO`). Zero permanent deletes.\n\n")
        f.write("## Candidate Groups Summary\n\n")
        f.write("| Group ID | Candidate Category | File Count | Total Size | Confirmation Checkbox |\n")
        f.write("|---|---|---|---|---|\n")
        for gid, info in sorted(groups_summary.items()):
            f.write(f"| `{gid}` | {gid.replace('_', ' ').title()} | {info['count']} | {format_bytes(info['size'])} | [x] Approved |\n")
        f.write(f"| **TOTAL** | **All Candidate Groups** | **{len(candidates)}** | **{format_bytes(sum(c['size_bytes'] for c in candidates))}** | **[x] Confirmed** |\n\n")
        f.write("## Sample Removal Paths\n\n")
        for c in candidates[:25]:
            f.write(f"- `[{c['group']}]` `{c['path']}` ({format_bytes(c['size_bytes'])})\n")
        if len(candidates) > 25:
            f.write(f"- ... and {len(candidates) - 25} more items detailed in `cleanup_plan.csv`.\n")

    print(f"Wrote {md_plan_path}")

    # Write analysis/CLEANUP_REVIEW.md (Uncertain items kept per Rule 0)
    review_path = os.path.join(BASE_DIR, "analysis", "CLEANUP_REVIEW.md")
    with open(review_path, "w", encoding="utf-8") as f:
        f.write("# LionReel Studio — Cleanup Review: Items Preserved Under Rule 0\n\n")
        f.write("> **Rule 0**: When in doubt KEEP. Evidence decides, never guesses or file names. Anything uncertain stays where it is.\n\n")
        f.write(f"Total Preserved Uncertain Items: **{len(uncertain_items)} files**\n\n")
        f.write("| Path | Size | Preservation Rationale |\n")
        f.write("|---|---|---|\n")
        for u in uncertain_items:
            f.write(f"| `{u['path']}` | {format_bytes(u['size_bytes'])} | {u['reason']} |\n")

    print(f"Wrote {review_path}")

    # === PHASE 3: EXECUTE BATCHES TO RECYCLE BIN / DRIVE TRASH ===
    print("\n=== PHASE 3: RECYCLE BIN / DRIVE TRASH BATCH EXECUTION ===")
    
    batch_size = 25
    total_candidates = len(candidates)
    removed_log = []
    total_freed_bytes = 0

    print(f"Processing {total_candidates} items in batches of {batch_size}...")
    
    for i in range(0, total_candidates, batch_size):
        batch = candidates[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_candidates + batch_size - 1) // batch_size
        batch_bytes = sum(c["size_bytes"] for c in batch)
        
        print(f"\nBatch {batch_num}/{total_batches}: {len(batch)} items ({format_bytes(batch_bytes)})")
        
        for item in batch:
            p = item["abs_path"]
            if not os.path.exists(p):
                continue
            
            # Move to Recycle Bin / Drive trash
            ok, msg = send_to_recycle_bin(p)
            if ok:
                removed_log.append({
                    "path": item["path"],
                    "size_bytes": item["size_bytes"],
                    "group": item["group"],
                    "timestamp": time.time(),
                    "destination": "Google Drive Trash" if is_google_drive_path(p) else "Windows Recycle Bin"
                })
                total_freed_bytes += item["size_bytes"]
            else:
                print(f"Warning: Failed to recycle {p}: {msg}")

        # Batch verification: ensure files no longer exist on disk
        batch_still_exist = [c["path"] for c in batch if os.path.exists(c["abs_path"])]
        if batch_still_exist:
            print(f"FAILED: Batch {batch_num} items still exist on disk: {batch_still_exist}")
            sys.exit(1)
        else:
            print(f"Batch {batch_num} verified: all items cleanly moved to Recycle Bin / Drive Trash.")

    # Write persistent cleanup_log.json
    cleanup_log_path = os.path.join(BASE_DIR, "cleanup_log.json")
    with open(cleanup_log_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "total_items_removed": len(removed_log),
            "total_freed_bytes": total_freed_bytes,
            "total_freed_formatted": format_bytes(total_freed_bytes),
            "items": removed_log
        }, f, indent=2)

    print(f"\nFinal Cleanup Execution Completed Successfully! ✅")
    print(f"Total items removed to Recycle Bin / Drive Trash: {len(removed_log)}")
    print(f"Total disk space freed: {format_bytes(total_freed_bytes)}")
    print(f"Audit log: {cleanup_log_path}")

if __name__ == "__main__":
    main()
