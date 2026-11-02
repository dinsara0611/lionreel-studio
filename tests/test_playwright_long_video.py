"""
tests/test_playwright_long_video.py
Playwright verification of Long Video (Compilation) UI behavior using installed Chrome (channel="chrome").
Verifies:
1. Dashboard loads with Long Video configuration defaults (100 clips, 12s, 16:9).
2. Preflight modal for Long Video suppresses "Set K clips" when capacity < 10 and displays "Landscape Sources:" instead of "Vertical Sources:".
3. "Start anyway (it will wait)" / "Proceed" is visible, accessible, and operational.
4. Harvest Bank Progress card (renderSelfHealingBanner) displays "Landscape 16:9:" (not "Vertical 9:16:") for 16:9 Long Videos.
5. Screenshots saved to brain artifacts directory.
"""

import os
import sys
import unittest
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"C:\Users\dinsa\.gemini\antigravity-ide\brain\d8fabd9c-0392-4de8-ac4f-0a350499ad2d"
SCREENSHOT_DIR = os.path.join(ARTIFACT_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

class TestPlaywrightLongVideo(unittest.TestCase):
    def test_long_video_ui_and_preflight(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900}
            )
            page = context.new_page()
            page.goto("http://127.0.0.1:8000", timeout=15000)
            page.wait_for_timeout(1000)

            # 1. Verify UI controls & state
            print("1. Checking default configuration in UI...")
            state_cfg = page.evaluate("() => state.config")
            print(f"State config: {state_cfg.get('VIDEO_TYPE')}, clips: {state_cfg.get('TARGET_CLIPS')}, aspect: {state_cfg.get('ASPECT_RATIO')}")
            self.assertEqual(state_cfg.get("VIDEO_TYPE"), "long")
            self.assertEqual(state_cfg.get("TARGET_CLIPS"), 100)
            self.assertEqual(state_cfg.get("ASPECT_RATIO"), "16:9")

            # 2. Test preflight modal behavior for Long Video with low bank capacity
            print("2. Testing Preflight Modal with Long Video (capacity=7 < 10)...")
            page.evaluate("""() => {
                showPreflightModal({
                    is_ready: false,
                    format: "long",
                    verified_windows: 7,
                    capacity: 7,
                    needed_clips: 100,
                    distinct_sources: 14,
                    landscape_sources: 11,
                    vertical_sources: 7,
                    min_sources_needed: 10,
                    estimated_harvest_time_sec: 4000,
                    warning: "This pool can supply at most 7 clips. 100 clips need at least 10 sources."
                }, () => { window.__proceed_called = true; }, () => {}, (k) => { window.__selected_k = k; });
            }""")
            page.wait_for_timeout(500)

            modal = page.locator("#modal-preflight")
            self.assertTrue(modal.is_visible())

            # Check that stat label is Landscape Sources for long video
            stat_vert_el = page.locator("#preflight-stat-vertical")
            stat_parent = stat_vert_el.locator("..")
            self.assertIn("Landscape Sources", stat_parent.inner_text())
            self.assertEqual(stat_vert_el.inner_text(), "11")

            # btn-preflight-set-k must be HIDDEN because capacity 7 < 10 for long video
            btn_set_k = page.locator("#btn-preflight-set-k")
            self.assertFalse(btn_set_k.is_visible())

            # btn-preflight-proceed must be VISIBLE
            btn_proceed = page.locator("#btn-preflight-proceed")
            self.assertTrue(btn_proceed.is_visible())

            # Take screenshot of the Long Video preflight modal
            screenshot_path = os.path.join(SCREENSHOT_DIR, "long_video_preflight_modal.png")
            page.screenshot(path=screenshot_path)
            print(f"Saved screenshot to: {screenshot_path}")

            # Click proceed button
            btn_proceed.click()
            page.wait_for_timeout(300)
            proceed_called = page.evaluate("() => window.__proceed_called")
            self.assertTrue(proceed_called)

            # 3. Test Harvest Bank Progress banner in Step 4 / Progress card
            print("3. Testing Harvest Bank Progress card orientation display for Long Video...")
            page.evaluate("() => navigateToStep(4)")
            page.wait_for_timeout(300)
            page.evaluate("""async () => {
                await renderSelfHealingBanner({
                    status: "waiting_for_clips",
                    reason_code: "CLIPS_SHORTFALL",
                    clips_ready: 93,
                    clips_needed: 100,
                    startTimeMs: Date.now() - 38000,
                    harvestStatus: {
                        is_harvesting: false,
                        growth_per_minute: 0.0,
                        last_activity_time: Math.floor(Date.now() / 1000 - 38)
                    },
                    waitCheckpoint: {
                        waiting_since: Math.floor(Date.now() / 1000 - 38),
                        consecutive_no_growth: 0
                    }
                }, 93, 100, false);
            }""")
            page.wait_for_timeout(500)

            banner = page.locator("#self-heal-amber-banner")
            self.assertTrue(banner.is_visible())
            banner_text = banner.inner_text()
            print("Banner text preview:")
            print(banner_text)

            # Crucial verification: Must show Landscape 16:9, NOT Vertical 9:16
            self.assertIn("Landscape 16:9", banner_text)
            self.assertNotIn("Vertical 9:16", banner_text)

            # Take screenshot of the corrected Harvest Bank Progress banner
            banner_screenshot_path = os.path.join(SCREENSHOT_DIR, "long_video_landscape_progress_card.png")
            banner.screenshot(path=banner_screenshot_path)
            print(f"Saved banner screenshot to: {banner_screenshot_path}")

            browser.close()
            print("Playwright long video UI verification successful!")

if __name__ == "__main__":
    unittest.main()
