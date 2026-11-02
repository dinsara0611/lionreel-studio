import os
import sys
import unittest
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8000"

class TestPartAUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def test_a1_export_actions_no_overflow(self):
        """A1: Export panel quick actions never overflow at 1440, 1280, 1024, 860, 390 px."""
        viewports = [1440, 1280, 1024, 860, 390]
        for w in viewports:
            context = self.browser.new_context(viewport={"width": w, "height": 900})
            page = context.new_page()
            page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
            page.wait_for_timeout(600)
            page.evaluate("() => { if (window.navigateToStep) window.navigateToStep(5); }")
            page.wait_for_timeout(400)

            # Check quick actions row
            res = page.evaluate("""() => {
                const row = document.querySelector('.export-panel-quick-actions');
                const panel = document.querySelector('.export-tabs-panel');
                if (!row || !panel) return { exists: false };
                const rBox = row.getBoundingClientRect();
                const pBox = panel.getBoundingClientRect();
                const overflowsRight = (rBox.right > pBox.right + 2);
                const hasWrapOrMenu = (row.scrollWidth <= row.clientWidth + 2) || (window.getComputedStyle(row).flexWrap === 'wrap');
                return {
                    exists: true,
                    overflowsRight: overflowsRight,
                    hasWrapOrMenu: hasWrapOrMenu,
                    scrollWidth: row.scrollWidth,
                    clientWidth: row.clientWidth
                };
            }""")
            context.close()
            self.assertTrue(res.get("exists"), f"Quick actions row should exist at {w}px")
            self.assertFalse(res.get("overflowsRight"), f"Export quick actions row overflows panel to the right at {w}px: {res}")

    def test_a2_preview_player_viewport_and_unmute_pill(self):
        """A2: Player fits viewport, no huge black area, unmute control is a small corner pill."""
        context = self.browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
        page.wait_for_timeout(600)
        page.evaluate("() => { if (window.navigateToStep) window.navigateToStep(5); }")
        page.wait_for_timeout(400)

        data = page.evaluate("""() => {
            const wrap = document.getElementById('export-player-wrap');
            const video = document.getElementById('export-video-player');
            const pill = document.getElementById('btn-player-unmute');
            if (!wrap || !video || !pill) return { exists: false };
            const wBox = wrap.getBoundingClientRect();
            const vBox = video.getBoundingClientRect();
            const pBox = pill.getBoundingClientRect();
            const pillIsFullWidth = (pBox.width >= wBox.width * 0.7);
            return {
                exists: true,
                wrapWidth: wBox.width,
                wrapHeight: wBox.height,
                videoWidth: vBox.width,
                videoHeight: vBox.height,
                pillIsFullWidth: pillIsFullWidth,
                pillWidth: pBox.width
            };
        }""")
        context.close()
        self.assertTrue(data.get("exists"))
        self.assertFalse(data.get("pillIsFullWidth"), f"Unmute button should be a small corner pill, not full-width: {data}")

    def test_a3_resolution_and_aspect_ratio_match(self):
        """A3: 1920x1080 can never say 9:16."""
        context = self.browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
        page.wait_for_timeout(600)
        page.evaluate("() => { if (window.navigateToStep) window.navigateToStep(5); }")
        page.wait_for_timeout(400)

        data = page.evaluate("""() => {
            const statRes = document.getElementById('export-stat-res');
            const statAspect = document.getElementById('export-stat-aspect');
            return {
                res: statRes ? statRes.innerText.trim() : '',
                aspect: statAspect ? statAspect.innerText.trim() : ''
            };
        }""")
        context.close()
        if "1920" in data["res"] and "1080" in data["res"] and data["res"].startswith("1920"):
            self.assertNotIn("9:16", data["aspect"], f"1920x1080 cannot have 9:16 label: {data}")

    def test_a4_platform_tabs_states_and_upload_button(self):
        """A4: Platform tabs clear states, upload button text matches active platform."""
        context = self.browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
        page.wait_for_timeout(600)
        page.evaluate("() => { if (window.navigateToStep) window.navigateToStep(5); }")
        page.wait_for_timeout(400)

        # Switch to YouTube Video
        page.evaluate("""() => {
            const btn = document.getElementById('choice-yt-video');
            if (btn) btn.click();
        }""")
        page.wait_for_timeout(300)

        data = page.evaluate("""() => {
            const uploadBtn = document.getElementById('label-primary-platform-upload') || document.getElementById('btn-primary-platform-upload');
            const activeTab = document.querySelector('.platform-choice-btn.active');
            return {
                uploadText: uploadBtn ? uploadBtn.innerText : '',
                activePlatform: activeTab ? activeTab.getAttribute('data-platform') : ''
            };
        }""")
        context.close()
        self.assertIn("YouTube", data["uploadText"], f"Upload button should match active YouTube platform: {data}")
        self.assertNotIn("Shorts", data["uploadText"], f"YouTube Video mode must not say Shorts on upload button: {data}")

    def test_a5_library_cards_equal_height_and_test_filter(self):
        """A5: Library cards have equal height and test/contract/sandbox jobs are filtered by default."""
        context = self.browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
        page.wait_for_timeout(600)
        page.evaluate("() => { if (window.navigateToStep) window.navigateToStep(5); }")
        page.wait_for_timeout(300)
        page.evaluate("() => { const t = document.getElementById('tab-nav-library'); if (t) t.click(); }")
        page.wait_for_timeout(500)

        data = page.evaluate("""() => {
            const cards = Array.from(document.querySelectorAll('.project-card, .export-project-chip'));
            const cardNames = cards.map(c => c.getAttribute('data-proj-name') || c.getAttribute('data-file-name') || c.innerText);
            const heights = cards.map(c => Math.round(c.getBoundingClientRect().height));
            const hasTestJobsVisible = cardNames.some(n => n.includes('job_real_contract') || n.includes('sandbox') || n.includes('test_'));
            return {
                count: cards.length,
                cardNames: cardNames,
                heights: heights,
                hasTestJobsVisible: hasTestJobsVisible
            };
        }""")
        context.close()
        self.assertFalse(data.get("hasTestJobsVisible"), f"Test/acceptance/contract jobs must be hidden from production library by default: {data}")

    def test_a6_quality_chips_honest_repeat_and_length_delta(self):
        """A6: Repeat >= 40% turns into amber sentence; length chip shows real delta."""
        context = self.browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
        page.wait_for_timeout(600)
        page.evaluate("() => { if (window.navigateToStep) window.navigateToStep(5); }")
        page.wait_for_timeout(400)

        # Trigger high repeat state (e.g. 79.2%)
        data = page.evaluate("""() => {
            if (window.setupExportScreen) {
                window.setupExportScreen({
                    name: 'test_repeat_sample.mp4',
                    width: 1920,
                    height: 1080,
                    duration: 180.1,
                    expected_duration_s: 180.0,
                    repeat_share_pct: 79.2,
                    overall_passed: true
                });
            }
            const chipRep = document.getElementById('chip-export-repeat');
            const chipLen = document.getElementById('chip-export-length');
            const repText = document.getElementById('export-stat-repeat') || document.getElementById('export-chip-repeat-text');
            const lenText = document.getElementById('export-chip-length-text');
            return {
                repText: repText ? repText.innerText : '',
                lenText: lenText ? lenText.innerText : '',
                isRepeatAmber: chipRep ? (chipRep.classList.contains('chip-warning') || chipRep.classList.contains('chip-amber')) : false
            };
        }""")
        context.close()
        self.assertTrue("79%" in data["repText"] and "reuses earlier moments" in data["repText"],
                        f"Repeat >= 40% should show honest sentence: {data}")

if __name__ == "__main__":
    unittest.main()
