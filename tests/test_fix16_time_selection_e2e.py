"""
test_fix16_time_selection_e2e.py
================================
Validates:
1. Preflight endpoint respects explicit clips count (e.g. clips=8 returns is_ready=True when pool has 8 verified clips).
2. Setting output time / duration (e.g. 1.0 min = 8 clips) allows instant generation without looping or shortfall errors.
3. When shortfall occurs (e.g. 100 clips), clicking "Set clips to what the pool can supply (8)" updates TARGET_CLIPS, UI sliders/labels, and launches the pipeline without re-triggering the preflight modal.
"""

import os
import sys
import unittest
import urllib.request
import json
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger

class TestFix16TimeSelectionE2E(unittest.TestCase):

    def test_api_preflight_respects_explicit_clips(self):
        """Preflight API must honor explicit clips parameter and return is_ready=True when target <= capacity."""
        url = "http://127.0.0.1:8000/api/preflight?animal=cat&type=long&clips=8"
        req = urllib.request.urlopen(url)
        data = json.loads(req.read().decode("utf-8"))

        self.assertEqual(data.get("needed_clips"), 8)
        self.assertEqual(data.get("capacity"), 8)
        self.assertTrue(data.get("is_ready"))
        self.assertTrue(data.get("can_supply_target"))
        self.assertEqual(data.get("warning"), "")
        self.assertEqual(data.get("status"), "ready")

    def test_api_preflight_shortfall_shows_accurate_capacity(self):
        """When 100 clips requested, preflight accurately reports 8 clips capacity from 4 sources."""
        url = "http://127.0.0.1:8000/api/preflight?animal=cat&type=long&clips=100"
        req = urllib.request.urlopen(url)
        data = json.loads(req.read().decode("utf-8"))

        self.assertEqual(data.get("needed_clips"), 100)
        self.assertEqual(data.get("capacity"), 8)
        self.assertFalse(data.get("is_ready"))
        self.assertEqual(data.get("min_sources_needed"), 34)
        self.assertIn("This pool can supply at most 8 clips. 100 clips need at least 34 sources.", data.get("warning"))

    def test_playwright_set_clips_button_starts_pipeline(self):
        """In browser, clicking 'Set clips to what the pool can supply (8)' sets TARGET_CLIPS and navigates to render stage."""
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto("http://127.0.0.1:8000/", wait_until="domcontentloaded")
            page.wait_for_timeout(1000)

            # Trigger preflight modal with 100 clips shortfall
            page.evaluate("""() => {
                const ls = document.getElementById('app-loading-screen');
                if (ls) ls.style.display = 'none';
                state.config.TARGET_CLIPS = 100;
                startRenderPipeline(false);
            }""")

            page.wait_for_timeout(600)
            modal = page.locator("#modal-preflight")
            self.assertTrue(modal.is_visible(), "Preflight modal should be visible")

            btn_set_k = page.locator("#btn-preflight-set-k")
            self.assertTrue(btn_set_k.is_visible(), "Set clips button should be visible")
            btn_text = btn_set_k.inner_text()
            self.assertIn("Set clips to what the pool can supply (8)", btn_text)

            # Click Set clips to what the pool can supply (8)
            btn_set_k.click()
            page.wait_for_timeout(800)

            # Verify modal closed and target clips updated to 8
            self.assertFalse(modal.is_visible(), "Modal must close immediately after clicking Set clips")
            target_clips = page.evaluate("() => state.config.TARGET_CLIPS")
            self.assertEqual(target_clips, 8, "TARGET_CLIPS should be set to 8")

            # Verify pipeline moved into starting/running or navigated to step 4
            is_active = page.evaluate("() => state.isStarting || state.isRunning || state.currentStep === 4")
            self.assertTrue(is_active, "Pipeline should be starting or on step 4")

            # Clean up: stop the running test job if started
            page.evaluate("() => { if (window.stopRenderPipeline) window.stopRenderPipeline(); }")
            browser.close()

if __name__ == "__main__":
    unittest.main()
