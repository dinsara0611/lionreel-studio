# LionReel Studio

Local app that turns licensed animal footage into Shorts and long videos, with QA gates and production reports.

## Run the app

Double-click `run_dashboard.bat`, then open http://localhost:8000.

## Where things are

- Code: this folder.
- Runtime storage: `C:\LionReel` (ledger, source cache, job work folders, models, Python venv).
- Finished videos: `finished/` and `output/<job>/`.

See `analysis/PROJECT_MAP.md` for modules, data flow and the files stored per job.

## Run all tests

```powershell
powershell -File scripts/run_all_tests.ps1
```

This copies the code to `C:\LionReel_sandbox` and runs pytest there, including the Playwright UI tests in the installed Chrome. Tests refuse to run from this folder or against `C:\LionReel`, and they use port 8100. Port 8000 is the live app.

To run each test file in its own process with a time limit:

```powershell
powershell -File scripts/run_all_tests.ps1 --collect-only -q
cd C:\LionReel_sandbox\proj
C:\LionReel_sandbox\venv\Scripts\python.exe scripts\run_suite.py --limit 300 --out suite.json
```

Set `LIONREEL_ROOT`, `LIONREEL_DATA_DIR` and `LIONREEL_CACHE_DIR` to the sandbox first.

## Useful tools

| Command | Purpose |
|---|---|
| `python scripts/ui_audit.py --base <url> --out <folder>` | Measures every page in both themes at 1920, 1440, 1280, 768 and 390 px |
| `python scripts/audit_source_licenses.py` | Asks the platform what licence and creator each bank source shows. Reads the ledger, never writes it |

`ffprobe.exe` must be in `C:\LionReel\tools`, or QA gates that need it report NOT RUN.
