# Clean-up plan

Built on 2026-11-05 from a read-only scan. Every group below is recoverable: the full backup is at `D:\LionReel_backup_20261105`, and items also go to the Recycle Bin or stay in git history.

**Planned: 1106 items, 22.63 GB to the Recycle Bin, plus 5 paths (5.2 MB) removed with git.**

## To the Recycle Bin

| Group | Items | Size | Why it is safe | How to get it back |
|---|---|---|---|---|
| `temp_work_folders` | 1054 | 22.14 GB | Work files of finished or failed jobs. Rendered clips of Waiting or Interrupted jobs are skipped by the scanner. Masters and reports live in `output/` and `finished/`, which are not touched | Recycle Bin, or the D: backup |
| `rejected_unreferenced_cache` | 20 | 503.8 MB | Cached downloads whose video id is not in the ledger at all (checked by id, not by the scanner alone) | Recycle Bin, or the D: backup |
| `empty_folders` | 23 | 0.0 KB | Empty | Recreated when needed |
| `python_cache` | 1 | 700.6 KB | Rebuilt by Python | Rebuilt automatically |
| `project_leftovers` | 8 | 1.4 MB | See the list below | Google Drive Trash for 30 days, or the D: backup |

## Project leftovers

| Path | Size | Why |
|---|---|---|
| `web_server.py.bak` | 132.1 KB | Old copy of web_server.py, not tracked, git history holds every version |
| `credits_registry.csv.bak` | 4.0 KB | Old copy, not imported or read by any code |
| `test_mf.mp4` | 269.8 KB | Test render left in the project root |
| `raw_c0.wav` | 937.6 KB | Audio stem left by a debug run |
| `test_scale.png` | 8.6 KB | Debug image |
| `gui_run.log` | 0.1 KB | Old log, 64 bytes |
| `untruncated_prompt.txt` | 10.9 KB | Saved prompt text, no code reads it |
| `import_timing_gdrive.txt` | 34.9 KB | Old timing dump, no code reads it |

## Removed with git (recoverable from any earlier commit)

| Path | Size | Why |
|---|---|---|
| `LionReel_backup_before_ui_polish` | 1.7 MB | Old backup folder, tracked in git |
| `LionReel_backup_before_stage_order` | 3.4 MB | Old backup folder, tracked in git |
| `lion_automate.py` | 155.4 KB | Old V94 engine. Nothing imports it. Only a fallback name in web_server.py that is removed with it |
| `rerender_job_6b8cce5c.py` | 10.4 KB | One-off script for one job. No references found |
| `run_real_3min_job.py` | 5.4 KB | One-off script. No references found |

## Kept on purpose

| Item | Why |
|---|---|
| `cache_eQsvgKdAl4s.mp4` (45.1 MB) | The scanner called it unreferenced, but video id is in the ledger |
| `cache_nzUdF0qtNOg.mp4` (38.0 MB) | The scanner called it unreferenced, but video id is in the ledger |
| `cache_zCBhhLo6lIM.mp4` (89.7 MB) | The scanner called it unreferenced, but video id is in the ledger |
| `C:\LionReel\backups` (2.0 GB) | Holds older ledger snapshots. Your call, not a safe group |
| `analysis/`, `ui_audit/`, `data/backups` | Earlier evidence and history |
| `.venv` | The dashboard launcher uses it |
| Everything on the protected list | Finished videos and their reports, ledger, verified bank, config, analytics, `output/` |
