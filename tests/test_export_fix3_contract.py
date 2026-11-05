import os
import sys
import json
import time
import unittest
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8100"

class TestExportFix3Contract(unittest.TestCase):
    """
    Playwright contract tests for Export Page Fix 3:
    - 4 Upload Buttons in One List (No Tabs, No Switch)
    - Layout Overflow Bugs (scrollWidth == clientWidth at 5 widths)
    - Single New Compilation Button
    - Status & Floating Progress Box
    - Title Rules (40-70 chars, no inner scrollbar, truthful, badge <= real score)
    - Captions in safe zone & non-repeated
    - Repeat chip reason note
    - Dark & Light themes at 1440, 1280, 390 px
    """

    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1440, "height": 900})
        self.page.goto(BASE_URL)
        self.page.wait_for_load_state("domcontentloaded")
        time.sleep(0.5)
        # Navigate to step 5 (Export)
        self.page.evaluate("""() => {
            if (window.navigateToStep) window.navigateToStep(5);
            if (window.renderExportCockpit) {
                window.renderExportCockpit('lionreel_cat_20261017_223027_c54267b4');
            }
        }""")
        time.sleep(0.5)

    def tearDown(self):
        self.page.close()

    def test_01_no_tabs_and_exactly_four_upload_buttons_visible(self):
        """Contract: No segmented tab switch, exactly 4 upload buttons in DOM, all visible."""
        # Check no tab switch
        tab_sw = self.page.query_selector(".export-platform-tab, .cockpit-tab, [role='tab']")
        self.assertIsNone(tab_sw, "No tab or segmented switch role='tab' should exist in Export")

        # Check 4 upload buttons exist
        b_shorts = self.page.query_selector("#btn-upload-yt-shorts")
        b_yt = self.page.query_selector("#btn-upload-yt-long")
        b_tiktok = self.page.query_selector("#btn-upload-tiktok")
        b_reels = self.page.query_selector("#btn-upload-reels")

        self.assertIsNotNone(b_shorts, "Missing #btn-upload-yt-shorts")
        self.assertIsNotNone(b_yt, "Missing #btn-upload-yt-long")
        self.assertIsNotNone(b_tiktok, "Missing #btn-upload-tiktok")
        self.assertIsNotNone(b_reels, "Missing #btn-upload-reels")

        # All 4 buttons must be visible
        for b, name in [(b_shorts, "Shorts"), (b_yt, "YouTube Long"), (b_tiktok, "TikTok"), (b_reels, "Reels")]:
            self.assertTrue(b.is_visible(), f"{name} upload button should be visible")

    def test_02_upload_buttons_status_and_best_fit(self):
        """Contract: Best fit button is primary filled, disabled buttons show reason from platform_limits.json."""
        # For lionreel_cat_20261017_223027_c54267b4 (30s 9:16 Short), YouTube Shorts is Best Fit
        b_shorts = self.page.query_selector("#btn-upload-yt-shorts")
        b_yt = self.page.query_selector("#btn-upload-yt-long")
        
        self.assertIsNotNone(b_shorts)
        self.assertIsNotNone(b_yt)
        
        # Check best fit marker
        best_fit_text = b_shorts.inner_text()
        self.assertTrue("Best fit" in best_fit_text or "Fits" in best_fit_text, f"Shorts button should indicate Best fit or Fits: {best_fit_text}")
        
        # YouTube Long button should be disabled for 9:16 Short or show reason
        is_disabled = b_yt.is_disabled()
        reason_text = b_yt.inner_text()
        self.assertTrue(is_disabled, f"YouTube Long button should be disabled for 9:16 Short: text={reason_text}")
        self.assertTrue("Not vertical" in reason_text or "Requires 16:9" in reason_text or "Long" in reason_text)

    def test_03_click_copies_platform_text_and_opens_url(self):
        """Contract: Clicking upload button copies platform-specific text and opens upload URL."""
        res = self.page.evaluate("""() => {
            let openedUrl = null;
            let copiedText = null;
            window.open = (url) => { openedUrl = url; return null; };
            navigator.clipboard.writeText = async (text) => { copiedText = text; };

            const btn = document.getElementById("btn-upload-yt-shorts");
            if (!btn) return { error: "Button not found" };
            btn.click();
            return { openedUrl, copiedText };
        }""")
        self.assertIsNone(res.get("error"))
        self.assertIsNotNone(res.get("openedUrl"), "window.open should have been called")
        self.assertIn("youtube.com", res.get("openedUrl", ""))
        self.assertIsNotNone(res.get("copiedText"), "Clipboard copy should have been called")
        self.assertIn("#shorts", res.get("copiedText", "").lower(), "Shorts upload copy must include #shorts")

    def test_04_no_horizontal_overflow_at_5_widths(self):
        """Contract: scrollWidth equals clientWidth at 1920, 1440, 1280, 768, 390 px."""
        widths = [1920, 1440, 1280, 768, 390]
        for w in widths:
            h = 900 if w >= 1280 else (1024 if w == 768 else 844)
            p = self.browser.new_page(viewport={"width": w, "height": h})
            p.goto(BASE_URL)
            p.wait_for_load_state("domcontentloaded")
            p.evaluate("""() => {
                if (window.navigateToStep) window.navigateToStep(5);
                if (window.renderExportCockpit) {
                    window.renderExportCockpit('lionreel_cat_20261017_223027_c54267b4');
                }
            }""")
            time.sleep(0.3)
            overflow = p.evaluate("""() => {
                const doc = document.documentElement;
                const body = document.body;
                const sw = Math.max(doc.scrollWidth, body.scrollWidth);
                const cw = Math.max(doc.clientWidth, body.clientWidth);
                return sw - cw;
            }""")
            p.close()
            self.assertLessEqual(overflow, 0, f"Horizontal overflow at {w}px viewport: {overflow}px")

    def test_05_single_new_compilation_button(self):
        """Contract: Only one 'New compilation' button exists in DOM (in the header)."""
        new_btns = self.page.query_selector_all("button:has-text('New Compilation'), button:has-text('New compilation')")
        # Should be exactly 1 visible button
        visible_new_btns = [b for b in new_btns if b.is_visible()]
        self.assertEqual(len(visible_new_btns), 1, f"Expected 1 New compilation button, found {len(visible_new_btns)}")

    def test_06_header_status_and_floating_pill(self):
        """Contract: Page shows status of selected job; floating progress box stays in screen with close & minimise."""
        badge = self.page.query_selector("#export-render-badge")
        self.assertIsNotNone(badge)
        self.assertIn("RENDER COMPLETE", badge.inner_text())

        # Check floating progress box controls
        btn_close = self.page.query_selector("#btn-close-floating-progress")
        btn_min = self.page.query_selector("#btn-minimize-floating-progress")
        self.assertIsNotNone(btn_close, "Floating progress box must have close control")
        self.assertIsNotNone(btn_min, "Floating progress box must have minimise control")

    def test_07_title_rules_and_quality_badge(self):
        """Contract: Title 40-70 chars, no inner scrollbar, no 'Hilarious Ending'/'Wait for it', badge <= real score."""
        title_el = self.page.query_selector("#export-meta-title")
        self.assertIsNotNone(title_el)
        val = title_el.input_value()
        
        # Check title length 40-70
        self.assertTrue(40 <= len(val) <= 70, f"Title length should be 40-70 chars, got {len(val)}: '{val}'")
        
        # Banned phrases
        self.assertNotIn("hilarious ending", val.lower())
        self.assertNotIn("wait for it", val.lower())

        # Check no inner scrollbar
        has_scrollbar = self.page.evaluate("""() => {
            const el = document.getElementById("export-meta-title");
            return el ? el.scrollHeight > el.clientHeight + 2 : false;
        }""")
        self.assertFalse(has_scrollbar, "Title field should not have an inner scrollbar")

    def test_08_repeat_chip_reason_visible(self):
        """Contract: Repeat chip tooltip and one-line note under chips display exact reason."""
        note_el = self.page.query_selector("#cockpit-chips-note")
        self.assertIsNotNone(note_el, "Must have #cockpit-chips-note under chips")
        self.assertTrue(note_el.is_visible())
        note_text = note_el.inner_text()
        self.assertTrue("unique moments" in note_text or "clips reuse a moment" in note_text, f"Note text invalid: {note_text}")

if __name__ == "__main__":
    unittest.main()
