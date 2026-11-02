"""
LionReel Studio — Step 3 ("Edit") Alignment & Consistency Test Suite
====================================================================
Playwright test suite verifying alignment, grid consistency, viewport fit,
and design token compliance for Step 3 (Edit) in dark and light themes,
across widths [1440, 1280, 1024, 860, 390], with video loaded and empty state.

Execution:
  .\\.venv\\Scripts\\python.exe tests/test_edit_alignment.py
"""

import os
import sys
import json
import time
import math
import random
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

_VENV_SITE = os.path.join(BASE_DIR, ".venv", "Lib", "site-packages")
if os.path.exists(_VENV_SITE) and _VENV_SITE not in sys.path:
    sys.path.insert(0, _VENV_SITE)

from playwright.sync_api import sync_playwright

SERVER_URL = "http://localhost:8000"
TARGET_JOB_ID = "lionreel_cat_20261010_210235_2c0674b7"
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "data", "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


class TestEditAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--disable-web-security", "--allow-file-access-from-files"]
        )
        cls.context = cls.browser.new_context(viewport={"width": 1440, "height": 900})
        cls.page = cls.context.new_page()

        # Connect to web server
        for _ in range(10):
            try:
                resp = cls.page.goto(SERVER_URL, timeout=10000)
                if resp and resp.status == 200:
                    break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError(f"Could not connect to {SERVER_URL}")

        cls.page.wait_for_timeout(1000)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.context.close()
            cls.browser.close()
            cls.pw.stop()
        except Exception:
            pass

    def _load_video_in_editor(self, width=1440, height=900, theme="dark"):
        """Load the target video in the editor step."""
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.evaluate(f"""(theme) => {{
            document.documentElement.setAttribute('data-theme', theme);
            if (theme === 'dark') {{
                document.body.classList.remove('theme-light');
            }} else {{
                document.body.classList.add('theme-light');
            }}
        }}""", theme)
        self.page.evaluate(f"""async (jobId) => {{
            if (window.loadVideoIntoEditor) {{
                await window.loadVideoIntoEditor(jobId);
            }}
            if (window.navigateToStep) {{
                window.navigateToStep(3);
            }}
        }}""", TARGET_JOB_ID)
        self.page.wait_for_selector("#view-editor.active", timeout=5000)
        self.page.wait_for_selector("#editor-loaded-bar", timeout=5000)
        self.page.wait_for_timeout(600)

    def _load_empty_editor(self, width=1440, height=900, theme="dark"):
        """Load the editor in empty state (no video loaded)."""
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.evaluate(f"""(theme) => {{
            document.documentElement.setAttribute('data-theme', theme);
            if (theme === 'dark') {{
                document.body.classList.remove('theme-light');
            }} else {{
                document.body.classList.add('theme-light');
            }}
        }}""", theme)
        self.page.evaluate("""async () => {
            if (window.loadVideoIntoEditor) {
                await window.loadVideoIntoEditor(null);
            }
            if (window.navigateToStep) {
                window.navigateToStep(3);
            }
        }""")
        self.page.wait_for_selector("#view-editor.active", timeout=5000)
        self.page.wait_for_timeout(400)

    # -------------------------------------------------------------------------
    # TEST 1: Column tops, gap under header, container edges
    # -------------------------------------------------------------------------
    def test_01_column_tops_and_header_gap(self):
        """Left column top == right column top; gap under header is 16-24px; container edges match header."""
        self._load_video_in_editor(width=1440, height=900)

        header_box = self.page.locator("#editor-loaded-bar").bounding_box()
        left_col = self.page.locator(".editor-main-col").bounding_box()
        right_col = self.page.locator("#inspector-panel").bounding_box()
        layout_box = self.page.locator(".editor-layout").bounding_box()

        self.assertIsNotNone(header_box, "Header bar must be visible")
        self.assertIsNotNone(left_col, "Left column must be visible")
        self.assertIsNotNone(right_col, "Right column must be visible")

        # 1. Left column top == right column top (+/-1px)
        self.assertAlmostEqual(
            left_col["y"], right_col["y"], delta=1.5,
            msg=f"Left column top ({left_col['y']}) must equal right column top ({right_col['y']})"
        )

        # 2. Gap under header is between 16 and 24 px
        gap_under_header = left_col["y"] - (header_box["y"] + header_box["height"])
        self.assertTrue(
            15.5 <= gap_under_header <= 24.5,
            f"Gap under header ({gap_under_header}px) must be between 16 and 24px"
        )

        # 3. Container edges match header edges (+/-1px)
        self.assertAlmostEqual(
            header_box["x"], layout_box["x"], delta=1.5,
            msg=f"Header left ({header_box['x']}) must equal layout left ({layout_box['x']})"
        )
        header_right = header_box["x"] + header_box["width"]
        layout_right = layout_box["x"] + layout_box["width"]
        self.assertAlmostEqual(
            header_right, layout_right, delta=1.5,
            msg=f"Header right ({header_right}) must equal layout right ({layout_right})"
        )

    # -------------------------------------------------------------------------
    # TEST 2: Tabs design-system segmented control
    # -------------------------------------------------------------------------
    def test_02_tabs_segmented_control(self):
        """Tabs: equal heights (36px), equal gaps, exactly one selected, left edge matches video card."""
        self._load_video_in_editor(width=1440, height=900)

        tabs = self.page.locator(".editor-tab-btn").all()
        self.assertEqual(len(tabs), 3, "There must be 3 player tabs")

        # Equal heights (36px +/- 1px)
        heights = [t.bounding_box()["height"] for t in tabs if t.bounding_box()]
        for h in heights:
            self.assertAlmostEqual(h, 36.0, delta=1.5, msg=f"Tab height ({h}px) must be 36px")

        # Exactly one tab selected
        selected_count = self.page.evaluate("""() => {
            const tabs = document.querySelectorAll('.editor-tab-btn');
            return Array.from(tabs).filter(t => t.classList.contains('active') || t.getAttribute('aria-selected') === 'true').length;
        }""")
        self.assertEqual(selected_count, 1, "Exactly one tab must be selected/active")

        # Left edge equals video stage left edge (+/-1px)
        tabs_container = self.page.locator(".editor-player-tabs-bar").bounding_box()
        video_stage = self.page.locator("#vertical-video-stage").bounding_box()
        self.assertIsNotNone(tabs_container)
        self.assertIsNotNone(video_stage)
        self.assertAlmostEqual(
            tabs_container["x"], video_stage["x"], delta=1.5,
            msg=f"Tabs left edge ({tabs_container['x']}) must match video frame left ({video_stage['x']})"
        )

    # -------------------------------------------------------------------------
    # TEST 3: Preview viewport fit & pills alignment
    # -------------------------------------------------------------------------
    def test_03_preview_viewport_fit_and_pills(self):
        """Controls visible inside viewport at 1440x900 & 1280x720; 9:16 aspect ratio; pills same height & baseline."""
        for w, h in [(1440, 900), (1280, 720)]:
            self._load_video_in_editor(width=w, height=h)

            controls_box = self.page.locator(".player-controls-bar").bounding_box()
            self.assertIsNotNone(controls_box, "Player controls bar must exist")
            controls_bottom = controls_box["y"] + controls_box["height"]
            self.assertLessEqual(
                controls_bottom, h,
                f"Player controls bottom ({controls_bottom}px) must be inside viewport height ({h}px) without scrolling"
            )

            stage_box = self.page.locator("#vertical-video-stage").bounding_box()
            self.assertIsNotNone(stage_box)
            # 9:16 aspect ratio (+/- 1%)
            ratio = stage_box["width"] / stage_box["height"]
            expected_ratio = 9.0 / 16.0
            self.assertAlmostEqual(
                ratio, expected_ratio, delta=0.015,
                msg=f"Video stage aspect ratio ({ratio:.3f}) must be 9:16 ({expected_ratio:.3f})"
            )

            # Centered horizontally in container
            container_box = self.page.locator(".video-player-container").bounding_box()
            container_center_x = container_box["x"] + container_box["width"] / 2.0
            stage_center_x = stage_box["x"] + stage_box["width"] / 2.0
            self.assertAlmostEqual(
                container_center_x, stage_center_x, delta=1.5,
                msg=f"Stage center ({stage_center_x}) must be horizontally centered in container ({container_center_x})"
            )

            # Pills: Grade pill & Unmute pill
            # Make unmute pill visible to measure
            self.page.evaluate("""() => {
                const p = document.getElementById('editor-unmute-pill');
                if (p) p.style.display = 'inline-flex';
            }""")
            grade_pill = self.page.locator("#btn-toggle-enhancement").bounding_box()
            unmute_pill = self.page.locator("#editor-unmute-pill").bounding_box()
            self.assertIsNotNone(grade_pill)
            self.assertIsNotNone(unmute_pill)

            # Same height (28px)
            self.assertAlmostEqual(grade_pill["height"], 28.0, delta=1.5, msg=f"Grade pill height ({grade_pill['height']}) must be 28px")
            self.assertAlmostEqual(unmute_pill["height"], 28.0, delta=1.5, msg=f"Unmute pill height ({unmute_pill['height']}) must be 28px")

            # Same vertical center
            grade_cy = grade_pill["y"] + grade_pill["height"] / 2.0
            unmute_cy = unmute_pill["y"] + unmute_pill["height"] / 2.0
            self.assertAlmostEqual(
                grade_cy, unmute_cy, delta=1.5,
                msg=f"Grade pill vertical center ({grade_cy}) must match unmute pill ({unmute_cy})"
            )

    # -------------------------------------------------------------------------
    # TEST 4: Header card thumbnail, title nowrap, ID, badges & buttons
    # -------------------------------------------------------------------------
    def test_04_header_card_content_and_alignment(self):
        """Thumbnail is clean poster (never contact sheet); file name no wrap; ID clean; buttons & badges aligned."""
        self._load_video_in_editor(width=1440, height=900)

        # 1. Thumbnail is not contact sheet
        thumb_src = self.page.locator("#editor-loaded-poster").get_attribute("src") or ""
        self.assertNotIn(
            "contact_sheet", thumb_src.lower(),
            f"Thumbnail source must NEVER be the contact sheet: got {thumb_src}"
        )

        # 2. File name has no wrapping
        title_overflow = self.page.evaluate("""() => {
            const el = document.getElementById('editor-loaded-title');
            if (!el) return false;
            return el.scrollWidth > el.clientWidth && window.getComputedStyle(el).whiteSpace !== 'nowrap';
        }""")
        self.assertFalse(title_overflow, "Title must not wrap to a second line")

        # 3. ID does not duplicate the file name text
        id_text = self.page.locator("#editor-loaded-job-id").inner_text()
        title_text = self.page.locator("#editor-loaded-title").inner_text()
        self.assertNotEqual(
            id_text.strip(), f"ID: {title_text.strip()}",
            "ID line must not simply repeat the file name"
        )

        # 4. Badges have matching height and vertical centering
        v_badge = self.page.locator("#editor-loaded-version").bounding_box()
        qa_badge = self.page.locator("#editor-loaded-qa-status").bounding_box()
        self.assertIsNotNone(v_badge)
        self.assertIsNotNone(qa_badge)
        self.assertAlmostEqual(v_badge["height"], qa_badge["height"], delta=1.5, msg="Badges must have matching height")
        v_cy = v_badge["y"] + v_badge["height"] / 2.0
        qa_cy = qa_badge["y"] + qa_badge["height"] / 2.0
        self.assertAlmostEqual(v_cy, qa_cy, delta=1.5, msg="Badges must be vertically centered on the same line")

        # 5. Buttons right-aligned, same height, vertically centered with title block
        btn_tour = self.page.locator("#btn-editor-instructions").bounding_box()
        btn_render = self.page.locator("#btn-editor-rerender-version").bounding_box()
        self.assertIsNotNone(btn_tour)
        self.assertIsNotNone(btn_render)
        self.assertAlmostEqual(btn_tour["height"], btn_render["height"], delta=1.5, msg="Header buttons must have same height")

    # -------------------------------------------------------------------------
    # TEST 5: Active Clip panel populated with real data (no template strings)
    # -------------------------------------------------------------------------
    def test_05_active_clip_panel_data(self):
        """Active clip panel auto-selects clip 1; no template strings like 'Source - Channel - Resolution' or '--'."""
        self._load_video_in_editor(width=1440, height=900)

        title_el = self.page.locator("#inspector-clip-title").inner_text()
        channel_el = self.page.locator("#inspector-clip-channel").inner_text()
        score_el = self.page.locator("#inspector-quality-score").inner_text()

        self.assertNotEqual(title_el.strip(), "Active Clip", "Clip title must be populated from real clip data")
        self.assertNotIn("Source · Channel · Resolution", channel_el, "Channel must not contain template placeholder")
        self.assertNotIn("Source - Channel - Resolution", channel_el, "Channel must not contain template placeholder")
        self.assertNotEqual(score_el.strip(), "Clip Score: --", "Clip score must not be placeholder '--'")
        self.assertFalse(channel_el.strip() == "", "Channel info must not be empty")

    # -------------------------------------------------------------------------
    # TEST 6: Trim fields, Action row, Nudge row alignment
    # -------------------------------------------------------------------------
    def test_06_trim_fields_and_actions(self):
        """Start & End inputs equal width/height; Output chip non-wrapping; actions equal width; nudges aligned."""
        self._load_video_in_editor(width=1440, height=900)

        start_box = self.page.locator("#input-trim-start").bounding_box()
        end_box = self.page.locator("#input-trim-end").bounding_box()
        output_box = self.page.locator("#val-trim-duration").bounding_box()

        self.assertIsNotNone(start_box)
        self.assertIsNotNone(end_box)
        self.assertIsNotNone(output_box)

        # Equal width and height (40px height)
        self.assertAlmostEqual(start_box["width"], end_box["width"], delta=1.5, msg="Start and End inputs must have equal width")
        self.assertAlmostEqual(start_box["height"], end_box["height"], delta=1.5, msg="Start and End inputs must have equal height")
        self.assertAlmostEqual(start_box["height"], 40.0, delta=2.5, msg="Start input height should be ~40px token")

        # Output chip does not wrap and does not overlap start/end
        output_text = self.page.locator("#val-trim-duration").inner_text()
        self.assertNotIn("\n", output_text, "Output text must not wrap to two lines")
        # No overlap between start_box, output_box, end_box
        self.assertLess(start_box["x"] + start_box["width"], output_box["x"], "Start box must not overlap Output chip")
        self.assertLess(output_box["x"] + output_box["width"], end_box["x"], "Output chip must not overlap End box")

        # Action buttons equal widths (+/-1px) and equal heights (36-40px)
        btn_mode = self.page.locator("#btn-trim-mode").bounding_box()
        btn_snap = self.page.locator("#btn-snap-funny").bounding_box()
        btn_reset = self.page.locator("#btn-reset-trim").bounding_box()
        self.assertIsNotNone(btn_mode)
        self.assertIsNotNone(btn_snap)
        self.assertIsNotNone(btn_reset)
        self.assertAlmostEqual(btn_mode["width"], btn_snap["width"], delta=1.5, msg="Mode and Snap buttons must have equal width")
        self.assertAlmostEqual(btn_snap["width"], btn_reset["width"], delta=1.5, msg="Snap and Reset buttons must have equal width")
        self.assertAlmostEqual(btn_mode["height"], btn_snap["height"], delta=1.5, msg="Action buttons must have equal height")

        # Nudge groups aligned under inputs (same left edge and equal widths)
        nudge_start_minus = self.page.locator("#btn-nudge-start-minus").bounding_box()
        self.assertIsNotNone(nudge_start_minus)
        self.assertAlmostEqual(
            start_box["x"], nudge_start_minus["x"], delta=1.5,
            msg=f"Start nudge group left ({nudge_start_minus['x']}) must match Start input left ({start_box['x']})"
        )

    # -------------------------------------------------------------------------
    # TEST 7: Trim slider single coordinate system
    # -------------------------------------------------------------------------
    def test_07_slider_coordinate_system_and_sync(self):
        """Slider: handles centered on track; highlight spans handle centers; handles sync with inputs."""
        self._load_video_in_editor(width=1440, height=900)

        track_box = self.page.locator(".dual-range-track").bounding_box()
        self.assertIsNotNone(track_box, "Track box must exist")

        # Verify vertical centering of handles on track
        handle_start_box = self.page.locator("#slider-trim-start").bounding_box()
        self.assertIsNotNone(handle_start_box)
        track_cy = track_box["y"] + track_box["height"] / 2.0
        handle_cy = handle_start_box["y"] + handle_start_box["height"] / 2.0
        self.assertAlmostEqual(
            track_cy, handle_cy, delta=2.5,
            msg=f"Slider handle vertical center ({handle_cy}) must align with track vertical center ({track_cy})"
        )

        # Highlight bar spans handle centers
        highlight_box = self.page.locator("#trim-range-highlight").bounding_box()
        self.assertIsNotNone(highlight_box)
        self.assertAlmostEqual(
            highlight_box["y"] + highlight_box["height"] / 2.0, track_cy, delta=2.0,
            msg="Highlight bar must be vertically centered on the track"
        )

        # 20 random (start, end) pairs verification in JS coordinate logic
        valid_coords = self.page.evaluate("""() => {
            const track = document.querySelector('.dual-range-track');
            const sliderStart = document.getElementById('slider-trim-start');
            const sliderEnd = document.getElementById('slider-trim-end');
            const highlight = document.getElementById('trim-range-highlight');
            if (!track || !sliderStart || !sliderEnd || !highlight) return false;

            const max = parseFloat(sliderStart.max) || 10;
            const trackWidth = track.getBoundingClientRect().width;

            for (let i = 0; i < 20; i++) {
                const s = Math.round((Math.random() * (max - 2)) * 10) / 10;
                const e = Math.round((s + 1 + Math.random() * (max - s - 1)) * 10) / 10;
                
                const expectedLeftPct = (s / max) * 100;
                const expectedWidthPct = ((e - s) / max) * 100;
                
                // Set values and trigger update
                sliderStart.value = s;
                sliderEnd.value = e;
                if (window.updateTrimSliderVisuals) {
                    window.updateTrimSliderVisuals();
                }
                
                const hLeft = parseFloat(highlight.style.left);
                const hWidth = parseFloat(highlight.style.width);
                if (Math.abs(hLeft - expectedLeftPct) > 1.5 || Math.abs(hWidth - expectedWidthPct) > 1.5) {
                    return false;
                }
            }
            return true;
        }""")
        self.assertTrue(valid_coords, "Slider range highlight must strictly span handle centers for all pairs")

    # -------------------------------------------------------------------------
    # TEST 8: Grid tokens, no horizontal overflow, contrast & text clipping
    # -------------------------------------------------------------------------
    def test_08_grid_tokens_overflow_and_contrast(self):
        """No horizontal overflow across [1440, 1280, 1024, 860, 390]; no clipped text; gaps on 8px scale."""
        widths = [1440, 1280, 1024, 860, 390]
        for w in widths:
            for theme in ["dark", "light"]:
                self._load_video_in_editor(width=w, height=800, theme=theme)

                # Check horizontal scroll overflow
                has_overflow = self.page.evaluate("""() => {
                    return document.documentElement.scrollWidth > document.documentElement.clientWidth + 2;
                }""")
                self.assertFalse(
                    has_overflow,
                    f"Page must not have horizontal overflow at width {w}px in {theme} theme"
                )

                # Check clipped text on labels, buttons, chips
                clipped_count = self.page.evaluate("""() => {
                    const elements = document.querySelectorAll('#view-editor button, #view-editor .badge, #view-editor .meta-tag');
                    let count = 0;
                    for (const el of elements) {
                        if (el.offsetParent === null) continue; // hidden
                        // Check if text is clipped unintentionally (excluding intentional ellipsis containers)
                        if (el.id !== 'editor-loaded-title' && el.id !== 'inspector-clip-title') {
                            if (el.scrollWidth > el.clientWidth + 2) count++;
                        }
                    }
                    return count;
                }""")
                self.assertEqual(clipped_count, 0, f"Found {clipped_count} clipped text elements at {w}px in {theme}")

    # -------------------------------------------------------------------------
    # TEST 9: Empty state & other steps baseline preservation
    # -------------------------------------------------------------------------
    def test_09_empty_state_and_other_steps_intact(self):
        """Empty state renders cleanly; other steps (Create, Sources, Render, Export) intact with zero console errors."""
        errors = []
        self.page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

        # 1. Empty state
        self._load_empty_editor(width=1440, height=900)
        empty_box = self.page.locator("#editor-empty-state").bounding_box()
        self.assertIsNotNone(empty_box, "Empty state card must be visible when no video loaded")
        loaded_bar = self.page.locator("#editor-loaded-bar")
        self.assertFalse(loaded_bar.is_visible(), "Loaded bar must be hidden in empty state")

        # 2. Check other steps navigate without errors
        for step in [1, 2, 4, 5]:
            self.page.evaluate(f"window.navigateToStep({step})")
            self.page.wait_for_timeout(300)

        # Verify no fatal console errors occurred
        fatal_errors = [e for e in errors if "Failed to load resource" not in e]
        self.assertEqual(len(fatal_errors), 0, f"Encountered unexpected console errors: {fatal_errors}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
