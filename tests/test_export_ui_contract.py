"""
Playwright Contract Tests for Export Page (Step 5):
"COCKPIT LAYOUT — ONE SCREEN, NO TABS, ZONES A/B/C/D"

Uses installed Chrome (channel="chrome", no external driver downloads).
"""
import os
import sys
import json
from playwright.sync_api import sync_playwright

SERVER_URL = "http://127.0.0.1:8100"
TARGET_SHORT_ID = "lionreel_cat_20261016_084742_31bc5d3b"

def test_export_ui_contract():
    print("\n=== STARTING EXPORT COCKPIT CONTRACT PLAYWRIGHT TEST SUITE ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)

        # -------------------------------------------------------------
        # TEST 1: NO TABS IN THE DOM
        # -------------------------------------------------------------
        print("\n--- [1] Checking Zero Tabs In The DOM ---")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(SERVER_URL, timeout=20000)
        page.wait_for_timeout(1000)
        page.evaluate(f"() => window.navigateToStep(5, '{TARGET_SHORT_ID}.mp4')")
        page.wait_for_timeout(1200)

        tabs_count = page.locator("#view-export .export-nav-tab, #view-export [role='tab']").count()
        print(f"  Tabs count in Export DOM: {tabs_count}")
        assert tabs_count == 0, f"Found {tabs_count} tabs in Export DOM! Cockpit design strictly prohibits tabs."

        # -------------------------------------------------------------
        # TEST 2: ZONES A, B, C, D VISIBLE TOGETHER (1440x900 ZERO PAGE SCROLL)
        # -------------------------------------------------------------
        print("\n--- [2] Checking Zones A, B, C, D & 1440x900 Zero Page Scroll ---")
        zone_a = page.locator("#cockpit-zone-a")
        zone_b = page.locator("#cockpit-zone-b")
        zone_c = page.locator("#cockpit-zone-c")
        zone_d = page.locator("#cockpit-zone-d")

        assert zone_a.is_visible(), "Zone A (Player & Specs) must be visible!"
        assert zone_b.is_visible(), "Zone B (Publish) must be visible!"
        assert zone_c.is_visible(), "Zone C (Action Rail) must be visible!"
        assert zone_d.is_visible(), "Zone D (Filmstrip) must be visible!"

        scroll_h = page.evaluate("() => document.documentElement.scrollHeight")
        client_h = page.evaluate("() => document.documentElement.clientHeight")
        print(f"  Viewport 1440x900: scrollHeight={scroll_h}, clientHeight={client_h}")
        assert scroll_h <= 900, f"Page has vertical scrollbar at 1440x900! scrollHeight={scroll_h} > 900"

        # -------------------------------------------------------------
        # TEST 3: 1280x720 ZERO PAGE SCROLL
        # -------------------------------------------------------------
        print("\n--- [3] Checking Desktop 1280x720 Zero Page Scroll ---")
        ctx_720 = browser.new_context(viewport={"width": 1280, "height": 720})
        page_720 = ctx_720.new_page()
        page_720.goto(SERVER_URL, timeout=20000)
        page_720.wait_for_timeout(1000)
        page_720.evaluate(f"() => window.navigateToStep(5, '{TARGET_SHORT_ID}.mp4')")
        page_720.wait_for_timeout(1200)

        scroll_h_720 = page_720.evaluate("() => document.documentElement.scrollHeight")
        print(f"  Viewport 1280x720: scrollHeight={scroll_h_720}")
        assert scroll_h_720 <= 720, f"Page has vertical scrollbar at 1280x720! scrollHeight={scroll_h_720} > 720"
        ctx_720.close()

        # -------------------------------------------------------------
        # TEST 4: ONE PLATFORM CONTROL ONLY AND ONE PRIMARY UPLOAD BUTTON
        # -------------------------------------------------------------
        print("\n--- [4] Checking Single Platform Control & Single Primary Upload ---")
        platform_controls = page.locator("#export-platform-switcher")
        assert platform_controls.count() == 1, "Must have exactly ONE platform segmented control!"

        primary_upload = page.locator("#btn-primary-platform-upload")
        assert primary_upload.is_visible(), "Primary platform upload button must be visible!"

        old_redirects = page.locator(".upload-redirect-btn").count()
        assert old_redirects == 0, f"Found {old_redirects} legacy duplicate upload buttons!"

        # -------------------------------------------------------------
        # TEST 5: THUMBNAIL ABSENT FOR SHORT, PRESENT FOR LONG
        # -------------------------------------------------------------
        print("\n--- [5] Checking Thumbnail Gating (Absent for Short, Present for Long) ---")
        page.evaluate(f"() => window.setupExportScreen('{TARGET_SHORT_ID}.mp4')")
        page.wait_for_timeout(500)
        thumb_btn = page.locator("#btn-export-thumbnails")
        is_thumb_vis = thumb_btn.is_visible()
        print(f"  Thumbnail button visible for Short: {is_thumb_vis}")
        assert not is_thumb_vis, "Thumbnail button must NOT be visible for a Short (< 180s)!"

        has_long = page.evaluate("() => (state.finishedProjects || []).some(p => p.name.includes('_long') || (p.duration && p.duration >= 180) || p.name.includes('502f5dd4'))")
        if has_long:
            page.evaluate("() => { const lp = state.finishedProjects.find(p => p.name.includes('_long') || (p.duration && p.duration >= 180) || p.name.includes('502f5dd4')); if (lp) window.setupExportScreen(lp.name); }")
            page.wait_for_timeout(500)
            is_long_thumb_vis = thumb_btn.is_visible()
            print(f"  Thumbnail button visible for Long: {is_long_thumb_vis}")
            assert is_long_thumb_vis, "Thumbnail button MUST be visible for a Long video!"

        # -------------------------------------------------------------
        # TEST 6: TEST FILES HIDDEN BY DEFAULT IN FILMSTRIP
        # -------------------------------------------------------------
        print("\n--- [6] Checking Test Files Hidden by Default ---")
        test_items_default = page.evaluate("""() => {
            const list = document.querySelectorAll('#export-projects-scroll-list .cockpit-film-item, #export-projects-scroll-list .export-project-card');
            let count = 0;
            list.forEach(el => {
                if (el.innerText.includes('job_real_contract') || el.innerText.includes('test_') || el.innerText.includes('sandbox_')) count++;
            });
            return count;
        }""")
        print(f"  Test items visible by default: {test_items_default}")
        assert test_items_default == 0, f"Found {test_items_default} test files visible by default in finished filmstrip!"

        # -------------------------------------------------------------
        # TEST 7: RESOLUTION AND REPEAT SHARE IN MONOSPACE LINE & CHIPS
        # -------------------------------------------------------------
        print("\n--- [7] Checking Specs Line & Chips ---")
        page.evaluate(f"() => window.setupExportScreen('{TARGET_SHORT_ID}.mp4')")
        page.wait_for_timeout(500)
        meta_text = page.locator("#export-video-meta").inner_text()
        print(f"  Monospace specs line: {meta_text}")
        assert "1081" not in meta_text, f"Odd width 1081 found in specs! Got: {meta_text}"
        assert "1080" in meta_text, f"1080 must be present in specs! Got: {meta_text}"

        rep_text = page.locator("#export-stat-repeat").inner_text()
        print(f"  Repeat share text: {rep_text}")
        assert ("%" in rep_text), f"Repeat share must show percentage! Got: {rep_text}"

        # -------------------------------------------------------------
        # TEST 8: DELETE NEEDS A CONFIRM DIALOG NAMING THE TARGET FILE
        # -------------------------------------------------------------
        print("\n--- [8] Checking Delete Confirmation Dialog ---")
        # Open More dropdown if necessary
        more_btn = page.locator("#btn-export-more-menu")
        if more_btn.is_visible():
            more_btn.click()
            page.wait_for_timeout(200)

        del_btn = page.locator("#btn-delete-export-video")
        assert del_btn.is_visible(), "Delete video button must be accessible!"
        del_btn.click()
        page.wait_for_timeout(300)

        confirm_modal = page.locator("#modal-delete-confirm")
        assert confirm_modal.is_visible(), "Delete confirmation modal must appear!"
        modal_text = confirm_modal.inner_text()
        assert TARGET_SHORT_ID in modal_text, f"Delete modal must explicitly name the target file! Got: {modal_text}"
        # Safely cancel the modal
        page.click("#btn-cancel-delete")
        page.wait_for_timeout(200)
        assert not confirm_modal.is_visible(), "Modal should close upon cancel"

        # -------------------------------------------------------------
        # TEST 9: MOBILE 390px ZERO HORIZONTAL SCROLL
        # -------------------------------------------------------------
        print("\n--- [9] Checking Mobile 390px Zero Horizontal Scroll ---")
        ctx_mob = browser.new_context(viewport={"width": 390, "height": 844})
        page_mob = ctx_mob.new_page()
        page_mob.goto(SERVER_URL, timeout=20000)
        page_mob.wait_for_timeout(1000)
        page_mob.evaluate(f"() => window.navigateToStep(5, '{TARGET_SHORT_ID}.mp4')")
        page_mob.wait_for_timeout(1000)

        mob_scroll_w = page_mob.evaluate("() => document.documentElement.scrollWidth")
        print(f"  Mobile 390px: scrollWidth={mob_scroll_w}")
        assert mob_scroll_w <= 390, f"Mobile has horizontal scrollbar! scrollWidth={mob_scroll_w} > 390"
        ctx_mob.close()

        ctx.close()
        browser.close()
    print("\n=== ALL EXPORT COCKPIT CONTRACT PLAYWRIGHT TESTS PASSED ===")

if __name__ == "__main__":
    test_export_ui_contract()
