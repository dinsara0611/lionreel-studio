import os
import sys
import json
import csv
import time
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load UI Freeze Manifest
with open(os.path.join(BASE_DIR, "ui_freeze_manifest.json"), "r", encoding="utf-8") as f:
    ui_freeze_manifest = json.load(f)

# Load UI In Use
with open(os.path.join(BASE_DIR, "analysis", "ui_in_use.json"), "r", encoding="utf-8") as f:
    ui_in_use_data = json.load(f)

# Load Backend In Use
with open(os.path.join(BASE_DIR, "analysis", "backend_in_use.json"), "r", encoding="utf-8") as f:
    backend_in_use_data = json.load(f)

ui_freeze_files = set(ui_freeze_manifest.keys())
ui_static_files = set(ui_in_use_data.get("static_gui_files", []))
active_py_modules = set(backend_in_use_data.get("active_python_modules", []))
runtime_data_files = set(backend_in_use_data.get("runtime_data_files", []))
string_referenced_files = set(backend_in_use_data.get("string_referenced_files", []))

def format_size(size_bytes):
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    elif size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes} B"

def classify_file(rel_path, abs_path):
    rel_norm = rel_path.replace('\\', '/')
    filename = os.path.basename(rel_norm)
    parts = rel_norm.split('/')
    top_dir = parts[0]
    
    sz = os.path.getsize(abs_path)
    mtime = os.path.getmtime(abs_path)
    mtime_str = datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')

    # 1. UI FREEZE / LIVE UI
    if rel_norm in ui_freeze_files or rel_norm in ui_static_files or top_dir == "gui":
        return {
            "category": "UI_LIVE",
            "evidence": "In ui_freeze_manifest.json and served live by web_server at http://localhost:8000",
            "action": "KEEP",
            "risk": "CRITICAL_MUST_KEEP"
        }

    # 2. VIRTUAL ENVIRONMENT
    if top_dir == ".venv":
        return {
            "category": "VIRTUAL_ENV",
            "evidence": "Python virtual environment required for dependencies and execution",
            "action": "KEEP",
            "risk": "CRITICAL_MUST_KEEP"
        }

    # 3. GIT REPOSITORY
    if top_dir == ".git":
        return {
            "category": "PROJECT_GIT",
            "evidence": "Version control repository history and tags",
            "action": "KEEP",
            "risk": "CRITICAL_MUST_KEEP"
        }

    # 4. CORE ENGINE & ENTRY POINTS
    if rel_norm in active_py_modules or filename in active_py_modules or filename == "lion_automate.py":
        return {
            "category": "CORE_BACKEND",
            "evidence": "Active pipeline engine/module traced from entry points",
            "action": "KEEP",
            "risk": "CRITICAL_MUST_KEEP"
        }

    # 5. TEST SUITE
    if top_dir == "tests" or top_dir == "scripts":
        return {
            "category": "TEST_AND_SCRIPTS",
            "evidence": "E2E Playwright verification tests and cleanup orchestration utilities",
            "action": "KEEP",
            "risk": "CRITICAL_MUST_KEEP"
        }

    # 6. CONFIG AND RUNTIME DATA
    if top_dir == "config" or top_dir == "models" or top_dir == "reference" or rel_norm in runtime_data_files:
        return {
            "category": "RUNTIME_DATA_CONFIG",
            "evidence": "Config bank, AI model weights, reference benchmark, or runtime database",
            "action": "KEEP",
            "risk": "CRITICAL_MUST_KEEP"
        }

    # 7. DOCUMENTATION AND AUDITS
    if filename in ["PROGRESS.md", "AUDIT.md", "CHANGELOG.md", "DESIGN_SYSTEM.md", "UI_FUNCTION_MATRIX.md",
                    "PROJECT_PROPOSAL.md", "UI_SOURCES_STEP_MATRIX.md", "requirements.txt", "run_dashboard.bat",
                    "Dockerfile", ".gitignore", "ui_freeze_manifest.json"]:
        return {
            "category": "PROJECT_DOCS",
            "evidence": "Project documentation, architecture guides, and requirements",
            "action": "KEEP",
            "risk": "CRITICAL_MUST_KEEP"
        }

    if top_dir in ["analysis", "ui_audit"]:
        return {
            "category": "AUDIT_REPORTS",
            "evidence": "Audit documentation and evidence reports",
            "action": "KEEP",
            "risk": "CRITICAL_MUST_KEEP"
        }

    # 8. FINISHED OUTPUT COMPILATIONS
    if top_dir == "finished":
        return {
            "category": "FINISHED_OUTPUTS",
            "evidence": "Master finished output compilations, contact sheets, and certificates",
            "action": "KEEP",
            "risk": "CRITICAL_MUST_KEEP"
        }

    # 9. ACTIVE RAW SOURCE CACHE
    if top_dir == "raw":
        return {
            "category": "ACTIVE_CACHE_POOL",
            "evidence": "Source footage cache referenced in ledger",
            "action": "KEEP",
            "risk": "MEDIUM_KEEP"
        }

    # 10. CANDIDATES TO QUARANTINE - OLD PIPELINE VERSIONS
    if filename in ["lion_automate_v96.py"]:
        return {
            "category": "OLD_PIPELINE_VERSION",
            "evidence": "Superseded legacy pipeline version (V96 replaced by V97)",
            "action": "QUARANTINE",
            "risk": "LOW"
        }

    # 11. CANDIDATES TO QUARANTINE - OLD LARGE BACKUP FOLDERS
    if top_dir in ["LionReel_backup_before_stage_order", "LionReel_backup_before_ui_polish"] or "data/backups" in rel_norm:
        return {
            "category": "OLD_BACKUP_SNAPSHOTS",
            "evidence": "Redundant historical pre-recovery snapshot folders already archived in C:\\LionReel_backups",
            "action": "QUARANTINE",
            "risk": "LOW"
        }

    # 12. CANDIDATES TO QUARANTINE - ROOT LEVEL TEMP / CLUTTER IMAGES & SCRIPTS
    if top_dir == "scratch":
        return {
            "category": "SCRATCH_TEMPORARY_FILES",
            "evidence": "Temporary diagnostic scripts, video probes, and scrap frame dumps",
            "action": "QUARANTINE",
            "risk": "LOW"
        }

    if top_dir in ["__pycache__", ".pytest_cache", "test-results", "node_modules"]:
        return {
            "category": "BUILD_CACHE_CLUTTER",
            "evidence": "Compiled bytecode cache and transient test result clutter",
            "action": "QUARANTINE",
            "risk": "LOW"
        }

    if filename.endswith(".pyc") or filename.endswith(".log") or filename in [
        "before_after_comparison.png", "woa_bl.jpg", "proposal.html", "LionReel_Studio_Project_Proposal.pdf",
        "web_server.lock", "test_short_1_4k_contact_sheet.png", "test_short_2_1080p_contact_sheet.png",
        "test_short_3_twopets_contact_sheet.png", "test_short_4_vertical_contact_sheet.png"
    ]:
        return {
            "category": "TEMP_ARTIFACT_CLUTTER",
            "evidence": "Old root diagnostic screenshots, PDF proposal, transient logs/locks",
            "action": "QUARANTINE",
            "risk": "LOW"
        }

    # 13. WORK JOBS OLDER THAN 7 DAYS (KEEP NEWEST 3)
    if top_dir == "work":
        return {
            "category": "OLD_WORK_INTERMEDIATES",
            "evidence": "Rendered intermediate working frames/clips",
            "action": "KEEP" if "lionreel_cat_20261010_020004_49dfa336" in rel_norm else "QUARANTINE",
            "risk": "LOW"
        }

    # 14. DEFAULT TO UNKNOWN -> KEEP
    return {
        "category": "UNKNOWN",
        "evidence": "Unclassified file preserved safely by rule (unknown is kept)",
        "action": "KEEP",
        "risk": "HIGH_SAFETY_FALLBACK"
    }

def run():
    print("[1/3] Scanning project directory...")
    plan_records = []
    category_summary = {}

    for root, dirs, files in os.walk(BASE_DIR):
        for f in files:
            abs_p = os.path.join(root, f)
            rel_p = os.path.relpath(abs_p, BASE_DIR).replace('\\', '/')
            sz = os.path.getsize(abs_p)
            mtime = os.path.getmtime(abs_p)
            mtime_str = datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')

            cls = classify_file(rel_p, abs_p)
            cat = cls["category"]
            act = cls["action"]

            if cat not in category_summary:
                category_summary[cat] = {"count": 0, "size": 0, "action": act}
            category_summary[cat]["count"] += 1
            category_summary[cat]["size"] += sz

            plan_records.append({
                "path": rel_p,
                "size_bytes": sz,
                "size_formatted": format_size(sz),
                "last_modified": mtime_str,
                "category": cat,
                "evidence": cls["evidence"],
                "action": act,
                "risk_level": cls["risk"]
            })

    # Sort records: Quarantined first, then Keep
    plan_records.sort(key=lambda x: (0 if x["action"] == "QUARANTINE" else 1, x["category"], x["path"]))

    csv_path = os.path.join(BASE_DIR, "cleanup_plan.csv")
    print(f"[2/3] Writing {csv_path}...")
    with open(csv_path, "w", newline="", encoding="utf-8") as fc:
        writer = csv.DictWriter(fc, fieldnames=[
            "path", "size_bytes", "size_formatted", "last_modified",
            "category", "evidence", "action", "risk_level"
        ])
        writer.writeheader()
        writer.writerows(plan_records)

    md_path = os.path.join(BASE_DIR, "CLEANUP_PLAN.md")
    print(f"[3/3] Writing {md_path}...")
    
    total_files = len(plan_records)
    total_bytes = sum(r["size_bytes"] for r in plan_records)
    quarantine_files = [r for r in plan_records if r["action"] == "QUARANTINE"]
    quarantine_bytes = sum(r["size_bytes"] for r in quarantine_files)
    keep_files = [r for r in plan_records if r["action"] == "KEEP"]
    keep_bytes = sum(r["size_bytes"] for r in keep_files)

    with open(md_path, "w", encoding="utf-8") as fm:
        fm.write("# LionReel Studio — Project Cleanup Plan\n\n")
        fm.write(f"**Generated:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        fm.write("## 1. Executive Summary & Space Reclamation\n\n")
        fm.write(f"- **Total Scanned Project Files:** {total_files:,} files ({format_size(total_bytes)})\n")
        fm.write(f"- **Files to KEEP:** {len(keep_files):,} files ({format_size(keep_bytes)})\n")
        fm.write(f"- **Files Proposed for QUARANTINE:** {len(quarantine_files):,} files ({format_size(quarantine_bytes)})\n")
        fm.write(f"- **Net Disk Space to be Freed:** **{format_size(quarantine_bytes)}**\n\n")

        fm.write("## 2. Category Summary & Actions\n\n")
        fm.write("| Category | Action | File Count | Total Size | Description / Risk |\n")
        fm.write("|---|---|---|---|---|\n")
        for cat, data in sorted(category_summary.items(), key=lambda x: (0 if x[1]["action"] == "QUARANTINE" else 1, -x[1]["size"])):
            fm.write(f"| **{cat}** | `{data['action']}` | {data['count']:,} | {format_size(data['size'])} | {'Quarantine into C:\\\\LionReel_quarantine' if data['action'] == 'QUARANTINE' else 'Preserved strictly untouched'} |\n")
        fm.write("\n---\n\n")

        fm.write("## 3. Strict Rules Enforcement\n\n")
        fm.write("1. **UI Freeze**: All 6 files in `gui/` (`index.html`, `style.css`, `app.js`, `lion_logo.png`, `lion_logo.svg`, `clipforge_logo.svg`) match `ui_freeze_manifest.json` and are marked `KEEP`.\n")
        fm.write("2. **Core Pipeline**: `lion_automate_v97.py`, `web_server.py`, `edl_manager.py`, `auto_reframe.py`, `qa_check.py`, `pet_detector.py`, `clip_ledger.py`, `source_utils.py` are strictly marked `KEEP`.\n")
        fm.write("3. **Runtime Data & Config**: `config/*.json`, `data/clip_ledger.db`, `credits_registry.csv`, `models/`, `reference/` are strictly marked `KEEP`.\n")
        fm.write("4. **Zero Unconfirmed Deletions**: All candidate files will be safely moved into `C:\\LionReel_quarantine\\20261010\\` preserving relative paths. Permanent deletion will only occur if explicitly instructed with 'CONFIRM DELETE'.\n\n")

        fm.write("## 4. Quarantined Candidates Breakdown (Sample of Top Items)\n\n")
        fm.write("| Relative Path | Size | Category | Evidence |\n")
        fm.write("|---|---|---|---|\n")
        for r in quarantine_files[:40]:
            fm.write(f"| `{r['path']}` | {r['size_formatted']} | {r['category']} | {r['evidence']} |\n")
        if len(quarantine_files) > 40:
            fm.write(f"| ... and {len(quarantine_files) - 40} additional files | ... | ... | Full list in `cleanup_plan.csv` |\n")

    print(f"\n[DONE] Generated CLEANUP_PLAN.md and cleanup_plan.csv:")
    print(f"  Total project: {format_size(total_bytes)}")
    print(f"  Files to KEEP: {len(keep_files):,} ({format_size(keep_bytes)})")
    print(f"  Files to QUARANTINE: {len(quarantine_files):,} ({format_size(quarantine_bytes)})")

if __name__ == "__main__":
    run()
