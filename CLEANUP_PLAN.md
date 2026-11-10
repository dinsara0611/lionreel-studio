# LionReel Studio — Project Cleanup Plan

**Generated:** 2026-10-10 04:12:51

## 1. Executive Summary & Space Reclamation

- **Total Scanned Project Files:** 7,665 files (6.36 GB)
- **Files to KEEP:** 6,304 files (2.14 GB)
- **Files Proposed for QUARANTINE:** 1,361 files (4.22 GB)
- **Net Disk Space to be Freed:** **4.22 GB**

## 2. Category Summary & Actions

| Category | Action | File Count | Total Size | Description / Risk |
|---|---|---|---|---|
| **OLD_BACKUP_SNAPSHOTS** | `QUARANTINE` | 1,160 | 3.31 GB | Quarantine into C:\\LionReel_quarantine |
| **SCRATCH_TEMPORARY_FILES** | `QUARANTINE` | 156 | 919.31 MB | Quarantine into C:\\LionReel_quarantine |
| **TEMP_ARTIFACT_CLUTTER** | `QUARANTINE` | 11 | 9.08 MB | Quarantine into C:\\LionReel_quarantine |
| **OLD_WORK_INTERMEDIATES** | `QUARANTINE` | 3 | 4.52 MB | Quarantine into C:\\LionReel_quarantine |
| **BUILD_CACHE_CLUTTER** | `QUARANTINE` | 27 | 1.24 MB | Quarantine into C:\\LionReel_quarantine |
| **OLD_PIPELINE_VERSION** | `QUARANTINE` | 4 | 193.62 KB | Quarantine into C:\\LionReel_quarantine |
| **ACTIVE_CACHE_POOL** | `KEEP` | 29 | 699.47 MB | Preserved strictly untouched |
| **VIRTUAL_ENV** | `KEEP` | 5,084 | 465.90 MB | Preserved strictly untouched |
| **UNKNOWN** | `KEEP` | 148 | 448.99 MB | Preserved strictly untouched |
| **FINISHED_OUTPUTS** | `KEEP` | 98 | 414.57 MB | Preserved strictly untouched |
| **PROJECT_GIT** | `KEEP` | 378 | 91.06 MB | Preserved strictly untouched |
| **AUDIT_REPORTS** | `KEEP` | 312 | 42.07 MB | Preserved strictly untouched |
| **RUNTIME_DATA_CONFIG** | `KEEP` | 13 | 23.64 MB | Preserved strictly untouched |
| **CORE_BACKEND** | `KEEP` | 158 | 7.09 MB | Preserved strictly untouched |
| **PROJECT_DOCS** | `KEEP` | 57 | 719.94 KB | Preserved strictly untouched |
| **UI_LIVE** | `KEEP` | 6 | 655.23 KB | Preserved strictly untouched |
| **TEST_AND_SCRIPTS** | `KEEP` | 21 | 175.03 KB | Preserved strictly untouched |

---

## 3. Strict Rules Enforcement

1. **UI Freeze**: All 6 files in `gui/` (`index.html`, `style.css`, `app.js`, `lion_logo.png`, `lion_logo.svg`, `clipforge_logo.svg`) match `ui_freeze_manifest.json` and are marked `KEEP`.
2. **Core Pipeline**: `lion_automate_v97.py`, `web_server.py`, `edl_manager.py`, `auto_reframe.py`, `qa_check.py`, `pet_detector.py`, `clip_ledger.py`, `source_utils.py` are strictly marked `KEEP`.
3. **Runtime Data & Config**: `config/*.json`, `data/clip_ledger.db`, `credits_registry.csv`, `models/`, `reference/` are strictly marked `KEEP`.
4. **Zero Unconfirmed Deletions**: All candidate files will be safely moved into `C:\LionReel_quarantine\20261010\` preserving relative paths. Permanent deletion will only occur if explicitly instructed with 'CONFIRM DELETE'.

## 4. Quarantined Candidates Breakdown (Sample of Top Items)

| Relative Path | Size | Category | Evidence |
|---|---|---|---|
| `__pycache__/auto_reframe.cpython-312.pyc` | 44.27 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/auto_reframe.cpython-314.pyc` | 44.85 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/clip_ledger.cpython-312.pyc` | 44.51 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/clip_ledger.cpython-314.pyc` | 49.17 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/edl_manager.cpython-312.pyc` | 33.53 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/edl_manager.cpython-314.pyc` | 21.15 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/harvest_worker.cpython-312.pyc` | 17.87 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/harvest_worker.cpython-314.pyc` | 20.28 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/lion_automate.cpython-312.pyc` | 171.34 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/lion_automate.cpython-314.pyc` | 192.62 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/lion_automate_v96.cpython-312.pyc` | 55.42 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/lion_automate_v97.cpython-312.pyc` | 140.90 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/lion_automate_v97.cpython-314.pyc` | 104.51 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/metadata_generator.cpython-312.pyc` | 20.75 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/pet_detector.cpython-312.pyc` | 9.16 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/qa_check.cpython-312.pyc` | 39.32 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/source_utils.cpython-312.pyc` | 7.69 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/source_utils.cpython-314.pyc` | 8.43 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/stage_state_machine.cpython-312.pyc` | 16.51 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/stage_timer.cpython-312.pyc` | 6.96 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/watermark_detector.cpython-312.pyc` | 13.52 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/web_server.cpython-312.pyc` | 106.86 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `__pycache__/web_server.cpython-314.pyc` | 104.33 KB | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `node_modules/@playwright/test/LICENSE` | 0 B | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `node_modules/playwright-core/LICENSE` | 0 B | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `node_modules/playwright/LICENSE` | 0 B | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `test-results/.last-run.json` | 45 B | BUILD_CACHE_CLUTTER | Compiled bytecode cache and transient test result clutter |
| `LionReel_backup_before_stage_order/.devcontainer/devcontainer.json` | 403 B | OLD_BACKUP_SNAPSHOTS | Redundant historical pre-recovery snapshot folders already archived in C:\LionReel_backups |
| `LionReel_backup_before_stage_order/LionReel_Antigravity_Master_Prompt_V2.md` | 16.64 KB | OLD_BACKUP_SNAPSHOTS | Redundant historical pre-recovery snapshot folders already archived in C:\LionReel_backups |
| `LionReel_backup_before_stage_order/LionReel_Studio_Project_Proposal.pdf` | 300.99 KB | OLD_BACKUP_SNAPSHOTS | Redundant historical pre-recovery snapshot folders already archived in C:\LionReel_backups |
| `LionReel_backup_before_stage_order/LionReel_backup_before_stage_order/.devcontainer/devcontainer.json` | 403 B | OLD_BACKUP_SNAPSHOTS | Redundant historical pre-recovery snapshot folders already archived in C:\LionReel_backups |
| `LionReel_backup_before_stage_order/LionReel_backup_before_stage_order/LionReel_Antigravity_Master_Prompt_V2.md` | 16.64 KB | OLD_BACKUP_SNAPSHOTS | Redundant historical pre-recovery snapshot folders already archived in C:\LionReel_backups |
| `LionReel_backup_before_stage_order/LionReel_backup_before_stage_order/LionReel_Studio_Project_Proposal.pdf` | 300.99 KB | OLD_BACKUP_SNAPSHOTS | Redundant historical pre-recovery snapshot folders already archived in C:\LionReel_backups |
| `LionReel_backup_before_stage_order/LionReel_backup_before_stage_order/analysis/ANALYSIS_REPORT.md` | 25.11 KB | OLD_BACKUP_SNAPSHOTS | Redundant historical pre-recovery snapshot folders already archived in C:\LionReel_backups |
| `LionReel_backup_before_stage_order/LionReel_backup_before_stage_order/analysis/change1/dark_1440.png` | 216.63 KB | OLD_BACKUP_SNAPSHOTS | Redundant historical pre-recovery snapshot folders already archived in C:\LionReel_backups |
| `LionReel_backup_before_stage_order/LionReel_backup_before_stage_order/analysis/change1/dark_390.png` | 131.75 KB | OLD_BACKUP_SNAPSHOTS | Redundant historical pre-recovery snapshot folders already archived in C:\LionReel_backups |
| `LionReel_backup_before_stage_order/LionReel_backup_before_stage_order/analysis/change1/docked_mid_scroll.png` | 198.83 KB | OLD_BACKUP_SNAPSHOTS | Redundant historical pre-recovery snapshot folders already archived in C:\LionReel_backups |
| `LionReel_backup_before_stage_order/LionReel_backup_before_stage_order/analysis/change1/end_of_page_natural.png` | 167.53 KB | OLD_BACKUP_SNAPSHOTS | Redundant historical pre-recovery snapshot folders already archived in C:\LionReel_backups |
| `LionReel_backup_before_stage_order/LionReel_backup_before_stage_order/analysis/change1/entrance_0ms.png` | 35.52 KB | OLD_BACKUP_SNAPSHOTS | Redundant historical pre-recovery snapshot folders already archived in C:\LionReel_backups |
| `LionReel_backup_before_stage_order/LionReel_backup_before_stage_order/analysis/change1/entrance_150ms.png` | 35.98 KB | OLD_BACKUP_SNAPSHOTS | Redundant historical pre-recovery snapshot folders already archived in C:\LionReel_backups |
| ... and 1321 additional files | ... | ... | Full list in `cleanup_plan.csv` |
