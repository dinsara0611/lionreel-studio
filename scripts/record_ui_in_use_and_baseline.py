import os
import sys
import json
import time
from urllib.parse import urlparse

# Ensure .venv site packages are available
venv_site = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".venv", "Lib", "site-packages")
if os.path.exists(venv_site) and venv_site not in sys.path:
    sys.path.insert(0, venv_site)

from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8000"
JOB_ID = "lionreel_cat_20261010_020004_49dfa336"
SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "screenshots", "baseline")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

recorded_urls = set()

def record_request(request):
    recorded_urls.add(request.url)

def run():
    print(f"[1/4] Starting Playwright with channel='chrome' against {BASE_URL}...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        
        viewports = [
            ("1440", 1440, 900),
            ("390", 390, 844)
        ]
        
        themes = ["dark", "light"]
        
        for vp_name, width, height in viewports:
            for theme in themes:
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                page.on("request", record_request)
                
                # Navigate to home
                page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
                page.wait_for_timeout(1000)
                
                # Apply theme
                page.evaluate(f"""(th) => {{
                    document.documentElement.setAttribute('data-theme', th);
                    if (th === 'light') {{
                        document.documentElement.classList.add('light-mode');
                        document.documentElement.classList.remove('dark-mode');
                    }} else {{
                        document.documentElement.classList.add('dark-mode');
                        document.documentElement.classList.remove('light-mode');
                    }}
                    localStorage.setItem('lionreel_theme', th);
                }}""", theme)
                page.wait_for_timeout(400)
                
                # Ensure job_id is set
                page.evaluate(f"""(jid) => {{
                    if (window.state) window.state.currentJobId = jid;
                }}""", JOB_ID)
                
                # STEP 1: CREATE / DASHBOARD
                page.evaluate("() => { if (typeof navigateToStep === 'function') navigateToStep(1); }")
                page.wait_for_timeout(500)
                shot_1 = os.path.join(SCREENSHOTS_DIR, f"baseline_step1_create_{vp_name}_{theme}.png")
                page.screenshot(path=shot_1, full_page=False)
                print(f"  -> Captured {os.path.basename(shot_1)}")
                
                # STEP 2: SOURCES
                page.evaluate("() => { if (typeof navigateToStep === 'function') navigateToStep(2); }")
                page.wait_for_timeout(700)
                shot_2 = os.path.join(SCREENSHOTS_DIR, f"baseline_step2_sources_{vp_name}_{theme}.png")
                page.screenshot(path=shot_2, full_page=False)
                print(f"  -> Captured {os.path.basename(shot_2)}")
                
                # STEP 3: EDIT
                page.evaluate("() => { if (typeof navigateToStep === 'function') navigateToStep(3); }")
                page.wait_for_timeout(1000)
                try:
                    page.wait_for_selector(".timeline-clip-card", timeout=5000)
                except Exception:
                    pass
                shot_3 = os.path.join(SCREENSHOTS_DIR, f"baseline_step3_edit_{vp_name}_{theme}.png")
                page.screenshot(path=shot_3, full_page=False)
                print(f"  -> Captured {os.path.basename(shot_3)}")
                
                # STEP 3 MODAL: SWAP FROM BANK (only for 1440)
                if vp_name == "1440":
                    swap_btn = page.query_selector("#btn-editor-replace-clip")
                    if swap_btn and swap_btn.is_visible():
                        swap_btn.click()
                        page.wait_for_timeout(600)
                        shot_swap = os.path.join(SCREENSHOTS_DIR, f"baseline_step3_modal_swap_{vp_name}_{theme}.png")
                        page.screenshot(path=shot_swap, full_page=False)
                        print(f"  -> Captured {os.path.basename(shot_swap)}")
                        # Close modal
                        page.evaluate("() => { const m = document.getElementById('modal-replace-clip'); if (m) m.style.display = 'none'; }")
                        page.wait_for_timeout(300)
                
                # STEP 4: RENDER
                page.evaluate("() => { if (typeof navigateToStep === 'function') navigateToStep(4); }")
                page.wait_for_timeout(600)
                shot_4 = os.path.join(SCREENSHOTS_DIR, f"baseline_step4_render_{vp_name}_{theme}.png")
                page.screenshot(path=shot_4, full_page=False)
                print(f"  -> Captured {os.path.basename(shot_4)}")
                
                # STEP 5: EXPORT
                page.evaluate("() => { if (typeof navigateToStep === 'function') navigateToStep(5); }")
                page.wait_for_timeout(700)
                shot_5 = os.path.join(SCREENSHOTS_DIR, f"baseline_step5_export_{vp_name}_{theme}.png")
                page.screenshot(path=shot_5, full_page=False)
                print(f"  -> Captured {os.path.basename(shot_5)}")
                
                context.close()
                
        browser.close()

    print(f"\n[2/4] Total unique URLs recorded by browser: {len(recorded_urls)}")
    
    # Map URLs to files on disk
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mapped_files = {}
    
    for u in sorted(recorded_urls):
        p = urlparse(u).path
        if p == "/":
            disk_rel = "gui/index.html"
        elif p.startswith("/api/"):
            # API endpoint, handled by web_server.py
            disk_rel = "web_server.py (API: " + p + ")"
        elif p.startswith("/work/"):
            disk_rel = p.lstrip("/")
        elif p.startswith("/finished/"):
            disk_rel = p.lstrip("/")
        elif p.startswith("/raw/"):
            disk_rel = p.lstrip("/")
        else:
            # check in gui/
            cand = os.path.join("gui", p.lstrip("/"))
            if os.path.exists(os.path.join(base_dir, cand)):
                disk_rel = cand
            else:
                disk_rel = p.lstrip("/")
                
        abs_p = os.path.join(base_dir, disk_rel)
        exists = os.path.exists(abs_p) if not disk_rel.startswith("web_server.py") else True
        sz = os.path.getsize(abs_p) if (exists and not disk_rel.startswith("web_server.py")) else 0
        
        mapped_files[u] = {
            "path": p,
            "disk_file": disk_rel,
            "exists": exists,
            "size": sz
        }

    # Static parsing of HTML, CSS, JS
    print("[3/4] Parsing static assets referenced inside gui/ files...")
    static_ui_files = set()
    for root, _, files in os.walk(os.path.join(base_dir, "gui")):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), base_dir).replace('\\', '/')
            static_ui_files.add(rel)

    ui_in_use_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_urls_recorded": len(recorded_urls),
        "recorded_urls": list(sorted(recorded_urls)),
        "mapped_files": mapped_files,
        "static_gui_files": list(sorted(static_ui_files))
    }
    
    out_json = os.path.join(base_dir, "analysis", "ui_in_use.json")
    with open(out_json, "w", encoding="utf-8") as f_out:
        json.dump(ui_in_use_data, f_out, indent=2)
        
    print(f"[4/4] Done! UI in use recorded and saved to: {out_json}")

if __name__ == "__main__":
    run()
