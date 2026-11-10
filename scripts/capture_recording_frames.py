import os
import sys
import time
from PIL import Image
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDINGS_DIR = os.path.join(BASE_DIR, "analysis", "recordings")
os.makedirs(RECORDINGS_DIR, exist_ok=True)

def record_film_strip():
    print("Capturing film-strip progress frame sequence...")
    frames_dir = os.path.join(RECORDINGS_DIR, "film_strip_frames")
    os.makedirs(frames_dir, exist_ok=True)
    images = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        page.goto(f"{BASE_URL}/?ui_theme=cutting_room", wait_until="domcontentloaded")
        page.wait_for_timeout(800)

        # Navigate to Render step (step 4)
        page.evaluate("() => { if (window.navigateToStep) window.navigateToStep(4); }")
        page.wait_for_timeout(400)

        # Capture sequence of 10 progression frames
        stages = [
            (0, "00:00.0", "INITIALIZING ENGINE", "Mounting clip bank and verifying disk budget..."),
            (12, "00:14.2", "STAGE 1/8 HARVESTING", "Found 48 candidates matching query..."),
            (25, "00:32.8", "STAGE 2/8 AUDIO TRANSCRIBE", "Transcribing vocal track with Whisper..."),
            (38, "00:51.4", "STAGE 3/8 VISION DETECT", "YOLOv8 detected cat, dog, couch (confidence 0.94)..."),
            (50, "01:10.1", "STAGE 4/8 MOMENT SCORING", "Scoring 18 funny moments with audio-visual peak..."),
            (65, "01:28.7", "STAGE 5/8 SMART CROP", "Dynamic 9:16 re-framing centered on cat face..."),
            (78, "01:46.3", "STAGE 6/8 COMPILATION", "Stitching 12 verified clips with 0 black frames..."),
            (90, "02:04.9", "STAGE 7/8 COLOR GRADE", "LUT grading applied with 0 clipping..."),
            (100, "02:18.4", "RENDER COMPLETE", "Master MP4 rendered successfully. Quality verified.")
        ]

        for idx, (pct, elapsed, badge_text, status_desc) in enumerate(stages):
            page.evaluate(f"""(data) => {{
                // Update filmstrip progress
                const bar = document.getElementById('render-progress-fill') || document.getElementById('progress-bar-fill');
                if (bar) bar.style.width = data.pct + '%';
                
                const timeEl = document.getElementById('render-elapsed-time');
                if (timeEl) timeEl.innerText = data.elapsed;

                const badge = document.getElementById('render-status-badge') || document.querySelector('.render-badge');
                if (badge) badge.innerText = data.badge;

                const txt = document.getElementById('render-status-text') || document.getElementById('progress-status-desc');
                if (txt) txt.innerText = data.status;

                // Sync filmstrip hero timeline
                if (window.syncCuttingRoomTimeline) {{
                    window.syncCuttingRoomTimeline(data.pct);
                }} else {{
                    const strip = document.getElementById('cr-filmstrip-progress');
                    if (strip) strip.style.width = data.pct + '%';
                }}
            }}""", {"pct": pct, "elapsed": elapsed, "badge": badge_text, "status": status_desc})
            
            page.wait_for_timeout(150)
            frame_path = os.path.join(frames_dir, f"frame_{idx:02d}_{pct:03d}pct.png")
            page.screenshot(path=frame_path)
            images.append(Image.open(frame_path))

        browser.close()

    # Save as animated WebP and GIF
    if images:
        webp_path = os.path.join(RECORDINGS_DIR, "film_strip_progress.webp")
        gif_path = os.path.join(RECORDINGS_DIR, "film_strip_progress.gif")
        images[0].save(webp_path, save_all=True, append_images=images[1:], duration=350, loop=0)
        images[0].save(gif_path, save_all=True, append_images=images[1:], duration=350, loop=0)
        print(f"Saved film strip progress recording to {webp_path} and {gif_path}")

def record_theme_switch():
    print("Capturing theme switch crossfade frame sequence...")
    frames_dir = os.path.join(RECORDINGS_DIR, "theme_switch_frames")
    os.makedirs(frames_dir, exist_ok=True)
    images = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        page.goto(f"{BASE_URL}/?ui_theme=cutting_room", wait_until="domcontentloaded")
        page.wait_for_timeout(800)

        # Go to Export tab to show preview, platform tabs, and buttons
        page.evaluate("() => { if (window.navigateToStep) window.navigateToStep(5); }")
        page.wait_for_timeout(400)

        # Capture dark frame
        page.evaluate("() => { document.documentElement.setAttribute('data-theme', 'dark'); document.documentElement.style.colorScheme = 'dark'; }")
        page.wait_for_timeout(200)
        f1 = os.path.join(frames_dir, "frame_01_dark.png")
        page.screenshot(path=f1)
        images.append(Image.open(f1))

        # Perform transition switch to light mode
        page.evaluate("""() => {
            if (window.toggleTheme) {
                window.toggleTheme();
            } else {
                document.documentElement.setAttribute('data-theme', 'light');
                document.documentElement.style.colorScheme = 'light';
            }
        }""")
        page.wait_for_timeout(60)
        f2 = os.path.join(frames_dir, "frame_02_transition_mid1.png")
        page.screenshot(path=f2)
        images.append(Image.open(f2))

        page.wait_for_timeout(100)
        f3 = os.path.join(frames_dir, "frame_03_transition_mid2.png")
        page.screenshot(path=f3)
        images.append(Image.open(f3))

        page.wait_for_timeout(150)
        f4 = os.path.join(frames_dir, "frame_04_light_settled.png")
        page.screenshot(path=f4)
        images.append(Image.open(f4))

        # Switch back to dark mode
        page.evaluate("""() => {
            if (window.toggleTheme) {
                window.toggleTheme();
            } else {
                document.documentElement.setAttribute('data-theme', 'dark');
                document.documentElement.style.colorScheme = 'dark';
            }
        }""")
        page.wait_for_timeout(60)
        f5 = os.path.join(frames_dir, "frame_05_transition_back_mid1.png")
        page.screenshot(path=f5)
        images.append(Image.open(f5))

        page.wait_for_timeout(150)
        f6 = os.path.join(frames_dir, "frame_06_dark_settled.png")
        page.screenshot(path=f6)
        images.append(Image.open(f6))

        browser.close()

    if images:
        webp_path = os.path.join(RECORDINGS_DIR, "theme_switch.webp")
        gif_path = os.path.join(RECORDINGS_DIR, "theme_switch.gif")
        images[0].save(webp_path, save_all=True, append_images=images[1:], duration=400, loop=0)
        images[0].save(gif_path, save_all=True, append_images=images[1:], duration=400, loop=0)
        print(f"Saved theme switch recording to {webp_path} and {gif_path}")

if __name__ == "__main__":
    record_film_strip()
    record_theme_switch()
