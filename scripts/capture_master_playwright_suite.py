import os
import sys
import time
import json
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "analysis", "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
HAR_PATH = os.path.join(BASE_DIR, "analysis", "ui_network_trace.har")

def run():
    print("=== LAUNCHING PLAYWRIGHT (channel='chrome', headless=True) ===")
    sys.stdout.flush()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        
        views_to_capture = [
            ("Library", 1),
            ("Create", 2),
            ("Sources", 3),
            ("Render", 4),
            ("Export", 5),
            ("CleanupModal", "cleanup")
        ]
        
        viewports = [
            (1440, 900, "1440"),
            (390, 844, "390")
        ]
        
        themes = ["dark", "light"]
        
        overflow_reports = []
        har_recorded = False

        for w, h, vp_label in viewports:
            for theme in themes:
                context_args = {
                    "viewport": {"width": w, "height": h}
                }
                # Record HAR on primary desktop run
                if not har_recorded and vp_label == "1440" and theme == "dark":
                    context_args["record_har_path"] = HAR_PATH
                    context_args["record_har_content"] = "embed"
                    har_recorded = True

                context = browser.new_context(**context_args)
                page = context.new_page()
                page.on("dialog", lambda dialog: dialog.accept())
                
                page.goto("http://127.0.0.1:8000/")
                page.wait_for_load_state("domcontentloaded")
                time.sleep(1.0)
                
                # Apply theme
                page.evaluate(f"""(th) => {{
                    if (typeof applyTheme === 'function') {{
                        applyTheme(th);
                    }} else {{
                        document.documentElement.setAttribute('data-theme', th);
                        if (th === 'light') {{
                            document.documentElement.classList.add('light-mode');
                            document.body.classList.add('light-mode');
                        }} else {{
                            document.documentElement.classList.remove('light-mode');
                            document.body.classList.remove('light-mode');
                        }}
                    }}
                }}""", theme)
                time.sleep(0.5)

                for view_name, step_num in views_to_capture:
                    if step_num == "cleanup":
                        # Open safe cleanup modal
                        page.evaluate("""() => {
                            if (typeof openSafeCleanupModal === 'function') {
                                openSafeCleanupModal();
                            } else {
                                const btn = document.getElementById('btn-open-safe-cleanup');
                                if (btn) btn.click();
                            }
                        }""")
                        time.sleep(1.2)
                        # Check modal is visible
                        modal_visible = page.evaluate("""() => {
                            const m = document.getElementById('modal-safe-cleanup');
                            return m && m.style.display !== 'none';
                        }""")
                        if not modal_visible:
                            print(f"Warning: Cleanup modal not visible for {view_name}_{vp_label}_{theme}")
                    else:
                        page.evaluate(f"""(step) => {{
                            if (typeof navigateToStep === 'function') {{
                                navigateToStep(step);
                            }} else {{
                                const viewMap = {{1: 'view-dashboard', 2: 'view-wizard', 3: 'view-editor', 4: 'view-render', 5: 'view-export'}};
                                document.querySelectorAll('.workspace-view').forEach(v => v.classList.remove('active'));
                                const tgt = document.getElementById(viewMap[step]);
                                if (tgt) tgt.classList.add('active');
                            }}
                        }}""", step_num)
                        time.sleep(0.8)

                    # Check for horizontal overflow
                    overflow_info = page.evaluate("""() => {
                        const docEl = document.documentElement;
                        const body = document.body;
                        const scrollW = Math.max(docEl.scrollWidth, body.scrollWidth);
                        const clientW = window.innerWidth;
                        const hasOverflow = scrollW > clientW + 1;
                        
                        const overflowingElements = [];
                        if (hasOverflow) {
                            const all = document.querySelectorAll('*');
                            all.forEach(el => {
                                const rect = el.getBoundingClientRect();
                                if (rect.right > clientW + 2) {
                                    overflowingElements.push({
                                        tag: el.tagName,
                                        id: el.id,
                                        className: el.className,
                                        right: Math.round(rect.right),
                                        clientW: clientW
                                    });
                                }
                            });
                        }
                        return {
                            hasOverflow: hasOverflow,
                            scrollWidth: scrollW,
                            clientWidth: clientW,
                            overflowElements: overflowingElements.slice(0, 5)
                        };
                    }""")

                    overflow_reports.append({
                        "view": view_name,
                        "viewport": f"{w}x{h}",
                        "theme": theme,
                        "overflow": overflow_info
                    })

                    # Take screenshot
                    shot_name = f"{view_name.lower()}_{vp_label}_{theme}.png"
                    shot_path = os.path.join(SCREENSHOTS_DIR, shot_name)
                    
                    if step_num == "cleanup":
                        # Take screenshot of the modal dialog
                        modal_loc = page.locator("#modal-safe-cleanup .modal-dialog")
                        if modal_loc.count() > 0 and modal_loc.is_visible():
                            modal_loc.screenshot(path=shot_path)
                        else:
                            page.screenshot(path=shot_path, full_page=False)
                        # Close modal before next view
                        page.evaluate("""() => {
                            const m = document.getElementById('modal-safe-cleanup');
                            if (m) m.style.display = 'none';
                        }""")
                    else:
                        page.screenshot(path=shot_path, full_page=False)
                    
                    print(f"Captured: {shot_name} (viewport={w}x{h}, theme={theme}, overflow={overflow_info['hasOverflow']})")
                    sys.stdout.flush()

                context.close()

        # Check DOM overflow across 1920, 1440, 1280, 768, 390 px viewports
        test_widths = [1920, 1440, 1280, 768, 390]
        print("\n--- RUNNING DOM OVERFLOW AUDIT ACROSS 5 VIEWPORTS ---")
        sys.stdout.flush()
        for tw in test_widths:
            context = browser.new_context(viewport={"width": tw, "height": 900})
            page = context.new_page()
            page.goto("http://127.0.0.1:8000/")
            page.wait_for_load_state("domcontentloaded")
            time.sleep(0.8)
            for view_name, step_num in [("Create", 2), ("Render", 4), ("Export", 5), ("Library", 1)]:
                page.evaluate(f"""(step) => {{
                    if (typeof navigateToStep === 'function') {{
                        navigateToStep(step);
                    }} else {{
                        const viewMap = {{1: 'view-dashboard', 2: 'view-wizard', 3: 'view-editor', 4: 'view-render', 5: 'view-export'}};
                        document.querySelectorAll('.workspace-view').forEach(v => v.classList.remove('active'));
                        const tgt = document.getElementById(viewMap[step]);
                        if (tgt) tgt.classList.add('active');
                    }}
                }}""", step_num)
                time.sleep(0.4)
                overflow_res = page.evaluate("""() => {
                    const scrollW = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
                    const clientW = window.innerWidth;
                    return {
                        hasOverflow: scrollW > clientW + 1,
                        scrollWidth: scrollW,
                        clientWidth: clientW
                    };
                }""")
                status = "PASS (No overflow)" if not overflow_res["hasOverflow"] else f"FAIL (scrollW={overflow_res['scrollWidth']} > clientW={overflow_res['clientWidth']})"
                print(f"Width {tw}px | {view_name}: {status}")
                sys.stdout.flush()
            context.close()

        browser.close()
        print(f"\nAll Playwright screenshots and audits completed successfully! ✅")
        print(f"HAR network trace written to: {HAR_PATH}")
        sys.stdout.flush()

if __name__ == "__main__":
    run()
