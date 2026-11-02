# LionReel Studio — Final Cleanup Execution Plan

**Method**: Windows Recycle Bin (C:\) & Google Drive Trash (G:\) via Shell32 `SHFileOperationW` (`FOF_ALLOWUNDO`). Zero permanent deletes.

## Candidate Groups Summary

| Group ID | Candidate Category | File Count | Total Size | Confirmation Checkbox |
|---|---|---|---|---|
| `intermediate_renders` | Intermediate Renders | 2 | 770 B | [x] Approved |
| `old_ui_backups` | Old Ui Backups | 2 | 618.8 KB | [x] Approved |
| `python_cache` | Python Cache | 17 | 694.5 KB | [x] Approved |
| `scratch_temp_files` | Scratch Temp Files | 37 | 3.06 MB | [x] Approved |
| **TOTAL** | **All Candidate Groups** | **58** | **4.35 MB** | **[x] Confirmed** |

## Sample Removal Paths

- `[scratch_temp_files]` `scratch_prompt.txt` (965 B)
- `[scratch_temp_files]` `scratch_last_prompt.txt` (4.1 KB)
- `[scratch_temp_files]` `scratch_full_last.txt` (4.1 KB)
- `[scratch_temp_files]` `scratch_sharpness.py` (1.5 KB)
- `[scratch_temp_files]` `scratch_ledger.py` (258 B)
- `[scratch_temp_files]` `scratch_check_sources.py` (1.3 KB)
- `[scratch_temp_files]` `scratch_check_sharpness_fast.py` (1.6 KB)
- `[scratch_temp_files]` `scratch_check_lap.py` (477 B)
- `[scratch_temp_files]` `scratch_test_zcb.py` (983 B)
- `[scratch_temp_files]` `scratch_scan_raw.py` (1.2 KB)
- `[scratch_temp_files]` `scratch_unsharp.py` (886 B)
- `[scratch_temp_files]` `scratch_clean_reservations.py` (466 B)
- `[scratch_temp_files]` `scratch_ozazz_f100.jpg` (209.0 KB)
- `[scratch_temp_files]` `scratch_ozazz_banner.jpg` (42.1 KB)
- `[scratch_temp_files]` `scratch_ozazz_bot.jpg` (32.2 KB)
- `[scratch_temp_files]` `scratch_825za_bot.jpg` (55.7 KB)
- `[scratch_temp_files]` `scratch_825za_top.jpg` (22.6 KB)
- `[scratch_temp_files]` `scratch_oz_top.jpg` (71.3 KB)
- `[scratch_temp_files]` `scratch_cache_KWA1jfqvZmg.jpg` (281.3 KB)
- `[scratch_temp_files]` `scratch_cache_cMlweIcxyZQ.jpg` (99.2 KB)
- `[scratch_temp_files]` `scratch_cache_Rr9701_s-Qs.jpg` (161.2 KB)
- `[scratch_temp_files]` `scratch_htlvw.jpg` (293.4 KB)
- `[scratch_temp_files]` `scratch_inspect_audio.py` (906 B)
- `[scratch_temp_files]` `scratch_analyze_source.py` (1.3 KB)
- `[scratch_temp_files]` `scratch_measure_rms.py` (1.3 KB)
- ... and 33 more items detailed in `cleanup_plan.csv`.
