# LionReel project rules

## Never touch

- Finished production videos and their report, mapping, credits and QA files
- `C:\LionReel\data\clip_ledger.db`: work on a copy
- Verified bank clips and source, licence and creator data
- The user's config files (`config.json`, `config/`), channel analytics
- `output/` in this folder

Before deleting or rewriting anything, look at it first, and keep a way back.

## Tests

- One command: `powershell -File scripts/run_all_tests.ps1`
- Tests and sandbox runs use `C:\LionReel_sandbox` and port 8100. Port 8000 is the live dashboard.
- All local paths go through `lion_paths.py`. Never hardcode `C:\LionReel`.
- `git add` named paths only: `output/` is tracked.

## Truth rules

- **One count function.** Every ledger number comes from `ClipLedger.get_ledger_counts`. No private SQL counts for the planner, UI, report or Export.
- **One verdict function.** `verdict.calculate_unified_verdict`: PASSED, PASSED WITH WARNINGS, FAILED, NOT RUN. The card shows the stored verdict word for word.
- **No fake pass.** A gate that crashes, is skipped or leaves no result is NOT RUN, and a job with a NOT RUN gate cannot be PASSED. Never default a missing result to a pass.
- **No invented numbers.** Every number in the UI and reports comes from stored files. A missing value says "not measured".
- **No invented attribution.** Licence and creator come from the platform (`source_licenses.py`) or say "not recorded".
- **Proof.** Never claim a fix without a test, a command output, an ffprobe result or a screenshot. If it cannot be proven, say "not proven". Earlier reports in `analysis/` contain false claims: check before relying on them.

## Standards

- Blocking subprocess calls go through `timed_subprocess`.
- Legal sources only: harvest takes a video only if its page shows a Creative Commons licence.
- Sharpness floor is 150 on the canonical scale (`canonical_window.measure_canonical_sharpness`) at every gate.
- Output: exactly 30 fps constant, bt709, H.264 High yuv420p, AAC 192 kbps, -14 LUFS +/- 0.5, true peak at or below -1.0 dBTP, length within +/- 1 s.
- UI: plain HTML, CSS and vanilla JS, tokens in `gui/style.css`, no new libraries, 13 px minimum text, sentence case, no glow, glass or gradient fills. The root font size is 15 px, so 13 px is 0.875rem.
- UI audits must switch theme with `applyTheme()`.
