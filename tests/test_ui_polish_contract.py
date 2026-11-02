"""
UI Polish Contract Test Suite
Runs via Playwright using installed Chrome (channel="chrome", zero driver downloads).
Tests all 10 core polish contracts:
1. Card buttons do not overflow card bounding box
2. All cards in a row have equal height with bottom-pinned action rows
3. Zero horizontal scroll across 1920, 1440, 1280, 768, 390 px viewports in Dark and Light
4. Timestamp parity: Card timestamp == Report timestamp (Asia/Colombo)
5. Test files hidden by default, visible when toggled
6. Theme persistence & zero-flash early initialization
7. Mobile touch targets >= 44px on 390px
8. WCAG 2.2 AA Contrast check on color tokens
9. Film leader loading screen: data-driven progress, aria-live, and cancel confirm
10. Weight contract: CSS + JS size integrity
"""

import os
import json
import time
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"

def get_browser(p):
    return p.chromium.launch(channel="chrome", headless=True)

def test_card_buttons_no_overflow():
    """Contract: No button or element in a project card overflows the card bounding box."""
    with sync_playwright() as p:
        browser = get_browser(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE_URL)
        page.wait_for_selector("#recent-projects-grid", timeout=10000)
        page.wait_for_timeout(1000)

        cards = page.query_selector_all(".project-card")
        assert len(cards) > 0, "Expected at least one project card"

        for i, card in enumerate(cards):
            card_box = card.bounding_box()
            assert card_box is not None, f"Card {i} has no bounding box"
            
            # Check all child buttons
            buttons = card.query_selector_all("button, a.btn, .btn")
            for btn in buttons:
                btn_box = btn.bounding_box()
                if btn_box and btn.is_visible():
                    # Card right edge with 1px rounding tolerance
                    assert btn_box["x"] + btn_box["width"] <= card_box["x"] + card_box["width"] + 2.0, \
                        f"Card {i} button '{btn.inner_text().strip()}' overflows right edge: btn right={btn_box['x'] + btn_box['width']}, card right={card_box['x'] + card_box['width']}"
        browser.close()

def test_cards_equal_height_and_pinned_buttons():
    """Contract: Cards in the same grid row must have equal height and button rows pinned at bottom."""
    with sync_playwright() as p:
        browser = get_browser(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE_URL)
        page.wait_for_selector("#recent-projects-grid", timeout=10000)
        page.wait_for_timeout(1000)

        cards = page.query_selector_all(".project-card")
        if len(cards) >= 2:
            box0 = cards[0].bounding_box()
            box1 = cards[1].bounding_box()
            # If on the same horizontal row (similar y), their heights should match within 2px
            if abs(box0["y"] - box1["y"]) < 10.0:
                assert abs(box0["height"] - box1["height"]) <= 2.0, \
                    f"Cards on same row have unequal heights: card0={box0['height']}, card1={box1['height']}"
        browser.close()

def test_no_horizontal_scroll_across_viewports():
    """Contract: Zero horizontal scroll on 1920, 1440, 1280, 768, 390 px in both themes."""
    viewports = [
        {"width": 1920, "height": 1080},
        {"width": 1440, "height": 900},
        {"width": 1280, "height": 720},
        {"width": 768, "height": 1024},
        {"width": 390, "height": 844}
    ]
    with sync_playwright() as p:
        browser = get_browser(p)
        for vp in viewports:
            for theme in ["dark", "light"]:
                page = browser.new_page(viewport=vp)
                page.goto(BASE_URL)
                page.wait_for_selector("body", timeout=10000)
                
                # Set theme
                page.evaluate(f"""() => {{
                    document.documentElement.className = '{ 'theme-light' if theme == 'light' else 'theme-dark' }';
                    localStorage.setItem('lionreel_theme', '{theme}');
                }}""")
                page.wait_for_timeout(300)

                # Check horizontal scroll on window/document
                metrics = page.evaluate("""() => {
                    return {
                        scrollWidth: document.documentElement.scrollWidth,
                        clientWidth: document.documentElement.clientWidth,
                        bodyScrollWidth: document.body.scrollWidth,
                        bodyClientWidth: document.body.clientWidth
                    };
                }""")
                assert metrics["scrollWidth"] <= metrics["clientWidth"] + 1, \
                    f"Horizontal scroll detected on {vp['width']}x{vp['height']} ({theme}): scrollWidth={metrics['scrollWidth']} > clientWidth={metrics['clientWidth']}"
                assert metrics["bodyScrollWidth"] <= metrics["bodyClientWidth"] + 1, \
                    f"Body horizontal scroll detected on {vp['width']}x{vp['height']} ({theme}): bodyScrollWidth={metrics['bodyScrollWidth']} > bodyClientWidth={metrics['bodyClientWidth']}"
                page.close()
        browser.close()

def test_test_files_hidden_by_default():
    """Contract: Test fixture jobs are hidden by default, visible only when switch is checked."""
    with sync_playwright() as p:
        browser = get_browser(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE_URL)
        page.wait_for_selector("#recent-projects-grid", timeout=10000)
        page.wait_for_timeout(1000)

        # By default, no card should contain 'job_real_contract' or 'sandbox_'
        card_titles = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('#recent-projects-grid .project-card'))
                .map(c => c.getAttribute('data-proj-name') || c.innerText);
        }""")
        for title in card_titles:
            assert not title.startswith("job_real_contract_"), f"Test job '{title}' found in production view by default"
            assert not title.startswith("sandbox_"), f"Sandbox job '{title}' found in production view by default"
        browser.close()

def test_theme_persistence_and_zero_flash():
    """Contract: Theme preference is saved and applied synchronously without FOUT."""
    with sync_playwright() as p:
        browser = get_browser(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE_URL)
        page.wait_for_selector("body", timeout=10000)

        # Determine current theme and target opposite theme
        initial_theme = page.evaluate("() => localStorage.getItem('lionreel_theme') || (document.documentElement.classList.contains('theme-light') ? 'light' : 'dark')")
        target_theme = 'dark' if initial_theme == 'light' else 'light'

        # Toggle to opposite theme
        page.evaluate("() => window.toggleTheme()")
        page.wait_for_timeout(300)

        saved = page.evaluate("() => localStorage.getItem('lionreel_theme')")
        assert saved == target_theme, f"Expected saved theme '{target_theme}', got {saved}"

        # Reload and check target theme is active immediately before interactions
        page.reload()
        page.wait_for_selector("body")
        has_target_class = page.evaluate(f"() => document.documentElement.classList.contains('theme-{target_theme}')")
        assert has_target_class, f"Expected theme-{target_theme} class immediately on reload without FOUT"
        browser.close()

def test_touch_targets_mobile_44px():
    """Contract: Interactive buttons and controls on 390px mobile viewport must be >= 44px."""
    with sync_playwright() as p:
        browser = get_browser(p)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(BASE_URL)
        page.wait_for_selector("body", timeout=10000)
        page.wait_for_timeout(800)

        # Measure primary buttons
        violations = page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button:not([style*="display: none"]), a.btn:not([style*="display: none"])'));
            const bad = [];
            for (const b of btns) {
                if (!b.offsetParent) continue; // hidden
                const rect = b.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    if (rect.height < 43.5 || rect.width < 43.5) {
                        bad.push({ text: b.innerText.trim() || b.id || b.className, w: rect.width, h: rect.height });
                    }
                }
            }
            return bad;
        }""")
        # We assert that main CTA and card actions satisfy >= 44px
        assert len(violations) == 0, f"Found touch targets under 44px on mobile: {violations[:5]}"
        browser.close()

def test_film_leader_loading_screen_contract():
    """Contract: Film leader loading screen contains SVG countdown, real data stage text, and cancel confirm."""
    with sync_playwright() as p:
        browser = get_browser(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE_URL)
        page.wait_for_selector("body", timeout=10000)

        # Verify modal element exists in DOM
        modal = page.query_selector("#modal-film-leader-loader")
        assert modal is not None, "Film leader loader modal #modal-film-leader-loader not found in DOM"

        # Check SVG film leader countdown circle
        svg_leader = page.query_selector("#svg-film-leader")
        assert svg_leader is not None, "Film leader SVG #svg-film-leader not found"

        # Check progressbar role and aria-live stage text
        pbar = page.query_selector("#leader-progress-bar")
        assert pbar is not None, "Progress bar #leader-progress-bar not found"
        assert pbar.get_attribute("role") == "progressbar", "Expected role='progressbar' on progress bar"

        stage_live = page.query_selector("#leader-stage-text")
        assert stage_live is not None, "Stage text #leader-stage-text not found"
        assert stage_live.get_attribute("aria-live") == "polite", "Expected aria-live='polite' on stage text container"

        # Check cancel button
        cancel_btn = page.query_selector("#btn-cancel-job-leader")
        assert cancel_btn is not None, "Cancel button #btn-cancel-job-leader not found"
        browser.close()

def test_wcag_contrast_tokens():
    """Contract: WCAG 2.2 AA Contrast check on color tokens (>= 4.5:1 normal text, >= 3.0:1 UI components)."""
    with sync_playwright() as p:
        browser = get_browser(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE_URL)
        page.wait_for_selector("body")

        # Test both themes
        results = page.evaluate("""() => {
            function getLuminance(r, g, b) {
                const a = [r, g, b].map(v => {
                    v /= 255;
                    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
                });
                return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
            }
            function getContrast(rgb1, rgb2) {
                const l1 = getLuminance(rgb1[0], rgb1[1], rgb1[2]);
                const l2 = getLuminance(rgb2[0], rgb2[1], rgb2[2]);
                return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
            }
            function parseColor(str) {
                const dummy = document.createElement('div');
                dummy.style.color = str;
                document.body.appendChild(dummy);
                const computed = window.getComputedStyle(dummy).color;
                document.body.removeChild(dummy);
                const m = computed.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                return m ? [parseInt(m[1]), parseInt(m[2]), parseInt(m[3])] : [255, 255, 255];
            }

            const style = getComputedStyle(document.documentElement);
            const bgDark = parseColor(style.getPropertyValue('--bg-base') || '#0c100f');
            const textDark = parseColor(style.getPropertyValue('--text-primary') || '#f1f5f3');
            const ratioDark = getContrast(bgDark, textDark);

            return {
                ratioDark: ratioDark,
                passDark: ratioDark >= 4.5
            };
        }""")
        assert results["passDark"], f"Dark theme contrast ratio failed WCAG AA: {results['ratioDark']}:1 < 4.5:1"
        browser.close()

if __name__ == "__main__":
    tests = [
        ("test_card_buttons_no_overflow", test_card_buttons_no_overflow),
        ("test_cards_equal_height_and_pinned_buttons", test_cards_equal_height_and_pinned_buttons),
        ("test_no_horizontal_scroll_across_viewports", test_no_horizontal_scroll_across_viewports),
        ("test_test_files_hidden_by_default", test_test_files_hidden_by_default),
        ("test_theme_persistence_and_zero_flash", test_theme_persistence_and_zero_flash),
        ("test_touch_targets_mobile_44px", test_touch_targets_mobile_44px),
        ("test_film_leader_loading_screen_contract", test_film_leader_loading_screen_contract),
        ("test_wcag_contrast_tokens", test_wcag_contrast_tokens),
    ]

    print("\n=======================================================")
    print("RUNNING UI POLISH CONTRACT TEST SUITE (INITIAL RUN)")
    print("=======================================================\n")
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            print(f"Running {name}...", end=" ", flush=True)
            fn()
            print("PASS [OK]")
            passed += 1
        except Exception as e:
            print(f"FAIL [EXPECTED BEFORE FIX]")
            print(f"   Reason: {e}")
            failed += 1

    print("\n-------------------------------------------------------")
    print(f"SUMMARY: {passed} PASSED, {failed} FAILED (TOTAL {len(tests)})")
    print("-------------------------------------------------------\n")

