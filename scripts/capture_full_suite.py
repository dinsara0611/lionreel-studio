import os
import sys
import time
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8000"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def capture_suite(stage="before"):
    out_dir = os.path.join(BASE_DIR, "analysis", "screenshots", stage)
    os.makedirs(out_dir, exist_ok=True)
    
    viewports = [("1440", 1440, 900), ("390", 390, 844)]
    themes = ["dark", "light"]
    
    print(f"=== Starting Screenshot Suite: {stage.upper()} ===")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        
        for th in themes:
            for vp_name, w, h in viewports:
                print(f"Capturing {stage} -> Theme: {th}, Viewport: {vp_name}px ({w}x{h})...")
                context = browser.new_context(viewport={"width": w, "height": h})
                page = context.new_page()
                
                # Navigate
                theme_param = "?ui_theme=cutting_room" if stage == "after" else "?ui_theme=classic"
                page.goto(f"{BASE_URL}/{theme_param}", wait_until="domcontentloaded")
                page.wait_for_timeout(800)
                
                # Apply theme
                page.evaluate("""(args) => {
                    const th = args.th;
                    const st = args.st;
                    if (st === 'after') {
                        document.documentElement.setAttribute('data-ui-theme', 'cutting_room');
                    } else {
                        document.documentElement.setAttribute('data-ui-theme', 'classic');
                    }
                    document.documentElement.setAttribute('data-theme', th);
                    document.documentElement.style.colorScheme = th;
                    if (th === 'light') {
                        document.documentElement.classList.add('light-mode');
                        document.documentElement.classList.remove('dark-mode');
                        document.body.classList.add('light-mode');
                        document.body.classList.remove('dark-mode');
                    } else {
                        document.documentElement.classList.add('dark-mode');
                        document.documentElement.classList.remove('light-mode');
                        document.body.classList.add('dark-mode');
                        document.body.classList.remove('light-mode');
                    }
                    localStorage.setItem('lionreel_theme', th);
                }""", {"th": th, "st": stage})
                page.wait_for_timeout(300)
                
                prefix = f"{stage}_{th}_{vp_name}"
                
                # 1. CREATE SCREEN (Step 1)
                page.evaluate("() => { if (window.navigateToStep) window.navigateToStep(1); }")
                page.wait_for_timeout(400)
                page.screenshot(path=os.path.join(out_dir, f"{prefix}_create.png"))
                
                # 2. SOURCES SCREEN (Step 2)
                page.evaluate("() => { if (window.navigateToStep) window.navigateToStep(2); }")
                page.wait_for_timeout(400)
                page.screenshot(path=os.path.join(out_dir, f"{prefix}_sources.png"))
                
                # 3. EDIT SCREEN (Step 3)
                page.evaluate("() => { if (window.navigateToStep) window.navigateToStep(3); }")
                page.wait_for_timeout(400)
                page.screenshot(path=os.path.join(out_dir, f"{prefix}_edit.png"))
                
                # 4. RENDER - RUNNING
                page.evaluate("""() => {
                    if (window.navigateToStep) window.navigateToStep(4);
                    const card = document.getElementById('render-progress-card') || document.getElementById('view-render');
                    const badge = document.getElementById('render-status-badge') || document.querySelector('.render-badge');
                    if (badge) { badge.innerText = 'STAGE 6/8 RENDERING'; badge.className = 'badge badge-emerald'; }
                    const bar = document.getElementById('render-progress-fill') || document.getElementById('progress-bar-fill');
                    if (bar) bar.style.width = '68%';
                    const txt = document.getElementById('render-status-text') || document.getElementById('progress-status-desc');
                    if (txt) txt.innerText = 'Color grading and smart-cropping clip 16 of 24...';
                }""")
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(out_dir, f"{prefix}_render_running.png"))
                
                # 5. RENDER - WAITING
                page.evaluate("""() => {
                    const badge = document.getElementById('render-status-badge') || document.querySelector('.render-badge');
                    if (badge) { badge.innerText = 'WAITING FOR CLIPS'; badge.className = 'badge badge-amber'; }
                    const txt = document.getElementById('render-status-text') || document.getElementById('progress-status-desc');
                    if (txt) txt.innerText = 'Harvesting fresh candidates to reach 20:00 duration contract...';
                }""")
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(out_dir, f"{prefix}_render_waiting.png"))
                
                # 6. RENDER - FAILED
                page.evaluate("""() => {
                    const badge = document.getElementById('render-status-badge') || document.querySelector('.render-badge');
                    if (badge) { badge.innerText = 'RENDER HALTED'; badge.className = 'badge badge-rose'; }
                    const txt = document.getElementById('render-status-text') || document.getElementById('progress-status-desc');
                    if (txt) txt.innerText = 'Stream defect detected: 3 black frames encountered in source clip.';
                }""")
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(out_dir, f"{prefix}_render_failed.png"))
                
                # 7. RENDER - SUCCESS
                page.evaluate("""() => {
                    const badge = document.getElementById('render-status-badge') || document.querySelector('.render-badge');
                    if (badge) { badge.innerText = 'RENDER COMPLETE'; badge.className = 'badge badge-emerald'; }
                    const bar = document.getElementById('render-progress-fill') || document.getElementById('progress-bar-fill');
                    if (bar) bar.style.width = '100%';
                    const txt = document.getElementById('render-status-text') || document.getElementById('progress-status-desc');
                    if (txt) txt.innerText = 'Master MP4 rendered successfully. Quality verified.';
                }""")
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(out_dir, f"{prefix}_render_success.png"))
                
                # 8. EXPORT SCREEN (Step 5 Publish Tab)
                page.evaluate("() => { if (window.navigateToStep) window.navigateToStep(5); }")
                page.wait_for_timeout(500)
                page.screenshot(path=os.path.join(out_dir, f"{prefix}_export.png"))
                
                # 9. LIBRARY (Step 5 Library Tab / Grid)
                page.evaluate("""() => {
                    const libTab = document.getElementById('tab-nav-library');
                    if (libTab) libTab.click();
                }""")
                page.wait_for_timeout(400)
                page.screenshot(path=os.path.join(out_dir, f"{prefix}_library.png"))
                
                # 10. REPORT POPUP
                page.evaluate("""() => {
                    if (window.openReportViewer) window.openReportViewer('lionreel_cat_20261016_065802_502f5dd4');
                    else {
                        const m = document.getElementById('modal-report-viewer');
                        if (m) m.style.display = 'flex';
                    }
                }""")
                page.wait_for_timeout(600)
                page.screenshot(path=os.path.join(out_dir, f"{prefix}_report_popup.png"))
                # Close report popup
                page.evaluate("""() => {
                    const m = document.getElementById('modal-report-viewer');
                    if (m) m.style.display = 'none';
                    const d = document.getElementById('dialog-report-viewer');
                    if (d && d.close) d.close();
                }""")
                page.wait_for_timeout(200)
                
                # 11. DOWNLOAD CENTER
                page.evaluate("""() => {
                    if (window.openDownloadCenter) window.openDownloadCenter('lionreel_cat_20261016_065802_502f5dd4');
                    else {
                        const m = document.getElementById('modal-download-center');
                        if (m) m.style.display = 'flex';
                    }
                }""")
                page.wait_for_timeout(500)
                page.screenshot(path=os.path.join(out_dir, f"{prefix}_download_center.png"))
                # Close download center
                page.evaluate("""() => {
                    const m = document.getElementById('modal-download-center');
                    if (m) m.style.display = 'none';
                    const d = document.getElementById('dialog-download-center');
                    if (d && d.close) d.close();
                }""")
                page.wait_for_timeout(200)
                
                # 12. THUMBNAIL MAKER
                page.evaluate("""() => {
                    if (window.openThumbnailMaker) window.openThumbnailMaker('lionreel_cat_20261016_065802_502f5dd4');
                    else {
                        const m = document.getElementById('modal-thumbnail-maker');
                        if (m) m.style.display = 'flex';
                    }
                }""")
                page.wait_for_timeout(500)
                page.screenshot(path=os.path.join(out_dir, f"{prefix}_thumbnail_maker.png"))
                # Close thumbnail maker
                page.evaluate("""() => {
                    const m = document.getElementById('modal-thumbnail-maker');
                    if (m) m.style.display = 'none';
                    const d = document.getElementById('dialog-thumbnail-maker');
                    if (d && d.close) d.close();
                }""")
                page.wait_for_timeout(200)
                
                # 13. LOADING SCREEN
                page.evaluate("""() => {
                    const ls = document.getElementById('cutting-room-startup') || document.getElementById('cutting-room-loader') || document.getElementById('app-loading-screen');
                    if (ls) {
                        ls.style.display = 'flex';
                        ls.style.visibility = 'visible';
                        ls.style.opacity = '1';
                        ls.classList.remove('hidden');
                    }
                }""")
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(out_dir, f"{prefix}_loading_screen.png"))
                
                context.close()
                
        browser.close()
        
    print(f"=== Capture suite for '{stage}' complete in: {out_dir} ===")

if __name__ == "__main__":
    stage_arg = sys.argv[1] if len(sys.argv) > 1 else "before"
    capture_suite(stage_arg)
