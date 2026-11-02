import os
import sys
import unittest
import json
import re
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_URL = "http://127.0.0.1:8000"

class TestExportScreenAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def _open_export_page(self, width=1440, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        page.goto(f"{BASE_URL}/#export", wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        return page

    def test_01_no_tabs_on_export_screen(self):
        """Assert zero tab navigation or tab strips anywhere in the export screen."""
        page = self._open_export_page()
        tabs_found = page.evaluate("""() => {
            const expView = document.getElementById("view-export");
            if (!expView) return -1;
            const tabs = expView.querySelectorAll(".nav-tabs, .tab-strip, .cockpit-tabs-nav, [role='tablist'], .tab-button");
            return tabs.length;
        }""")
        page.close()
        self.assertEqual(tabs_found, 0, f"Expected 0 tabs on export screen, found {tabs_found}")

    def test_02_all_four_platform_rows_present(self):
        """Assert all 4 platform rows are always visible together in the DOM."""
        page = self._open_export_page()
        rows = page.evaluate("""() => {
            const expected = ["youtube_shorts", "youtube_video", "tiktok", "instagram_reels"];
            return expected.map(id => {
                const el = document.getElementById(`platform-row-${id}`);
                return {
                    id: id,
                    present: !!el,
                    visible: el ? (window.getComputedStyle(el).display !== 'none') : false
                };
            });
        }""")
        page.close()
        for r in rows:
            self.assertTrue(r["present"], f"Row {r['id']} must exist in DOM")
            self.assertTrue(r["visible"], f"Row {r['id']} must be visible")

    def test_03_status_lines_30s_short(self):
        """Assert status lines and best fit marker for 30s vertical short."""
        page = self._open_export_page()
        page.evaluate("""() => window.setupExportScreen('lionreel_cat_20261017_102216_9ed2b729.mp4')""")
        page.wait_for_timeout(400)

        statuses = page.evaluate("""() => {
            return {
                shorts_status: document.getElementById('status-youtube_shorts')?.innerText,
                shorts_best: document.getElementById('best-fit-youtube_shorts')?.style.display !== 'none',
                yt_status: document.getElementById('status-youtube_video')?.innerText,
                tiktok_status: document.getElementById('status-tiktok')?.innerText,
                reels_status: document.getElementById('status-instagram_reels')?.innerText
            };
        }""")
        page.close()
        self.assertIn("fits", statuses["shorts_status"].lower())
        self.assertTrue(statuses["shorts_best"], "Shorts should be BEST FIT for 30s vertical")
        self.assertIn("fits", statuses["yt_status"].lower())
        self.assertIn("fits", statuses["tiktok_status"].lower())
        self.assertIn("fits", statuses["reels_status"].lower())

    def test_04_status_lines_3min_landscape(self):
        """Assert status lines and unavailability reasons for 3min 16:9 video."""
        page = self._open_export_page()
        page.evaluate("""() => window.setupExportScreen('lionreel_cat_3min_16_9.mp4')""")
        page.wait_for_timeout(400)

        eval_data = page.evaluate("""() => {
            return {
                yt_status: document.getElementById('status-youtube_video')?.innerText,
                yt_best: document.getElementById('best-fit-youtube_video')?.style.display !== 'none',
                shorts_status: document.getElementById('status-youtube_shorts')?.innerText,
                shorts_disabled: document.getElementById('btn-upload-youtube_shorts')?.disabled,
                tiktok_status: document.getElementById('status-tiktok')?.innerText,
                tiktok_disabled: document.getElementById('btn-upload-tiktok')?.disabled,
                reels_status: document.getElementById('status-instagram_reels')?.innerText,
                reels_disabled: document.getElementById('btn-upload-instagram_reels')?.disabled
            };
        }""")
        page.close()
        self.assertIn("fits", eval_data["yt_status"].lower())
        self.assertTrue(eval_data["yt_best"], "YouTube video should be BEST FIT for 16:9 video")
        self.assertIn("16:9", eval_data["shorts_status"])
        self.assertTrue(eval_data["shorts_disabled"])
        self.assertIn("16:9", eval_data["tiktok_status"])
        self.assertTrue(eval_data["tiktok_disabled"])
        self.assertIn("16:9", eval_data["reels_status"])
        self.assertTrue(eval_data["reels_disabled"])

    def test_05_status_lines_19m52s_landscape(self):
        """Assert status lines for 19:52 long video."""
        page = self._open_export_page()
        page.evaluate("""() => window.setupExportScreen('lionreel_cat_20261015_190045_fc2355ef.mp4')""")
        page.wait_for_timeout(400)

        eval_data = page.evaluate("""() => {
            return {
                yt_status: document.getElementById('status-youtube_video')?.innerText,
                yt_best: document.getElementById('best-fit-youtube_video')?.style.display !== 'none',
                shorts_status: document.getElementById('status-youtube_shorts')?.innerText,
                shorts_disabled: document.getElementById('btn-upload-youtube_shorts')?.disabled
            };
        }""")
        page.close()
        self.assertIn("fits", eval_data["yt_status"].lower())
        self.assertTrue(eval_data["yt_best"])
        self.assertTrue(eval_data["shorts_disabled"])

    def test_06_exactly_one_new_compilation_button(self):
        """Assert exactly one 'New compilation' button exists across page."""
        page = self._open_export_page()
        btn_count = page.evaluate("""() => {
            const allBtns = Array.from(document.querySelectorAll("button, a.btn"));
            const newCompBtns = allBtns.filter(b => (b.innerText || "").toLowerCase().includes("new compilation"));
            return newCompBtns.length;
        }""")
        page.close()
        self.assertEqual(btn_count, 1, f"Expected exactly 1 'New compilation' button, found {btn_count}")

    def test_07_no_horizontal_overflow_across_viewports(self):
        """Assert no clipping or horizontal overflow at 1440, 1280, 1024, 860, 390 px."""
        for width in [1440, 1280, 1024, 860, 390]:
            page = self._open_export_page(width=width, height=800)
            overflow = page.evaluate("""() => {
                return document.body.scrollWidth > document.body.clientWidth;
            }""")
            page.close()
            self.assertFalse(overflow, f"Horizontal overflow detected at {width}px width")

    def test_08_activity_chip_idle_and_jobs_panel(self):
        """Assert topbar activity chip indicates 'idle' and controls collapsible panel."""
        page = self._open_export_page()
        chip_data = page.evaluate("""() => {
            const chip = document.getElementById("topbar-activity-chip");
            const label = document.getElementById("topbar-activity-text") || document.getElementById("topbar-activity-label");
            const panel = document.getElementById("topbar-jobs-panel");
            return {
                chip_present: !!chip,
                is_idle: chip?.classList.contains("idle"),
                label_text: label?.innerText?.trim(),
                panel_present: !!panel,
                panel_initially_hidden: panel?.style.display === "none"
            };
        }""")
        self.assertTrue(chip_data["chip_present"])
        self.assertTrue(chip_data["is_idle"])
        self.assertEqual(chip_data["label_text"], "idle")
        self.assertTrue(chip_data["panel_present"])
        self.assertTrue(chip_data["panel_initially_hidden"])

        panel_opened = page.evaluate("""() => {
            const chip = document.getElementById("topbar-activity-chip");
            chip.click();
            const panel = document.getElementById("topbar-jobs-panel");
            return panel?.style.display === "block";
        }""")
        self.assertTrue(panel_opened, "Clicking activity chip must toggle jobs panel open")
        page.close()

    def test_09_repeat_share_note_logic(self):
        """Assert repeat share sentence displays when repeat > 40% and hides otherwise."""
        page = self._open_export_page()

        # Case 1: 50% repeat share
        note_50 = page.evaluate("""() => {
            const mockTarget = { name: "test_comp.mp4", duration: 30, repeat_share_pct: 50 };
            window.setupExportScreen(mockTarget);
            const noteEl = document.getElementById("export-repeat-note");
            return {
                visible: noteEl && window.getComputedStyle(noteEl).display !== "none",
                text: noteEl?.innerText
            };
        }""")
        self.assertTrue(note_50["visible"], "Repeat note must be visible at 50% repeat")
        self.assertIn("50% of this video reuses moments", note_50["text"])

        # Case 2: 15% repeat share
        note_15 = page.evaluate("""() => {
            const mockTarget = { name: "test_comp2.mp4", duration: 30, repeat_share_pct: 15 };
            window.setupExportScreen(mockTarget);
            const noteEl = document.getElementById("export-repeat-note");
            return {
                visible: noteEl && window.getComputedStyle(noteEl).display !== "none"
            };
        }""")
        self.assertFalse(note_15["visible"], "Repeat note must be hidden at <= 40% repeat")
        page.close()

    def test_10_keyboard_accessibility_and_aria(self):
        """Assert keyboard accessibility and ARIA roles/labels on export controls."""
        page = self._open_export_page()
        a11y = page.evaluate("""() => {
            const results = {};
            const drawers = ["youtube_shorts", "youtube_video", "tiktok", "instagram_reels"];
            drawers.forEach(id => {
                const btn = document.getElementById(`btn-toggle-drawer-${id}`);
                results[id] = {
                    has_aria_expanded: btn?.hasAttribute("aria-expanded"),
                    aria_expanded_val: btn?.getAttribute("aria-expanded"),
                    has_aria_label: btn?.hasAttribute("aria-label")
                };
            });
            results.topbar_chip = {
                has_haspopup: document.getElementById("topbar-activity-chip")?.hasAttribute("aria-haspopup"),
                has_aria_expanded: document.getElementById("topbar-activity-chip")?.hasAttribute("aria-expanded")
            };
            return results;
        }""")
        page.close()
        for id in ["youtube_shorts", "youtube_video", "tiktok", "instagram_reels"]:
            self.assertTrue(a11y[id]["has_aria_expanded"])
            self.assertEqual(a11y[id]["aria_expanded_val"], "false")
            self.assertTrue(a11y[id]["has_aria_label"])
        self.assertTrue(a11y["topbar_chip"]["has_haspopup"])

if __name__ == "__main__":
    unittest.main()
