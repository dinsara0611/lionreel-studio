import os
import sys
import time
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "analysis", "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def run():
    with sync_playwright() as p:
        # User requirement: installed Chrome (channel='chrome', no driver download)
        browser = p.chromium.launch(channel="chrome", headless=True)
        
        test_matrix = [
            {"state": "normal", "theme": "dark", "width": 1440, "height": 900},
            {"state": "normal", "theme": "light", "width": 1440, "height": 900},
            {"state": "normal", "theme": "dark", "width": 390, "height": 844},
            {"state": "normal", "theme": "light", "width": 390, "height": 844},
            {"state": "waiting", "theme": "dark", "width": 1440, "height": 900},
            {"state": "waiting", "theme": "light", "width": 1440, "height": 900},
            {"state": "waiting", "theme": "dark", "width": 390, "height": 844},
            {"state": "waiting", "theme": "light", "width": 390, "height": 844},
        ]
        
        for config in test_matrix:
            state_mode = config["state"]
            theme = config["theme"]
            w = config["width"]
            h = config["height"]
            
            context = browser.new_context(viewport={"width": w, "height": h})
            page = context.new_page()
            
            # Auto-handle dialog if stop button confirm is triggered
            page.on("dialog", lambda dialog: dialog.accept())
            
            # Navigate to the local dashboard
            page.goto("http://127.0.0.1:8000/")
            page.wait_for_load_state("domcontentloaded")
            time.sleep(1.0)
            
            # Switch to render view and inject mock telemetry
            page.evaluate(f"""() => {{
                // Apply theme
                document.documentElement.setAttribute('data-theme', '{theme}');
                if ('{theme}' === 'light') {{
                    document.documentElement.classList.add('light-mode');
                    document.body.classList.add('light-mode');
                }} else {{
                    document.documentElement.classList.remove('light-mode');
                    document.body.classList.remove('light-mode');
                }}
                
                // Switch to view-render
                document.querySelectorAll('.workspace-view').forEach(v => v.classList.remove('active'));
                const renderView = document.getElementById('view-render');
                if (renderView) renderView.classList.add('active');
                
                // Mock state
                const isWait = ('{state_mode}' === 'waiting');
                const heroCard = document.getElementById('render-hero-card');
                const headline = document.getElementById('render-headline');
                const subtitle = document.getElementById('render-subtitle');
                const autopilotEl = document.getElementById('render-autopilot-status');
                const autopilotMsg = document.getElementById('render-autopilot-msg');
                const pctEl = document.getElementById('render-percentage-text');
                const fillEl = document.getElementById('render-progress-fill');
                const elapsedEl = document.getElementById('render-time-elapsed');
                const remainEl = document.getElementById('render-time-remaining');
                const stageNameEl = document.getElementById('render-stage-name');
                const liveBadge = document.getElementById('live-clock-badge');
                const liveText = document.getElementById('live-clock-text');
                const stopBtn = document.getElementById('btn-render-cancel');
                
                if (stopBtn) stopBtn.style.display = 'inline-flex';
                if (elapsedEl) elapsedEl.innerText = '01:22';
                
                if (isWait) {{
                    if (heroCard) {{
                        heroCard.classList.remove('failed');
                        heroCard.classList.add('waiting');
                    }}
                    if (headline) headline.innerText = 'Finding new footage';
                    if (subtitle) subtitle.innerText = '4 clips x 7.5 s = 30 s. 1 new clip ready, 3 to find.';
                    if (autopilotEl) {{
                        autopilotEl.style.display = 'block';
                        autopilotEl.classList.add('waiting');
                    }}
                    if (autopilotMsg) autopilotMsg.innerText = '4 clips x 7.5 s = 30 s. 1 new clip ready, 3 to find. • Pool: 1/4 clips ready • Finding new footage (need 3 more, found 1, verifying 0)';
                    if (pctEl) pctEl.innerText = '25%';
                    if (fillEl) fillEl.style.width = '25%';
                    if (remainEl) remainEl.innerText = '00:45 – 01:15';
                    if (stageNameEl) stageNameEl.innerText = 'Finding new footage';
                    if (liveBadge) liveBadge.className = 'live-clock-badge badge-waiting';
                    if (liveText) liveText.innerText = 'WAITING';
                }} else {{
                    if (heroCard) {{
                        heroCard.classList.remove('failed', 'waiting');
                    }}
                    if (headline) headline.innerText = 'Rendering your video';
                    if (subtitle) subtitle.innerText = '4 clips x 7.5 s = 30 s. 1 new clip ready, 3 to find.';
                    if (autopilotEl) {{
                        autopilotEl.style.display = 'block';
                        autopilotEl.classList.remove('waiting');
                    }}
                    if (autopilotMsg) autopilotMsg.innerText = '4 clips x 7.5 s = 30 s. 1 new clip ready, 3 to find. • Pool: 1/4 clips ready • Stage 6/10: Reframe and render cuts (est. 00:45 – 01:15)';
                    if (pctEl) pctEl.innerText = '50%';
                    if (fillEl) fillEl.style.width = '50%';
                    if (remainEl) remainEl.innerText = '00:45 – 01:15';
                    if (stageNameEl) stageNameEl.innerText = 'Reframe and render cuts';
                    if (liveBadge) liveBadge.className = 'live-clock-badge';
                    if (liveText) liveText.innerText = 'LIVE';
                }}
            }}""")
            
            time.sleep(0.5)
            
            # Verify UI contracts in page
            glow_eval = page.evaluate("""() => {
                const glow = document.querySelector('.render-hero-glow');
                const glowStyle = glow ? window.getComputedStyle(glow).display : 'none';
                const pct = document.querySelector('.render-pct-large');
                const pctShadow = pct ? window.getComputedStyle(pct).textShadow : 'none';
                const remainVal = document.getElementById('render-time-remaining').innerText;
                const headText = document.getElementById('render-headline').innerText;
                return {
                    glowDisplay: glowStyle,
                    pctShadow: pctShadow,
                    remainText: remainVal,
                    headline: headText
                };
            }""")
            
            assert glow_eval["glowDisplay"] == "none", f"Glow must be none, got {glow_eval['glowDisplay']}"
            assert "Waiting" not in glow_eval["remainText"], f"Remain text must not contain 'Waiting': {glow_eval['remainText']}"
            
            filename = f"render_screen_{state_mode}_{theme}_{w}.png"
            filepath = os.path.join(SCREENSHOTS_DIR, filename)
            
            # Capture screenshot of render hero card or full view
            render_card = page.locator("#render-hero-card")
            if render_card.count() > 0:
                render_card.screenshot(path=filepath)
            else:
                page.screenshot(path=filepath)
            
            print(f"Captured: {filename} (glow={glow_eval['glowDisplay']}, shadow={glow_eval['pctShadow']}, time={glow_eval['remainText']}, head={glow_eval['headline']})")
            context.close()
            
        browser.close()
        print("All 8 Playwright screenshots successfully captured.")

if __name__ == "__main__":
    run()
