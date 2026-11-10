import sys
import os
import json
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"
VIEWPORTS = [1440, 1280, 1024, 860, 390]
THEMES = ["dark", "light"]
STEPS = [1, 2, 3, 4, 5]

def run_a9_audit():
    print("[A9 AUDIT] Starting layout audit across viewports and themes...")
    findings = []
    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)

        for theme in THEMES:
            for w in VIEWPORTS:
                h = 900 if w > 600 else 844
                context = browser.new_context(viewport={"width": w, "height": h})
                page = context.new_page()

                def on_console(msg):
                    if msg.type == "error":
                        console_errors.append(f"[{theme}@{w}px] Console error: {msg.text}")

                page.on("console", on_console)
                page.goto(f"{BASE_URL}/?ui_theme=cutting_room", wait_until="domcontentloaded")
                page.wait_for_timeout(400)

                # Set color theme
                page.evaluate(f"() => {{ if (window.applyTheme) window.applyTheme('{theme}'); }}")
                page.wait_for_timeout(300)

                for step in STEPS:
                    page.evaluate(f"() => {{ if (window.navigateToStep) window.navigateToStep({step}); }}")
                    page.wait_for_timeout(250)

                    # Check for horizontal root overflow
                    root_check = page.evaluate("""() => {
                        const doc = document.documentElement;
                        const body = document.body;
                        const scrollW = Math.max(doc.scrollWidth, body.scrollWidth);
                        const clientW = doc.clientWidth;
                        return {
                            hasOverflow: scrollW > clientW + 2,
                            scrollW: scrollW,
                            clientW: clientW
                        };
                    }""")

                    if root_check["hasOverflow"]:
                        findings.append({
                            "type": "HORIZONTAL_PAGE_OVERFLOW",
                            "theme": theme,
                            "viewport": w,
                            "step": step,
                            "detail": f"Page scrollWidth ({root_check['scrollW']}px) exceeds clientWidth ({root_check['clientW']}px)"
                        })

                    # Check for element overlaps in key action rows / headers
                    overlap_check = page.evaluate("""() => {
                        const badOverlaps = [];
                        // Check header brand vs stepper vs right controls
                        const header = document.querySelector('.app-header');
                        if (header) {
                            const left = header.querySelector('.header-left');
                            const stepper = header.querySelector('.workflow-stepper');
                            const right = header.querySelector('.header-right');
                            if (left && stepper && right) {
                                const lBox = left.getBoundingClientRect();
                                const sBox = stepper.getBoundingClientRect();
                                const rBox = right.getBoundingClientRect();
                                if (sBox.width > 0 && lBox.width > 0 && rBox.width > 0) {
                                    if (lBox.right > sBox.left + 4) {
                                        badOverlaps.push(`Header left overlaps stepper by ${Math.round(lBox.right - sBox.left)}px`);
                                    }
                                    if (sBox.right > rBox.left + 4) {
                                        badOverlaps.push(`Stepper overlaps header right by ${Math.round(sBox.right - rBox.left)}px`);
                                    }
                                }
                            }
                        }

                        // Check export action buttons
                        const expActions = document.querySelector('.export-panel-quick-actions');
                        const expPanel = document.querySelector('.export-tabs-panel');
                        if (expActions && expPanel) {
                            const aBox = expActions.getBoundingClientRect();
                            const pBox = expPanel.getBoundingClientRect();
                            if (aBox.right > pBox.right + 2) {
                                badOverlaps.push(`Export quick actions overflow right panel boundary: aBox.right=${aBox.right}, pBox.right=${pBox.right}`);
                            }
                        }

                        return badOverlaps;
                    }""")

                    for ov in overlap_check:
                        findings.append({
                            "type": "OVERLAP_OR_OVERFLOW",
                            "theme": theme,
                            "viewport": w,
                            "step": step,
                            "detail": ov
                        })

                context.close()

        browser.close()

    result = {
        "status": "PASS" if len(findings) == 0 and len(console_errors) == 0 else "FAIL",
        "findings_count": len(findings),
        "console_errors_count": len(console_errors),
        "findings": findings,
        "console_errors": console_errors
    }

    os.makedirs("analysis", exist_ok=True)
    with open("analysis/layout_audit_a9.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"[A9 AUDIT] Complete: {len(findings)} layout findings, {len(console_errors)} console errors.")
    if result["status"] == "PASS":
        print("[A9 AUDIT] PASSED: Zero findings across all viewports and themes.")
        return 0
    else:
        print("[A9 AUDIT] FAILED:")
        for f in findings:
            print(" -", f)
        for err in console_errors:
            print(" - Error:", err)
        return 1

if __name__ == "__main__":
    sys.exit(run_a9_audit())
