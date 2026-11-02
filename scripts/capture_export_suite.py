import os
import time
from playwright.sync_api import sync_playwright

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "analysis", "screenshots")
os.makedirs(OUTPUT_DIR, exist_ok=True)

VIDEOS = [
    {
        "id": "short_30s",
        "file": "lionreel_cat_20261017_102216_9ed2b729.mp4",
        "label": "30s Vertical Short"
    },
    {
        "id": "long_3min",
        "file": "lionreel_cat_3min_16_9.mp4",
        "label": "3min 16:9 Long Video"
    },
    {
        "id": "long_19m52s",
        "file": "lionreel_cat_20261015_190045_fc2355ef.mp4",
        "label": "19m52s Long Video"
    }
]

VIEWPORTS = [
    {"name": "1440px", "width": 1440, "height": 900},
    {"name": "1024px", "width": 1024, "height": 768},
    {"name": "390px", "width": 390, "height": 844}
]

THEMES = [
    {"name": "dark", "class_add": None, "class_remove": "light-theme"},
    {"name": "light", "class_add": "light-theme", "class_remove": None}
]

def main():
    print("=== Launching Playwright Chrome to Capture Export Screen Screenshots ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)

        for v in VIDEOS:
            print(f"\n--- Video: {v['label']} ({v['file']}) ---")
            for vp in VIEWPORTS:
                for th in THEMES:
                    context = browser.new_context(viewport={"width": vp["width"], "height": vp["height"]})
                    page = context.new_page()

                    # Navigate directly to #export
                    page.goto("http://127.0.0.1:8000/#export", wait_until="domcontentloaded")
                    page.wait_for_timeout(1000)

                    # Ensure target video is selected
                    target_file = v["file"]
                    page.evaluate(f"""(filename) => {{
                        if (window.setupExportScreen) {{
                            window.setupExportScreen(filename);
                        }}
                    }}""", target_file)
                    page.wait_for_timeout(600)

                    # Set theme using app's applyTheme
                    page.evaluate(f"""(themeName) => {{
                        if (window.applyTheme) {{
                            window.applyTheme(themeName);
                        }} else {{
                            document.documentElement.setAttribute('data-theme', themeName);
                            document.body.setAttribute('data-theme', themeName);
                            if (themeName === 'light') {{
                                document.documentElement.classList.add('theme-light', 'light-mode');
                                document.body.classList.add('theme-light', 'light-mode');
                            }} else {{
                                document.documentElement.classList.add('theme-dark', 'dark-mode');
                                document.body.classList.add('theme-dark', 'dark-mode');
                            }}
                        }}
                    }}""", th["name"])
                    page.wait_for_timeout(400)

                    # Check for body horizontal overflow / clipping
                    scroll_info = page.evaluate("""() => {
                        return {
                            scrollWidth: document.body.scrollWidth,
                            clientWidth: document.body.clientWidth,
                            hasHorizontalScroll: document.body.scrollWidth > document.body.clientWidth
                        };
                    }""")

                    filename = f"export_{v['id']}_{vp['name']}_{th['name']}.png"
                    out_path = os.path.join(OUTPUT_DIR, filename)
                    page.screenshot(path=out_path, full_page=False)

                    print(f"  Saved: {filename} (Width: {vp['width']}, Overflow: {scroll_info['hasHorizontalScroll']})")
                    context.close()

        browser.close()
    print(f"\n[DONE] All 18 screenshots successfully captured in {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
