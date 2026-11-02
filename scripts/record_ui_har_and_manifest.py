import os
import sys
import time
import json
import hashlib
import re
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAR_PATH = os.path.join(BASE_DIR, "analysis", "ui_network_trace.har")
MANIFEST_PATH = os.path.join(BASE_DIR, "ui_freeze_manifest.json")

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def run():
    print("=== RECORDING HAR NETWORK TRACE ACROSS LIVE APP ===")
    loaded_urls = set()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_har_path=HAR_PATH
        )
        page = context.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        page.on("request", lambda req: loaded_urls.add(req.url))
        
        # 1. Dashboard / Library
        page.goto("http://127.0.0.1:8000/")
        page.wait_for_load_state("domcontentloaded")
        time.sleep(1.0)
        
        # 2. Wizard / Create
        page.evaluate("""() => {
            if (typeof navigateToStep === 'function') navigateToStep(2);
        }""")
        time.sleep(0.8)
        
        # 3. Sources / Editor
        page.evaluate("""() => {
            if (typeof navigateToStep === 'function') navigateToStep(3);
        }""")
        time.sleep(0.8)
        
        # 4. Render
        page.evaluate("""() => {
            if (typeof navigateToStep === 'function') navigateToStep(4);
        }""")
        time.sleep(0.8)
        
        # 5. Export
        page.evaluate("""() => {
            if (typeof navigateToStep === 'function') navigateToStep(5);
        }""")
        time.sleep(0.8)
        
        # 6. Safe Clean-Up Modal
        page.evaluate("""() => {
            if (typeof openSafeCleanupModal === 'function') {
                openSafeCleanupModal();
            } else {
                const btn = document.getElementById('btn-open-safe-cleanup');
                if (btn) btn.click();
            }
        }""")
        time.sleep(1.2)
        
        # 7. Light theme toggle
        page.evaluate("applyTheme('light');")
        time.sleep(0.5)
        
        # 8. Dark theme toggle
        page.evaluate("applyTheme('dark');")
        time.sleep(0.5)
        
        context.close()
        browser.close()

    print(f"HAR successfully written to: {HAR_PATH}")
    print(f"Recorded {len(loaded_urls)} requested URLs.")
    for u in sorted(loaded_urls):
        print(f"  {u}")

    # Map URLs to files on disk and find referenced assets in HTML/CSS/JS
    ui_files = set()
    gui_dir = os.path.join(BASE_DIR, "gui")
    
    for u in loaded_urls:
        if "127.0.0.1:8000" in u or "localhost:8000" in u:
            # Parse path from URL
            path_part = u.split("8000", 1)[-1].split("?")[0].lstrip("/")
            if not path_part or path_part == "":
                path_part = "index.html"
            local_cand = os.path.join(gui_dir, path_part)
            if os.path.isfile(local_cand):
                ui_files.add(os.path.relpath(local_cand, BASE_DIR).replace("\\", "/"))

    # Also inspect HTML, CSS, JS for referenced assets (url(), @import, src=, href=, fonts)
    ref_patterns = [
        re.compile(r'url\s*\(\s*[\'"]?([^\'")]+)[\'"]?\s*\)'),
        re.compile(r'@import\s+[\'"]([^\'"]+)[\'"]'),
        re.compile(r'src=[\'"]([^\'"]+)[\'"]'),
        re.compile(r'href=[\'"]([^\'"]+)[\'"]')
    ]
    
    scan_sources = [
        os.path.join(gui_dir, "index.html"),
        os.path.join(gui_dir, "style.css"),
        os.path.join(gui_dir, "app.js"),
        os.path.join(gui_dir, "tour_strings.js"),
        os.path.join(gui_dir, "fonts", "fonts.css")
    ]
    
    for src_file in scan_sources:
        if not os.path.isfile(src_file):
            continue
        rel_src = os.path.relpath(src_file, BASE_DIR).replace("\\", "/")
        ui_files.add(rel_src)
        with open(src_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        for pat in ref_patterns:
            for match in pat.findall(content):
                clean_ref = match.split("?")[0].split("#")[0].strip()
                if clean_ref.startswith("data:") or clean_ref.startswith("http:") or clean_ref.startswith("https:"):
                    continue
                # Resolve relative to src_file or gui_dir
                cand1 = os.path.normpath(os.path.join(os.path.dirname(src_file), clean_ref))
                cand2 = os.path.normpath(os.path.join(gui_dir, clean_ref))
                for cand in (cand1, cand2):
                    if os.path.isfile(cand):
                        ui_files.add(os.path.relpath(cand, BASE_DIR).replace("\\", "/"))

    # Also ensure all fonts in gui/fonts are included
    fonts_dir = os.path.join(gui_dir, "fonts")
    if os.path.isdir(fonts_dir):
        for fn in os.listdir(fonts_dir):
            fp = os.path.join(fonts_dir, fn)
            if os.path.isfile(fp):
                ui_files.add(os.path.relpath(fp, BASE_DIR).replace("\\", "/"))

    # Filter out backup files (.bak)
    ui_in_use = sorted([f for f in ui_files if not f.endswith(".bak")])
    
    print("\n--- UI IN USE (PROTECTED SET) ---")
    manifest = {}
    for rel_path in ui_in_use:
        full_path = os.path.join(BASE_DIR, rel_path)
        sz = os.path.getsize(full_path)
        digest = sha256_file(full_path)
        manifest[rel_path] = {
            "sha256": digest,
            "size": sz
        }
        print(f"  {rel_path}: size={sz}, sha256={digest[:12]}...")

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nRe-created {MANIFEST_PATH} with {len(manifest)} frozen UI assets! ✅")

if __name__ == "__main__":
    run()
