"""
Capture Playwright screenshots of Step 3 (Edit) with new Feedback Loop controls.
Uses installed Google Chrome (channel="chrome", no driver download).
Captures:
1. Dark theme 1440px
2. Dark theme 390px
3. Light theme 1440px
4. Light theme 390px
"""

import os
import sys
import time
from playwright.sync_api import sync_playwright

def main():
    out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "analysis", "screenshots")
    os.makedirs(out_dir, exist_ok=True)
    
    print("[1/5] Launching Google Chrome via Playwright (channel='chrome')...")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception as e:
            print(f"Error launching chrome channel: {e}")
            sys.exit(1)

        # 1. Dark Desktop 1440px
        print("[2/5] Capturing Dark Desktop (1440px)...")
        ctx_dark_1440 = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx_dark_1440.new_page()
        page.goto("http://localhost:8000/", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        page.evaluate("() => { document.documentElement.setAttribute('data-theme', 'dark'); localStorage.setItem('theme', 'dark'); if (window.navigateToStep) window.navigateToStep(3); }")
        page.wait_for_timeout(1500)
        page.wait_for_selector("#inspector-feedback-section", timeout=5000)
        dark_1440_path = os.path.join(out_dir, "edit_step_dark_1440.png")
        page.screenshot(path=dark_1440_path)
        print(f"  -> Saved {dark_1440_path}")
        ctx_dark_1440.close()

        # 2. Dark Mobile 390px
        print("[3/5] Capturing Dark Mobile (390px)...")
        ctx_dark_390 = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        page = ctx_dark_390.new_page()
        page.goto("http://localhost:8000/", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        page.evaluate("() => { document.documentElement.setAttribute('data-theme', 'dark'); localStorage.setItem('theme', 'dark'); if (window.navigateToStep) window.navigateToStep(3); }")
        page.wait_for_timeout(1500)
        page.wait_for_selector("#inspector-feedback-section", timeout=5000)
        
        # Scroll feedback section into center view
        inspector = page.locator("#inspector-feedback-section")
        if inspector.count() > 0:
            inspector.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            
        dark_390_path = os.path.join(out_dir, "edit_step_dark_390.png")
        page.screenshot(path=dark_390_path)
        print(f"  -> Saved {dark_390_path}")
        ctx_dark_390.close()

        # 3. Light Desktop 1440px
        print("[4/5] Capturing Light Desktop (1440px)...")
        ctx_light_1440 = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx_light_1440.new_page()
        page.goto("http://localhost:8000/", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        page.evaluate("() => { document.documentElement.setAttribute('data-theme', 'light'); localStorage.setItem('theme', 'light'); if (window.navigateToStep) window.navigateToStep(3); }")
        page.wait_for_timeout(1500)
        page.wait_for_selector("#inspector-feedback-section", timeout=5000)
        
        light_1440_path = os.path.join(out_dir, "edit_step_light_1440.png")
        page.screenshot(path=light_1440_path)
        print(f"  -> Saved {light_1440_path}")
        ctx_light_1440.close()

        # 4. Light Mobile 390px
        print("[5/5] Capturing Light Mobile (390px)...")
        ctx_light_390 = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        page = ctx_light_390.new_page()
        page.goto("http://localhost:8000/", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        page.evaluate("() => { document.documentElement.setAttribute('data-theme', 'light'); localStorage.setItem('theme', 'light'); if (window.navigateToStep) window.navigateToStep(3); }")
        page.wait_for_timeout(1500)
        page.wait_for_selector("#inspector-feedback-section", timeout=5000)
        
        inspector = page.locator("#inspector-feedback-section")
        if inspector.count() > 0:
            inspector.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            
        light_390_path = os.path.join(out_dir, "edit_step_light_390.png")
        page.screenshot(path=light_390_path)
        print(f"  -> Saved {light_390_path}")
        ctx_light_390.close()

        browser.close()
        print("\nAll 4 screenshots successfully captured and verified!")

if __name__ == "__main__":
    main()
