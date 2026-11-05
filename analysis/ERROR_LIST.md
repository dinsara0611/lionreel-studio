# Error list

Baseline taken on 2026-11-05 from commit `dec1b1d`, the code as it stood before any behaviour fix.
Status of each row is in `MASTER_REPORT.md`.

## Baseline results

| Check | Result |
|---|---|
| pytest, file by file, in sandbox | 229 passed, 66 failed, `test_waiting_state.py` hung until killed at 300 s |
| ruff, all rules | 2,472 findings (834 auto-fixable). 7 are real defects, listed below |
| Type check | Not configured in this project |
| ESLint | Not configured: no `package.json` |
| pip-audit on `requirements.txt` | Pillow 11.3.0 has 6 listed CVEs, fixed in 13.0.0 |
| `git fsck` | 3 missing blobs, restored from identical working files |
| UI audit (70 page states) | 0 overflow, 0 horizontal scroll, 2,124 text under 13 px, 622 targets under 44 px, 36 contrast failures, 12 unlabelled, 500 on every load |

The earlier `analysis/MASTER_REPORT.md` said "100% PASS". It cited `stuck_job_watchdog.py`, `source_discovery.py` and `watermark_filter.py`, none of which exist or ever existed in git history. Its claims are not used as evidence here.

## Errors

Severity: S1 wrong or unsafe result, S2 feature broken, S3 quality or debt.

| ID | Area | Symptom | File | Line | Sev |
|---|---|---|---|---|---|
| E01 | backend | Harvest did not check licences. Plain text search, every clip stamped "CC-BY 4.0" | `harvest_worker.py` | 669, 788 | S1 |
| E02 | backend | Creator never saved. Ledger holds placeholders such as `CC-BY Creator` | `harvest_worker.py` | 479, 790 | S1 |
| E03 | backend | Unknown licence text normalised to CC BY 4.0. CC BY-SA unreachable | `source_utils.py` | 186-199 | S1 |
| E04 | backend | Reports invented "CC Creator" and "Creative Commons (CC-BY 4.0)" | `lion_automate_v97.py`, `report_generator.py` | 2519, 4666, 660 | S1 |
| E05 | backend | No ffprobe reachable by the engine. QA fell back to OpenCV, source of the "29/1" fps value | `qa_check.py` | 99-133 | S1 |
| E06 | backend | Missing QA report defaulted to PASSED, score 96.0 invented | `web_server.py` | 2095-2141 | S1 |
| E07 | backend | Crash in the defect gate returned passed=True | `qa_check.py` | 157 | S1 |
| E08 | backend | Two verdicts: `qa_check` said PASSED/REJECTED, report said four states | `qa_check.py`, `report_generator.py` | 1544, 261 | S1 |
| E09 | backend | Gate 1 did not check fps, profile, pix_fmt, colour tags, even size, AAC | `qa_check.py` | 1405 | S1 |
| E10 | backend | Clip count never compared with config. Duration passed when no target stored | `qa_check.py` | 1417 | S1 |
| E11 | backend | Sharpness checked by median of the master, not on every clip | `qa_check.py` | 724 | S1 |
| E12 | backend | Loudness used `loudnorm` with a fixed 40 s limit: final file differed (report -14.20, measured -13.8), long files fell to -99 | `qa_check.py` | 196 | S1 |
| E13 | backend | "New footage 100%" printed when freshness unknown | `qa_check.py`, `lion_automate_v97.py` | 1636, 4580 | S1 |
| E14 | backend | Stage evidence hardcoded "passed 10/10 automated QA gates" | `lion_automate_v97.py` | 4560 | S1 |
| E15 | backend | Reuse OFF still fell back to LRU reuse, and checked only the last 5 videos | `clip_ledger.py` | 1262 | S1 |
| E16 | backend | Teaser forced `allow_reuse=True` regardless of the user's choice | `lion_automate_v97.py` | 4940 | S1 |
| E17 | backend | Short accepted any ratio, no target length input, teaser had no clip count | `job_options.py` | 174, 245, 288 | S1 |
| E18 | backend | Counts disagreed on one ledger: 29, 11, 18, 49 and 4 | `clip_ledger.py`, `web_server.py` | 787, 872, 957, 1315 | S1 |
| E19 | backend | 32 of 33 engine subprocess calls had no timeout, harvest 2 of 2 | `lion_automate_v97.py`, `harvest_worker.py` | many | S1 |
| E20 | backend | `shutil` shadowed by a local import: clip checkpoints silently never saved, later uses can crash | `lion_automate_v97.py` | 3973 | S1 |
| E21 | backend | Reservation slept inside the write transaction, blocking the harvester during the wait for clips | `clip_ledger.py` | 1267 | S1 |
| E22 | backend | Harvest capped at 2 downloads, no time budget, downloaded before checking length or size | `harvest_worker.py` | 573 | S2 |
| E23 | backend | Long files not constant frame rate: 5,398 frames, 29.993 average after stream-copy concat | `lion_automate_v97.py` | 4222 | S1 |
| E24 | backend | `json` undefined in colour preset path, `math` undefined in feedback score | `auto_reframe.py`, `feedback_manager.py` | 1228, 246 | S2 |
| E25 | backend | Old sharpness floor 15.0 left in SQL counts and selection | `clip_ledger.py`, `fulfillment_planner.py` | 806, 530 | S2 |
| E26 | backend | Clean up preview and execute crashed: wrong keyword argument | `web_server.py` | 1928, 2711, 2732 | S2 |
| E27 | backend | 17 test files targeted port 8000 and 23 reached the production ledger | `tests/` | many | S1 |
| E28 | backend | Hardcoded `C:\LionReel` in 14 modules, no way to isolate a run | various | many | S2 |
| E29 | ui | Text under 13 px: 2,124 instances | `gui/style.css`, `gui/index.html`, `gui/app.js` | token `--text-xs` | S3 |
| E30 | ui | Targets under 44 px: 622 instances | `gui/style.css` | - | S3 |
| E31 | ui | Contrast failures: 36 | `gui/style.css`, `gui/index.html` | 5439, 2176 | S2 |
| E32 | ui | `--accent-hover` referred to itself, so hover styles using it were invalid | `gui/style.css` | 108, 194 | S2 |
| E33 | ui | Glass (18 `backdrop-filter`), 21 gradients, glow shadows, text shadows | `gui/style.css` | many | S3 |
| E34 | ui | Button without an accessible name | `gui/index.html` | 332 | S3 |
| E35 | ui | Two "New compilation" buttons on Export | `gui/index.html`, `gui/app.js` | - | S2 |
| E36 | ui | Export contract tests fail: publish zone, tab role | `gui/index.html` | 2193 | S2 |
| E37 | tests | Stale tests: expect media files or removed behaviour, about 30 of the 66 failures | `tests/` | - | S3 |
| E38 | config | Pillow 11.3.0 advisories | `requirements.txt` | - | S3 |
| E39 | legal | 13 of 15 bank sources show no Creative Commons licence on YouTube. They supplied 77 of 86 traced windows in finished videos | ledger | - | S1 |

Items from the brief are tracked in `MASTER_REPORT.md` with their status.
