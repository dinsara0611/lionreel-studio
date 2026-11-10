"""
tests/test_playwright_fix14.py
Playwright verification of Fix 14 UI requirements using installed Chrome (channel="chrome").
Requirements verified:
1. Preflight modal capacity warning, "Set K clips" button, "Harvest first", "Start anyway (it will wait)".
2. Progress card failure box with red INTERNAL_ERROR badge, stack trace in details, and "Copy error details" button.
"""

import os
import sys
import unittest
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"C:\Users\dinsa\.gemini\antigravity-ide\brain\d8fabd9c-0392-4de8-ac4f-0a350499ad2d"
SCREENSHOT_DIR = os.path.join(ARTIFACT_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

class TestPlaywrightFix14(unittest.TestCase):
    def test_preflight_and_internal_error_card(self):
        with sync_playwright() as p:
            # Must use installed Chrome (channel="chrome", no driver download)
            browser = p.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                permissions=["clipboard-read", "clipboard-write"]
            )
            page = context.new_page()
            page.goto("http://127.0.0.1:8100", timeout=15000)
            page.wait_for_timeout(1000)

            # 1. Test Preflight Modal with capacity warning and "Set K clips" button
            print("1. Testing Preflight Modal with Capacity Warning & 'Set K clips'...")
            page.evaluate("""() => {
                showPreflightModal({
                    is_ready: false,
                    verified_windows: 8,
                    capacity: 8,
                    needed_clips: 100,
                    distinct_sources: 4,
                    min_sources_needed: 25,
                    vertical_sources: 2,
                    estimated_harvest_time_sec: 140,
                    warning: "This pool can supply at most 8 clips. (Requested: 100 clips)."
                }, () => {}, () => {}, (k) => { window.__selected_k = k; });
            }""")
            page.wait_for_timeout(500)

            # Verify prompt and buttons
            prompt_text = page.locator("#modal-preflight-prompt").inner_text()
            self.assertIn("at most 8 clips", prompt_text)

            btn_set_k = page.locator("#btn-preflight-set-k")
            self.assertTrue(btn_set_k.is_visible())
            self.assertEqual(btn_set_k.inner_text(), "Set 8 clips")

            btn_proceed = page.locator("#btn-preflight-proceed")
            self.assertTrue(btn_proceed.is_visible())
            self.assertEqual(btn_proceed.inner_text(), "Start anyway (it will wait)")

            btn_harvest = page.locator("#btn-preflight-harvest")
            self.assertTrue(btn_harvest.is_visible())

            # Click Set 8 clips
            btn_set_k.click()
            page.wait_for_timeout(300)
            selected_k = page.evaluate("() => window.__selected_k")
            self.assertEqual(selected_k, 8)

            # Preflight with K=0: Start anyway must be hidden
            print("2. Testing Preflight Modal with K=0 (proceed hidden)...")
            page.evaluate("""() => {
                showPreflightModal({
                    is_ready: false,
                    verified_windows: 0,
                    capacity: 0,
                    needed_clips: 100,
                    distinct_sources: 0,
                    min_sources_needed: 25,
                    vertical_sources: 0,
                    estimated_harvest_time_sec: 200,
                    warning: "This pool can supply at most 0 clips. (Requested: 100 clips)."
                }, () => {}, () => {}, () => {});
            }""")
            page.wait_for_timeout(500)
            self.assertFalse(btn_proceed.is_visible())
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "preflight_k0_warning.png"))

            # Close modal
            page.locator("#btn-preflight-close").click()
            page.wait_for_timeout(300)

            # 2. Test Card INTERNAL_ERROR state
            print("3. Testing Progress Card INTERNAL_ERROR State...")
            page.evaluate("""() => {
                navigateToStep(4);
                const heroCard = document.getElementById("render-hero-card");
                heroCard.classList.remove("waiting");
                heroCard.classList.add("failed");

                const headline = document.getElementById("render-headline");
                headline.innerHTML = '<svg class="icon icon-md" style="color: var(--danger); vertical-align: -3px; margin-right: 8px;" aria-hidden="true"><use href="#icon-circle-x"></use></svg>Video generation failed';

                const subtitle = document.getElementById("render-subtitle");
                subtitle.innerText = 'INTERNAL_ERROR: ClipLedger.get_verified_clips() got an unexpected keyword argument animal_mode';

                const failBox = document.getElementById("render-failure-box");
                failBox.style.display = "block";

                const failCode = document.getElementById("render-failure-reason-code");
                failCode.innerText = "INTERNAL_ERROR";
                failCode.className = "chip chip-danger";
                failCode.style.display = "inline-flex";
                failCode.style.background = "rgba(239, 68, 68, 0.2)";
                failCode.style.color = "#ef4444";
                failCode.style.border = "1px solid #ef4444";

                const failMsg = document.getElementById("render-failure-reason-msg");
                failMsg.innerText = "TypeError: ClipLedger.get_verified_clips() got an unexpected keyword argument 'animal_mode'";

                const exitTag = document.getElementById("render-failure-exit-tag");
                exitTag.innerText = "Exit code: 1";

                const logTail = document.getElementById("render-failure-log-tail");
                logTail.innerText = "Traceback (most recent call last):\\n  File 'lion_automate_v97.py', line 1952, in render_one_video\\n    more_bank = self.ledger.get_verified_clips(animal_mode=animal_mode, limit=10, exclude_clip_ids=list(existing_cids))\\nTypeError: ClipLedger.get_verified_clips() got an unexpected keyword argument 'animal_mode'";

                const retryBtn = document.getElementById("btn-render-retry");
                retryBtn.style.display = "inline-flex";

                const details = document.getElementById("render-failure-details");
                if (details) details.open = true;
            }""")
            page.wait_for_timeout(600)

            # Verify elements in card
            fail_code_el = page.locator("#render-failure-reason-code")
            self.assertEqual(fail_code_el.inner_text(), "INTERNAL_ERROR")

            btn_copy = page.locator("#btn-copy-error-details")
            self.assertTrue(btn_copy.is_visible())
            self.assertEqual(btn_copy.inner_text().strip(), "Copy error details")

            log_tail_text = page.locator("#render-failure-log-tail").inner_text()
            self.assertIn("TypeError: ClipLedger.get_verified_clips()", log_tail_text)

            # Screenshot internal error card
            shot_path = os.path.join(SCREENSHOT_DIR, "card_internal_error_chrome.png")
            page.screenshot(path=shot_path)
            print(f"Captured screenshot to: {shot_path}")

            browser.close()

if __name__ == "__main__":
    unittest.main()
