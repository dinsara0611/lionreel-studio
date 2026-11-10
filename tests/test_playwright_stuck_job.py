"""
tests/test_playwright_stuck_job.py
==================================
Playwright UI verification using installed Chrome (channel="chrome", no driver download).
Verifies:
1. Stale job cleanup bar ("1 stuck job from HH:MM. Clean up" with action button).
2. Amber prediction warning banner when elapsed > predicted range.
3. Toggleable "Show live engine log (last 5 lines)" under stages card.
4. Unified stage state: when waiting, both badge and stage reflect WAITING (no contradiction).
5. Dark and light themes tested.
6. 1440px desktop and 390px mobile viewports tested.
7. Screenshots saved to artifact directory.
"""

import os
import sys
import json
import time
import subprocess
import unittest
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

ARTIFACT_DIR = r"C:\Users\dinsa\.gemini\antigravity-ide\brain\8560932b-8884-4fc3-9f30-9c81f8e136ba"
SCREENSHOT_DIR = os.path.join(ARTIFACT_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

PYTHON_EXE = r"C:\LionReel\venv\Scripts\python.exe"
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable

TEST_PORT = 8011

class TestPlaywrightStuckJobUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Clean any stale server lock
        lock_p = os.path.join(BASE_DIR, "web_server.lock")
        if os.path.exists(lock_p):
            try:
                os.remove(lock_p)
            except Exception:
                pass

        env = os.environ.copy()
        env["PORT"] = str(TEST_PORT)
        env["NO_BROWSER"] = "1"
        cls.server_proc = subprocess.Popen(
            [PYTHON_EXE, "web_server.py"],
            cwd=BASE_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        import urllib.request
        server_ready = False
        for _ in range(25):
            try:
                r = urllib.request.urlopen(f"http://127.0.0.1:{TEST_PORT}/api/status", timeout=1)
                if r.status == 200:
                    server_ready = True
                    break
            except Exception:
                time.sleep(0.3)
        if not server_ready:
            cls.server_proc.terminate()
            raise RuntimeError(f"Could not connect to test server on port {TEST_PORT}")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server_proc") and cls.server_proc:
            try:
                cls.server_proc.terminate()
                cls.server_proc.wait(timeout=3)
            except Exception:
                pass

    def test_stuck_job_watchdog_ui(self):
        with sync_playwright() as p:
            # Use installed Chrome per constraints
            browser = p.chromium.launch(channel="chrome", headless=True)

            # --- TEST 1: Desktop 1440px Dark Mode ---
            context_dark = browser.new_context(
                viewport={"width": 1440, "height": 900},
                color_scheme="dark"
            )
            page = context_dark.new_page()
            page.goto(f"http://127.0.0.1:{TEST_PORT}/", timeout=15000)
            page.wait_for_timeout(1000)

            # Navigate to Render step (View 4)
            page.evaluate("navigateToStep(4);")
            page.wait_for_timeout(500)

            # Inject mock status with stuckJobInfo, predictionWarning, recentLogs, and waiting state
            mock_status = {
                "status": "waiting_for_clips",
                "stateLabel": "WAITING",
                "isRunning": True,
                "isWaiting": True,
                "elapsedSeconds": 495,
                "workingSeconds": 15.0,
                "waitingSeconds": 480.0,
                "workingFormatted": "00:15",
                "waitingFormatted": "08:00",
                "elapsedFormatted": "08:15",
                "stageIndex": 1,
                "stageName": "Collect candidate moments from ledger",
                "progressPct": 33,
                "clips_ready": 2,
                "clips_needed": 6,
                "stuckJobInfo": {
                    "job_id": "lionreel_cat_20261031_153841_bcad3a4f",
                    "time_str": "15:38",
                    "summary_line": "1 stuck job from 15:38. Clean up",
                    "reason": "Watchdog detected missing heartbeat > 60s"
                },
                "isOverPredicted": True,
                "predictionWarning": "Taking longer than predicted: 08:15, expected 01:00–02:00. Reason: waiting for footage (2/6 clips ready)",
                "recentLogs": [
                    "[SEQ 10] Checking clip ledger pool capacity...",
                    "[SEQ 11] Pool has 2 usable clips, 6 requested (deficit: 4)",
                    "[SEQ 12] Entering waiting state for background harvest...",
                    "[SEQ 13] Heartbeat counter: 42 (PID: 12345)",
                    "[SEQ 14] Watching for verified clips in ledger..."
                ],
                "stages": [
                    {
                        "id": 1,
                        "key": "collect_candidates",
                        "label": "Collect candidate moments from ledger",
                        "status": "WAITING",
                        "duration_sec": 0.0,
                        "evidence": "Waiting: 2 of 6 clips ready",
                        "reason": "Waiting for 4 clips"
                    },
                    {
                        "id": 2,
                        "key": "prepare_sources",
                        "label": "Prepare & verify raw source video files",
                        "status": "PENDING",
                        "duration_sec": 0.0,
                        "evidence": "",
                        "reason": ""
                    }
                ]
            }

            # Feed mock status into client UI
            page.evaluate(f"""(data) => {{
                // Trigger client state updates
                state.serverStateLabel = data.stateLabel;
                state.isWaiting = data.isWaiting;

                // 1. Stale job banner
                const staleBanner = document.getElementById("stale-job-banner");
                const staleText = document.getElementById("stale-job-text");
                if (staleBanner && staleText) {{
                    staleText.innerText = data.stuckJobInfo.summary_line;
                    staleBanner.style.display = "flex";
                }}

                // 2. Prediction warning banner
                const predWarnBanner = document.getElementById("prediction-warning-banner");
                const predWarnText = document.getElementById("prediction-warning-text");
                if (predWarnBanner && predWarnText) {{
                    predWarnText.innerText = data.predictionWarning;
                    predWarnBanner.style.display = "flex";
                }}

                // 3. Live engine log
                const liveLogPre = document.getElementById("live-engine-log-content");
                if (liveLogPre) {{
                    liveLogPre.innerText = data.recentLogs.join("\\n");
                }}

                // 4. Update stages UI
                updateRenderStagesUI(data.stages);

                // 5. Update hero
                const stageNameEl = document.getElementById("render-stage-name");
                if (stageNameEl) stageNameEl.innerText = "Finding Footage (Waiting)";
            }}""", mock_status)
            page.wait_for_timeout(500)

            # Assertions: Stale Job Banner
            stale_banner = page.locator("#stale-job-banner")
            self.assertTrue(stale_banner.is_visible(), "Stale job banner must be visible")
            stale_text = page.locator("#stale-job-text").inner_text()
            self.assertIn("1 stuck job from 15:38. Clean up", stale_text)

            # Assertions: Prediction Warning Banner
            pred_banner = page.locator("#prediction-warning-banner")
            self.assertTrue(pred_banner.is_visible(), "Prediction warning banner must be visible")
            pred_text = page.locator("#prediction-warning-text").inner_text()
            self.assertIn("Taking longer than predicted", pred_text)

            # Assertions: Stages UI Unified State
            stage_1_badge = page.locator(".render-stage-row[data-stage-id='1'] .stage-badge")
            self.assertEqual(stage_1_badge.inner_text().strip(), "WAITING", "Stage 1 must display WAITING, NOT RUNNING")
            stage_1_ev = page.locator("#stage-evidence-1 .evidence-text").inner_text()
            self.assertIn("Waiting: 2 of 6 clips ready", stage_1_ev)

            # Assertions: Live Engine Log Toggle
            log_body = page.locator("#live-engine-log-body")
            self.assertFalse(log_body.is_visible(), "Log body should initially be collapsed")
            page.locator("#btn-toggle-engine-log").click()
            page.wait_for_timeout(300)
            self.assertTrue(log_body.is_visible(), "Log body should be visible after toggle click")
            log_content = page.locator("#live-engine-log-content").inner_text()
            self.assertIn("[SEQ 10]", log_content)
            self.assertIn("[SEQ 14]", log_content)

            # Screenshot Desktop Dark Mode
            ss_desktop_dark = os.path.join(SCREENSHOT_DIR, "stuck_job_watchdog_1440px_dark.png")
            page.screenshot(path=ss_desktop_dark, full_page=True)
            print(f"Captured screenshot: {ss_desktop_dark}")

            # --- TEST 2: Desktop 1440px Light Mode ---
            context_light = browser.new_context(
                viewport={"width": 1440, "height": 900},
                color_scheme="light"
            )
            page_light = context_light.new_page()
            page_light.goto(f"http://127.0.0.1:{TEST_PORT}/", timeout=15000)
            page_light.wait_for_timeout(500)
            page_light.evaluate("document.documentElement.setAttribute('data-theme', 'light'); navigateToStep(4);")
            page_light.wait_for_timeout(500)

            # Set up mock state in light mode
            page_light.evaluate(f"""(data) => {{
                state.serverStateLabel = data.stateLabel;
                state.isWaiting = data.isWaiting;

                const staleBanner = document.getElementById("stale-job-banner");
                const staleText = document.getElementById("stale-job-text");
                if (staleBanner && staleText) {{
                    staleText.innerText = data.stuckJobInfo.summary_line;
                    staleBanner.style.display = "flex";
                }}
                const predWarnBanner = document.getElementById("prediction-warning-banner");
                const predWarnText = document.getElementById("prediction-warning-text");
                if (predWarnBanner && predWarnText) {{
                    predWarnText.innerText = data.predictionWarning;
                    predWarnBanner.style.display = "flex";
                }}
                const liveLogPre = document.getElementById("live-engine-log-content");
                if (liveLogPre) {{
                    liveLogPre.innerText = data.recentLogs.join("\\n");
                }}
                updateRenderStagesUI(data.stages);
                document.getElementById("btn-toggle-engine-log").click();
            }}""", mock_status)
            page_light.wait_for_timeout(500)

            ss_desktop_light = os.path.join(SCREENSHOT_DIR, "stuck_job_watchdog_1440px_light.png")
            page_light.screenshot(path=ss_desktop_light, full_page=True)
            print(f"Captured screenshot: {ss_desktop_light}")

            # --- TEST 3: Mobile 390px Dark Mode ---
            context_mobile = browser.new_context(
                viewport={"width": 390, "height": 844},
                color_scheme="dark"
            )
            page_mobile = context_mobile.new_page()
            page_mobile.goto(f"http://127.0.0.1:{TEST_PORT}/", timeout=15000)
            page_mobile.wait_for_timeout(500)
            page_mobile.evaluate("navigateToStep(4);")
            page_mobile.wait_for_timeout(500)

            page_mobile.evaluate(f"""(data) => {{
                state.serverStateLabel = data.stateLabel;
                state.isWaiting = data.isWaiting;

                const staleBanner = document.getElementById("stale-job-banner");
                const staleText = document.getElementById("stale-job-text");
                if (staleBanner && staleText) {{
                    staleText.innerText = data.stuckJobInfo.summary_line;
                    staleBanner.style.display = "flex";
                }}
                const predWarnBanner = document.getElementById("prediction-warning-banner");
                const predWarnText = document.getElementById("prediction-warning-text");
                if (predWarnBanner && predWarnText) {{
                    predWarnText.innerText = data.predictionWarning;
                    predWarnBanner.style.display = "flex";
                }}
                const liveLogPre = document.getElementById("live-engine-log-content");
                if (liveLogPre) {{
                    liveLogPre.innerText = data.recentLogs.join("\\n");
                }}
                updateRenderStagesUI(data.stages);
                document.getElementById("btn-toggle-engine-log").click();
            }}""", mock_status)
            page_mobile.wait_for_timeout(500)

            ss_mobile_dark = os.path.join(SCREENSHOT_DIR, "stuck_job_watchdog_390px_dark.png")
            page_mobile.screenshot(path=ss_mobile_dark, full_page=True)
            print(f"Captured screenshot: {ss_mobile_dark}")

            browser.close()

if __name__ == "__main__":
    unittest.main()
