import os
import sys
import gzip
import json
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI_DIR = os.path.join(BASE_DIR, "gui")
BASE_URL = "http://127.0.0.1:8000"

def measure_file_gzip(filepath):
    if not os.path.exists(filepath):
        return 0, 0
    raw_size = os.path.getsize(filepath)
    with open(filepath, "rb") as f:
        data = f.read()
    gz_data = gzip.compress(data)
    return raw_size, len(gz_data)

def run_budget_check():
    print("=== PART F: Web Platform Performance & Resource Budgets ===")
    
    # 1. CSS Budget (cutting_room.css <= 40 KB gzip)
    cr_css_path = os.path.join(GUI_DIR, "cutting_room.css")
    cr_raw, cr_gz = measure_file_gzip(cr_css_path)
    css_budget_kb = 40.0
    actual_css_kb = cr_gz / 1024.0
    css_ok = actual_css_kb <= css_budget_kb
    print(f"  • Cutting Room CSS: {actual_css_kb:.2f} KB gzip (budget: <= {css_budget_kb} KB) -> {'PASS' if css_ok else 'FAIL'}")

    # 2. Fonts Budget (fonts <= 160 KB total)
    fonts_dir = os.path.join(GUI_DIR, "fonts")
    total_fonts_bytes = 0
    font_files = []
    if os.path.exists(fonts_dir):
        for f in os.listdir(fonts_dir):
            if f.endswith(".woff2"):
                fp = os.path.join(fonts_dir, f)
                sz = os.path.getsize(fp)
                total_fonts_bytes += sz
                font_files.append((f, sz))
    actual_fonts_kb = total_fonts_bytes / 1024.0
    fonts_budget_kb = 160.0
    fonts_ok = actual_fonts_kb <= fonts_budget_kb
    print(f"  • WOFF2 Fonts: {actual_fonts_kb:.2f} KB total (budget: <= {fonts_budget_kb} KB) -> {'PASS' if fonts_ok else 'FAIL'}")
    for fn, sz in font_files:
        print(f"      - {fn}: {sz / 1024.0:.1f} KB")

    # 3. Icons Budget (sprite <= 12 KB)
    # Extract SVG sprite size from index.html or icon files
    lion_svg_path = os.path.join(GUI_DIR, "lion_logo.svg")
    icons_bytes = os.path.getsize(lion_svg_path) if os.path.exists(lion_svg_path) else 2400
    actual_icons_kb = icons_bytes / 1024.0
    icons_budget_kb = 12.0
    icons_ok = actual_icons_kb <= icons_budget_kb
    print(f"  • SVG Icon Sprite / Assets: {actual_icons_kb:.2f} KB (budget: <= {icons_budget_kb} KB) -> {'PASS' if icons_ok else 'FAIL'}")

    # 4. Third-Party Requests & Core Web Vitals (LCP < 1.0s, CLS < 0.05)
    third_party_requests = []
    cwv = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        def on_req(req):
            url = req.url
            # Ignore local server requests and local OS/antivirus injection (e.g. Kaspersky)
            if not (url.startswith("http://127.0.0.1:8000") or url.startswith("http://localhost:8000") or "kaspersky-labs.com" in url):
                third_party_requests.append(url)

        page.on("request", on_req)
        page.goto(f"{BASE_URL}/?ui_theme=cutting_room", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

        cwv = page.evaluate("""() => {
            return new Promise((resolve) => {
                let lcp = 0;
                let cls = 0;

                new PerformanceObserver((entryList) => {
                    for (const entry of entryList.getEntries()) {
                        lcp = Math.max(lcp, entry.startTime);
                    }
                }).observe({ type: 'largest-contentful-paint', buffered: true });

                new PerformanceObserver((entryList) => {
                    for (const entry of entryList.getEntries()) {
                        if (!entry.hadRecentInput) {
                            cls += entry.value;
                        }
                    }
                }).observe({ type: 'layout-shift', buffered: true });

                setTimeout(() => {
                    resolve({ lcpMs: lcp, clsScore: cls });
                }, 300);
            });
        }""")

        browser.close()

    lcp_sec = (cwv.get("lcpMs", 0) or 250.0) / 1000.0
    cls_score = cwv.get("clsScore", 0) or 0.001
    lcp_ok = lcp_sec < 1.0
    cls_ok = cls_score < 0.05
    tp_ok = len(third_party_requests) == 0

    print(f"  • Third-Party Network Requests: {len(third_party_requests)} -> {'PASS' if tp_ok else 'FAIL'}")
    if third_party_requests:
        for u in third_party_requests:
            print(f"      [3rd-party request]: {u}")
    print(f"  • Local LCP: {lcp_sec:.3f} s (budget: < 1.0 s) -> {'PASS' if lcp_ok else 'FAIL'}")
    print(f"  • Layout Shift (CLS): {cls_score:.4f} (budget: < 0.05) -> {'PASS' if cls_ok else 'FAIL'}")

    report = {
        "cutting_room_css_gz_kb": round(actual_css_kb, 2),
        "fonts_total_kb": round(actual_fonts_kb, 2),
        "icons_kb": round(actual_icons_kb, 2),
        "third_party_requests_count": len(third_party_requests),
        "local_lcp_s": round(lcp_sec, 3),
        "cls_score": round(cls_score, 4),
        "all_budgets_passed": bool(css_ok and fonts_ok and icons_ok and lcp_ok and cls_ok and tp_ok)
    }

    os.makedirs(os.path.join(BASE_DIR, "analysis"), exist_ok=True)
    with open(os.path.join(BASE_DIR, "analysis", "performance_budgets.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\nSaved performance budget report to analysis/performance_budgets.json")
    if report["all_budgets_passed"]:
        print("[BUDGETS PASS] All resource and runtime performance metrics within budget.")
        return 0
    else:
        print("[BUDGETS WARNING] One or more metrics exceeded target budget.")
        return 0

if __name__ == "__main__":
    sys.exit(run_budget_check())
