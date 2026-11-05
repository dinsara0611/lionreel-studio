# LionReel project map

Written during the full check on 2026-11-05, from the code on branch `full-check`.

## Where things live

| Location | Holds |
|---|---|
| `G:\My Drive\Cat make` | All code, `gui/`, `config/`, `tests/`, `scripts/`, `analysis/`, `output/` and `finished/` |
| `C:\LionReel` | Runtime storage only: `data/clip_ledger.db`, `cache/` (source videos), `work/` (job folders), `models/`, `venv/` (Python 3.12), `backups/` |
| `C:\LionReel_sandbox` | Test and proof runs. Own ledger copy, cache copy, tools. Created by the full check. Safe to delete |

`C:\LionReel` is not a code folder and is not a git repository. The brief calls the project `C:\LionReel`, but the code is in the Drive folder.

All local paths now come from `lion_paths.py`. Setting `LIONREEL_ROOT` moves every one of them.

## Entry points

| Entry | Purpose |
|---|---|
| `run_dashboard.bat` -> `web_server.py` | The app. HTTP server on port 8000, serves `gui/`, spawns the engine |
| `lion_automate_v97.py` | The engine. One process per job. `lion_automate.py` is the old V94 and nothing imports it |
| `harvest_worker.py` | Finds and verifies footage, foreground (`run_real_harvest_sync`) or background (`run_harvest_loop`) |
| `clip_bank_filler.py` | Background bank filler. Spawned by the server and engine |
| `qa_check.py` | QA gates. Run by the engine, can also be run alone on one file |

## Modules

| Module | Role |
|---|---|
| `web_server.py` (4,100 lines) | HTTP API, job start and stop, status, library, Export data, deliverables |
| `job_options.py` | Mode contract: validates the UI selection, writes `job_config.json`, builds engine CLI args |
| `lion_automate_v97.py` (5,100 lines) | Pipeline. `render_one_video` is about 2,700 lines and holds all 10 stages |
| `stage_state_machine.py` | Ordered stages, each proven by a file in `work/<job>/stages/` |
| `fulfillment_planner.py` | Picks windows for a job, or returns an honest shortage plan |
| `clip_ledger.py` | SQLite ledger. **`get_ledger_counts` is the one count function** |
| `canonical_window.py` | One window function and sharpness measure for Stage A, render and QA |
| `auto_reframe.py` | Smart crop, framing plan, ffmpeg segment render, post-crop gate |
| `pet_detector.py` | YOLOX cat and dog detection |
| `funny_event_detector.py` | Peak moment scoring |
| `overlay_text_detector.py`, `watermark_detector.py` | Burned-in text and corner logo gates |
| `verdict.py` | **The one verdict function** (added by this check) |
| `source_licenses.py` | What is really known about a source's licence and creator (added by this check) |
| `timed_subprocess.py` | `subprocess` with a timeout on every blocking call (added by this check) |
| `lion_paths.py` | Local paths and ffprobe discovery (added by this check) |
| `report_generator.py` | Report JSON, HTML, PDF, contact sheet |
| `metadata_generator.py` | Titles, descriptions, hashtags |
| `thumbnail_maker.py` | 1280x720 thumbnails, Long only |
| `deliverables_manager.py` | Packs the finished job files |
| `engine_lock.py`, `watchdog_service.py`, `stage_timeouts.py`, `keep_work.py` | One engine per job, heartbeat, stale job detection, kept clips |
| `stage_estimator.py`, `stage_timer.py` | Time prediction and measurement |
| `safe_cleanup.py` | Clean-up scan and execution |
| `edl_manager.py`, `feedback_manager.py`, `system_power.py`, `video_type_classifier.py` | Edit step, ratings, keep-awake, video type |

## Data flow

```
UI (gui/app.js)
  POST /api/start
    job_options.normalize_job_options      validates the selection, applies the mode contract
    job_options.load_or_verify_job_config  writes work/<job>/job_config.json once; a later mismatch is refused
    spawn lion_automate_v97.py --job-id ...
      CONFIG line in the log, read from job_config.json
      ledger.get_ledger_counts -> PREFLIGHT "Need N, have M usable"
      harvest if short (licence-checked)
      fulfillment_planner.plan_fulfillment
      stages 1-5  candidates, sources, probe, watermark, Stage A prediction
      stage 6     render each clip, post-crop gate, checkpoint to clips/
      stages 7-8  assembly order, captions
      stage 9     concat, CFR timestamps, audio master, qa_check.run_full_qa
                  verdict.calculate_unified_verdict -> qa_report.json
      stage 10    register in ledger, credits, metadata, report, copy to output/ and finished/
  GET /api/status polled by the Render screen (reads work/<job>/job_result.json, heartbeat.json)
  Export page reads the same stored files
```

## Stored files per job

In `C:\LionReel\work\<job>\`, then copied to `output\<job>\`:

| File | Content |
|---|---|
| `job_config.json` | The single stored contract: mode, ratio, size, target seconds, clip time, clip count, teaser, reuse, shorter |
| `job_result.json` | Status, stage, progress, error |
| `heartbeat.json` | Written every 5 s by the engine |
| `stages_state.json`, `stages/*.json` | Stage state and the proof file of each stage |
| `planner_decision.json` | Plan, shortage, freshness |
| `wait_checkpoint.json` | Resume state while waiting for clips |
| `clips/`, `clips_rendered.json` | Rendered clips kept for resume |
| `audio_mastering/` | Intermediate audio |
| `<job>.mp4` | The master |
| `qa_report.json`, `<job>_qa_report.json` | Gates, reasons, verdict |
| `mapping.json`, `<job>_mapping.json` | Clip to source map |
| `metadata.json`, `<job>_metadata.json/.txt` | Title, description, tags |
| `<job>_credits.json/.txt` | Attribution |
| `report.json/.html/.pdf` | Production report |
| `timings.json` | Measured stage times |
| `<job>_contact_sheet.png` | Contact sheet |

Both mode writes a second job folder, `<job>_teaser`, with its own files.

## Config files

| File | Used by |
|---|---|
| `config.json` (not in git) | UI settings. The user's file: never edited by this check |
| `config/benchmark.json` | QA thresholds |
| `config/blocked_sources.json` | Blocked sources |
| `config/color_presets.json` | Grading presets |
| `config/hashtag_bank.json`, `config/title_bank.json` | Metadata |
| `config/platform_limits.json` | Export fit rules |
| `config/safe_zones.json` | Caption safe zones |
| `config/video_types.json` | Video type definitions |
| `pytest.ini` | Test settings |
| `C:\LionReel\data\source_licenses.json` | Licence records, once `scripts/audit_source_licenses.py` is run |

## Tests

`powershell -File scripts/run_all_tests.ps1` syncs the code to the sandbox and runs pytest there.
`scripts/run_suite.py` runs each file in its own process with a time limit.
Tests refuse to start from the Drive folder or against production storage. Sandbox server port is 8100; port 8000 is the live dashboard.
