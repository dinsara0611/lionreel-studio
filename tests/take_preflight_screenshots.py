import os
import sys
import time
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = os.path.join(r"C:\Users\dinsa\.gemini\antigravity-ide\brain\d8fabd9c-0392-4de8-ac4f-0a350499ad2d", "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def take_screenshots():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        
        # Test configurations: (width, height, is_dark, name)
        configs = [
            (1440, 900, True, "preflight_dialog_1440px_dark.png"),
            (1440, 900, False, "preflight_dialog_1440px_light.png"),
            (390, 844, True, "preflight_dialog_390px_dark.png"),
            (390, 844, False, "preflight_dialog_390px_light.png"),
        ]

        for w, h, is_dark, fname in configs:
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto("http://127.0.0.1:8100/", wait_until="domcontentloaded")
            
            # Set theme
            if is_dark:
                page.evaluate("() => { if (window.applyTheme) window.applyTheme('dark'); else { document.documentElement.setAttribute('data-theme', 'dark'); document.body.classList.remove('light-mode'); } }")
            else:
                page.evaluate("() => { if (window.applyTheme) window.applyTheme('light'); else { document.documentElement.setAttribute('data-theme', 'light'); document.body.classList.add('light-mode'); } }")

            # Open preflight modal via app helper or directly trigger check
            page.evaluate("""() => {
                const ls = document.getElementById('app-loading-screen');
                if (ls) ls.style.display = 'none';
                if (window.showPreflightModal) {
                    window.showPreflightModal({
                        animal: 'cat',
                        format: 'long',
                        needed_clips: 100,
                        verified_windows: 8,
                        usable_sources: 4,
                        min_sources_needed: 34,
                        usable_sources_text: '4 of 34 needed',
                        vertical_sources: 7,
                        vertical_verified: 6,
                        vertical_sources_text: '7 (6 verified windows yet)',
                        pass_rate_text: '2 of 28 passed',
                        capacity: 8,
                        can_supply_target: false,
                        warning: 'This pool can supply at most 8 clips. 100 clips need at least 34 sources.',
                        estimated_harvest_time_text: '~26275s - 42697s (estimate)',
                        last_harvest_text: 'Last harvest: 05:02:53, 3 sources scanned, 2 windows verified',
                        suggestion_text: '',
                        options: ['set_n_clips', 'harvest_first', 'start_anyway']
                    }, () => {});
                } else {
                    const m = document.getElementById('modal-preflight');
                    if (m) m.style.display = 'flex';
                }
            }""")
            time.sleep(0.5)

            out_path = os.path.join(SCREENSHOTS_DIR, fname)
            page.screenshot(path=out_path, full_page=False)
            print(f"Saved {fname} ({w}x{h}, dark={is_dark}) -> {out_path}")

        # Also capture one with K=0 showing suggestion banner and hidden Start anyway
        page_k0 = browser.new_page(viewport={"width": 1440, "height": 900})
        page_k0.goto("http://127.0.0.1:8100/", wait_until="domcontentloaded")
        page_k0.evaluate("() => { document.documentElement.setAttribute('data-theme', 'dark'); }")
        page_k0.evaluate("""() => {
            const ls = document.getElementById('app-loading-screen');
            if (ls) ls.style.display = 'none';
            if (window.showPreflightModal) {
                window.showPreflightModal({
                    animal: 'cat',
                    format: 'long',
                    needed_clips: 100,
                    verified_windows: 0,
                    usable_sources: 0,
                    min_sources_needed: 34,
                    usable_sources_text: '0 of 34 needed',
                    vertical_sources: 7,
                    vertical_verified: 0,
                    vertical_sources_text: '7 (0 verified windows yet)',
                    pass_rate_text: '0 of 15 passed',
                    capacity: 0,
                    can_supply_target: false,
                    warning: 'This pool can supply at most 0 clips. 100 clips need at least 34 sources.',
                    estimated_harvest_time_text: 'Estimate: not enough data yet',
                    last_harvest_text: 'Last harvest: 05:02:53, 3 sources scanned, 2 windows verified',
                    suggestion_text: 'Try a short video of 6 clips after the first harvest',
                    options: ['harvest_first', 'cancel']
                }, () => {});
            }
        }""")
        time.sleep(0.5)
        k0_path = os.path.join(SCREENSHOTS_DIR, "preflight_dialog_k0_suggestion_1440px.png")
        page_k0.screenshot(path=k0_path, full_page=False)
        print(f"Saved K=0 screenshot -> {k0_path}")

        # Also capture live harvest progress view state
        page_prog = browser.new_page(viewport={"width": 1440, "height": 900})
        page_prog.goto("http://127.0.0.1:8100/", wait_until="domcontentloaded")
        page_prog.evaluate("() => { document.documentElement.setAttribute('data-theme', 'dark'); }")
        page_prog.evaluate("""() => {
            const ls = document.getElementById('app-loading-screen');
            if (ls) ls.style.display = 'none';
            if (window.showPreflightModal) {
                window.showPreflightModal({
                    animal: 'cat',
                    format: 'long',
                    needed_clips: 100,
                    verified_windows: 8,
                    usable_sources: 4,
                    min_sources_needed: 34,
                    usable_sources_text: '4 of 34 needed',
                    vertical_sources: 7,
                    vertical_verified: 6,
                    vertical_sources_text: '7 (6 verified windows yet)',
                    pass_rate_text: '2 of 28 passed',
                    capacity: 8,
                    can_supply_target: false,
                    warning: 'This pool can supply at most 8 clips. 100 clips need at least 34 sources.',
                    estimated_harvest_time_text: '~26275s - 42697s (estimate)',
                    last_harvest_text: 'Last harvest: 05:02:53, 3 sources scanned, 2 windows verified',
                    suggestion_text: '',
                    options: ['set_n_clips', 'harvest_first', 'start_anyway']
                }, () => {});
                
                // Show harvest progress view
                const pb = document.getElementById('preflight-harvest-progress');
                if (pb) pb.style.display = 'block';
                document.getElementById('preflight-harvest-current-source').textContent = 'cache_KWA1jfqvZmg.mp4';
                document.getElementById('preflight-harvest-scanned').textContent = '3 of 11';
                document.getElementById('preflight-harvest-analyzed').textContent = '28';
                document.getElementById('preflight-harvest-verified').textContent = '2';
                document.getElementById('preflight-harvest-growth').textContent = '+0.2 / min';
                document.getElementById('preflight-harvest-pbar').style.width = '25%';
                document.getElementById('preflight-harvest-rejects').innerHTML = '<span>Rejects: LOW_PET_PRESENCE (7) • PET_NOT_CENTERABLE (9)</span>';
            }
        }""")
        time.sleep(0.5)
        prog_path = os.path.join(SCREENSHOTS_DIR, "preflight_harvest_progress_1440px.png")
        page_prog.screenshot(path=prog_path, full_page=False)
        print(f"Saved harvest progress screenshot -> {prog_path}")

        browser.close()

if __name__ == "__main__":
    take_screenshots()
