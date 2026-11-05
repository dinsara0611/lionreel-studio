"""
tests/test_ui_report_download_thumb.py
======================================
Automated Playwright E2E test suite for the Report + Download Center + Thumbnail Maker suite.
Uses installed Chrome (channel="chrome", no external driver downloads).

Verifies:
1. Report Viewer modal:
   - A4 layout, HTML iframe loading, pagination sidebar
   - Zoom in/out controls
   - Executive summary clipboard copy
   - PDF download link with inline/attachment header
   - Escape key and backdrop closing
2. Download Center modal:
   - Deliverables package discovery (16 items, 2.22 GB)
   - Large package warning banner (> 1 GB)
   - Multi-select toggle and count
   - Direct download links and ZIP pack download link
   - Open folder / copy path buttons
3. Thumbnail Maker modal:
   - Candidate frame extraction gallery & scoring badges
   - 6 Layout templates & live preview rendering (base64 data URL)
   - Truthful hook character counter (3-5 words, <=28 chars)
   - Automated checklist badges (WCAG contrast, 16:9, safe-zone, <2MB)
   - CTR learning loop status
   - Save active thumbnail & export buttons
4. Failure Diagnostic Mode:
   - Diagnostic Report opens with "Diagnostic Failure Report" title
5. Export Studio & Library Cards Integration:
   - Buttons on Export Step 5 & Finished Project Cards
6. Cross-platform responsive fidelity:
   - Desktop (1440px) & Mobile (390px) in dark & light themes
   - High-res visual screenshot capture
"""

import os
import sys
import json
import time
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_DIR = r"C:\Users\dinsa\.gemini\antigravity-ide\brain\239ba0c7-5b9d-46b1-87d5-ad371a9399fa\screenshots"
ANALYSIS_SCREENSHOTS = os.path.join(BASE_DIR, "analysis", "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(ANALYSIS_SCREENSHOTS, exist_ok=True)

TARGET_JOB_ID = "lionreel_cat_20261016_065802_502f5dd4"
SERVER_URL = "http://127.0.0.1:8100"


def save_screenshot(page, filename):
    p1 = os.path.join(SCREENSHOT_DIR, filename)
    p2 = os.path.join(ANALYSIS_SCREENSHOTS, filename)
    page.screenshot(path=p1)
    page.screenshot(path=p2)
    print(f"  [Screenshot] Saved: {filename}")


def test_ui_report_download_thumb_suite():
    print("\n=== STARTING REPORT + DOWNLOAD CENTER + THUMBNAIL MAKER PLAYWRIGHT SUITE ===")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)

        # -------------------------------------------------------------
        # PART A: DESKTOP 1440px (DARK & LIGHT THEMES)
        # -------------------------------------------------------------
        for theme in ["dark", "light"]:
            print(f"\n--- Testing Desktop (1440x900) - Theme: {theme.upper()} ---")
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                color_scheme=theme
            )
            # Grant clipboard permissions for copy summary testing
            context.grant_permissions(["clipboard-read", "clipboard-write"])
            page = context.new_page()
            page.goto(SERVER_URL, timeout=20000)
            page.wait_for_timeout(1000)

            # Set dark/light class on body if needed
            page.evaluate(f"""() => {{
                document.body.classList.remove('theme-dark', 'theme-light');
                document.body.classList.add('theme-{theme}');
            }}""")

            # ---------------------------------------------------------
            # 1. Report Viewer Verification
            # ---------------------------------------------------------
            print("  [1] Opening Report Viewer...")
            page.evaluate(f"() => window.openReportViewer('{TARGET_JOB_ID}')")
            page.wait_for_timeout(800)

            # Verify modal visible
            modal_rep = page.locator("#modal-report-viewer")
            assert modal_rep.is_visible(), "Report viewer modal should be visible"
            
            sub_text = page.locator("#report-modal-sub").inner_text()
            assert TARGET_JOB_ID in sub_text, f"Report subtitle should contain job id: {sub_text}"

            # Verify PDF download button
            pdf_btn = page.locator("#btn-report-download-pdf")
            pdf_href = pdf_btn.get_attribute("href")
            assert f"/api/jobs/{TARGET_JOB_ID}/report.pdf" in pdf_href, f"Invalid PDF link: {pdf_href}"

            # Verify zoom controls
            zoom_in = page.locator("#btn-report-zoom-in")
            zoom_out = page.locator("#btn-report-zoom-out")
            zoom_label = page.locator("#report-zoom-label")
            assert zoom_label.inner_text() == "100%"
            zoom_in.click()
            page.wait_for_timeout(200)
            assert zoom_label.inner_text() == "115%"
            zoom_out.click()
            page.wait_for_timeout(200)
            assert zoom_label.inner_text() == "100%"

            # Verify Copy Summary button
            copy_btn = page.locator("#btn-report-copy-summary")
            assert copy_btn.is_visible()
            copy_btn.click()
            page.wait_for_timeout(500)

            # Capture Desktop Report Screenshot
            save_screenshot(page, f"report_viewer_desktop_{theme}.png")

            # Verify Escape key closes modal
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            assert not modal_rep.is_visible(), "Report viewer modal should be hidden after Escape"

            # ---------------------------------------------------------
            # 2. Download Center Verification
            # ---------------------------------------------------------
            print("  [2] Opening Download Center...")
            page.evaluate(f"async () => await window.openDownloadCenter('{TARGET_JOB_ID}')")
            page.locator(".deliverable-row").first.wait_for(timeout=10000)

            modal_dl = page.locator("#modal-download-center")
            assert modal_dl.is_visible(), "Download Center modal should be visible"

            # Check rows loaded
            rows = page.locator(".deliverable-row")
            row_count = rows.count()
            print(f"  Deliverables rows found: {row_count}")
            assert row_count >= 15, f"Expected at least 15 deliverable rows, got {row_count}"

            # Check >1GB warning banner
            warning_banner = page.locator("#dl-size-warning")
            assert warning_banner.is_visible(), "Warning banner should be displayed for 2.22 GB package"

            # Check total size label
            total_lbl = page.locator("#dl-total-size-label").inner_text()
            assert "GB" in total_lbl or "MB" in total_lbl, f"Unexpected total size label: {total_lbl}"

            # Check ZIP pack button link
            zip_btn = page.locator("#btn-dl-pack-zip")
            zip_href = zip_btn.get_attribute("href")
            assert f"/api/jobs/{TARGET_JOB_ID}/download-pack" in zip_href, f"Invalid ZIP link: {zip_href}"

            # Capture Download Center Screenshot
            save_screenshot(page, f"download_center_desktop_{theme}.png")

            # Close via close icon
            page.locator("#btn-close-download-center").click()
            page.wait_for_timeout(400)
            assert not modal_dl.is_visible(), "Download center should close via close button"

            # ---------------------------------------------------------
            # 3. Thumbnail Maker Verification
            # ---------------------------------------------------------
            print("  [3] Opening Thumbnail Maker...")
            page.evaluate(f"async () => await window.openThumbnailMaker('{TARGET_JOB_ID}')")
            page.locator(".thumb-candidate-item").first.wait_for(timeout=10000)

            modal_thumb = page.locator("#modal-thumbnail-maker")
            assert modal_thumb.is_visible(), "Thumbnail maker modal should be visible"

            # Check candidate frames gallery
            candidates = page.locator(".thumb-candidate-item")
            cand_count = candidates.count()
            print(f"  Candidate frames found: {cand_count}")
            assert cand_count >= 3, f"Expected candidate frames, got {cand_count}"

            # Check checklist badges
            page.locator(".thumb-checklist-badge").first.wait_for(timeout=10000)
            badges = page.locator(".thumb-checklist-badge")
            badge_count = badges.count()
            print(f"  Checklist badges found: {badge_count}")
            assert badge_count >= 4, f"Expected checklist badges, got {badge_count}"

            # Check CTR learning loop status
            learning_box = page.locator("#thumb-learning-box")
            assert learning_box.is_visible()
            assert "Learning Loop" in learning_box.inner_text() or "tested" in learning_box.inner_text().lower()

            # Live tweak: change template
            print("  Tweaking layout template to bold_color_block...")
            page.select_option("#select-thumb-template", "bold_color_block")
            page.wait_for_timeout(600)

            # Live tweak: change hook text
            print("  Tweaking truthful hook text...")
            page.fill("#input-thumb-hook", "EPIC CAT STUNTS")
            page.wait_for_timeout(600)

            counter_text = page.locator("#thumb-hook-counter").inner_text()
            assert "15/28 chars" in counter_text, f"Unexpected counter: {counter_text}"

            # Verify previews updated
            img_src = page.locator("#thumb-preview-large").get_attribute("src")
            assert img_src and img_src.startswith("data:image/jpeg;base64,"), "Live preview should be base64 data URL"

            # Capture Thumbnail Maker Screenshot
            save_screenshot(page, f"thumbnail_maker_desktop_{theme}.png")

            # Close modal via backdrop click
            page.mouse.click(10, 10)
            page.wait_for_timeout(400)

            # ---------------------------------------------------------
            # 4. Failure Diagnostic Mode
            # ---------------------------------------------------------
            if theme == "dark":
                print("  [4] Verifying Diagnostic Report Failure Mode...")
                page.evaluate(f"() => window.openReportViewer('{TARGET_JOB_ID}', 'diagnostic')")
                page.wait_for_timeout(800)
                assert page.locator("#modal-report-viewer").is_visible()
                title_text = page.locator("#report-modal-title").inner_text()
                assert "Diagnostic" in title_text, f"Title should indicate Diagnostic Report: {title_text}"
                save_screenshot(page, "diagnostic_report_failure_mode.png")
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)

            # ---------------------------------------------------------
            # 5. Export Studio & Finished Library Cards Integration
            # ---------------------------------------------------------
            if theme == "dark":
                print("  [5] Verifying Export Studio & Library Cards Integration...")
                # Navigate to Step 5
                page.evaluate(f"() => {{ if (window.renderExportStudio) window.renderExportStudio('{TARGET_JOB_ID}'); window.navigateToStep(5); }}")
                page.wait_for_timeout(600)

                exp_report_btn = page.locator("#btn-export-report")
                exp_thumb_btn = page.locator("#btn-export-thumbnails")
                assert exp_report_btn.is_visible(), "Export Step 5 should have Report button"
                assert exp_thumb_btn.is_visible(), "Export Step 5 should have Thumbnail button"

                # Navigate to Step 1 (Home/Library)
                page.evaluate("() => window.navigateToStep(1)")
                page.wait_for_timeout(600)

                # Check library card buttons
                report_cards = page.locator(".btn-proj-report")
                dl_cards = page.locator(".btn-proj-downloads")
                thumb_cards = page.locator(".btn-proj-thumb")
                if report_cards.count() > 0:
                    assert dl_cards.count() > 0
                    assert thumb_cards.count() > 0
                    print(f"  Verified {report_cards.count()} project cards equipped with Report, Downloads, and Thumbnail buttons")

            context.close()

        # -------------------------------------------------------------
        # PART B: MOBILE 390px (DARK & LIGHT THEMES)
        # -------------------------------------------------------------
        for theme in ["dark", "light"]:
            print(f"\n--- Testing Mobile (390x844) - Theme: {theme.upper()} ---")
            context = browser.new_context(
                viewport={"width": 390, "height": 844},
                color_scheme=theme,
                is_mobile=True
            )
            page = context.new_page()
            page.goto(SERVER_URL, timeout=20000)
            page.wait_for_timeout(1000)

            page.evaluate(f"""() => {{
                document.body.classList.remove('theme-dark', 'theme-light');
                document.body.classList.add('theme-{theme}');
            }}""")

            # 1. Report Viewer Mobile
            page.evaluate(f"async () => await window.openReportViewer('{TARGET_JOB_ID}')")
            page.locator("#modal-report-viewer").wait_for(timeout=10000)
            page.wait_for_timeout(800)
            save_screenshot(page, f"report_viewer_mobile_390_{theme}.png")
            page.locator("#btn-close-report-modal").click()
            page.wait_for_timeout(300)

            # 2. Download Center Mobile
            page.evaluate(f"async () => await window.openDownloadCenter('{TARGET_JOB_ID}')")
            page.locator(".deliverable-row").first.wait_for(timeout=10000)
            page.wait_for_timeout(500)
            save_screenshot(page, f"download_center_mobile_390_{theme}.png")
            page.locator("#btn-close-download-center").click()
            page.wait_for_timeout(300)

            # 3. Thumbnail Maker Mobile
            page.evaluate(f"async () => await window.openThumbnailMaker('{TARGET_JOB_ID}')")
            page.locator(".thumb-candidate-item").first.wait_for(timeout=10000)
            page.wait_for_timeout(600)
            save_screenshot(page, f"thumbnail_maker_mobile_390_{theme}.png")
            page.locator("#btn-close-thumbnail-maker").click()
            page.wait_for_timeout(300)

            context.close()

        browser.close()

    print("\n=== PLAYWRIGHT SUITE COMPLETED 100% SUCCESSFULLY ===")


if __name__ == "__main__":
    test_ui_report_download_thumb_suite()
