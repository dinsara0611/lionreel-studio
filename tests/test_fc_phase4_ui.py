"""Full check, Phase 4: UI contract, measured in the installed Chrome against the sandbox server."""
import json
import os
import re
import urllib.request

import pytest
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "http://127.0.0.1:8100"


def read(name):
    return open(os.path.join(BASE_DIR, "gui", name), encoding="utf8").read()


@pytest.mark.parametrize("name", ["style.css", "index.html", "app.js"])
def test_no_invalid_font_size_values(name):
    assert not re.search(r"font-size:\s*[\d.]+(?:rem|px)[A-Za-z]", read(name))


def test_no_glass_glow_or_text_shadow():
    css = read("style.css")
    assert "backdrop-filter" not in css and "text-shadow" not in css
    assert "green-glow)" not in re.sub(r"--green-glow:[^;]*;", "", css)


def test_gradients_are_only_scrims_shimmer_and_ticks():
    css = read("style.css")
    fills = [g for g in re.findall(r"gradient\([^;]*", css) if "emerald" in g or "#ef4444" in g or "#d97706" in g]
    assert not fills


def test_tokens_do_not_reference_themselves():
    for name, value in re.findall(r"(--[\w-]+):\s*([^;]+);", read("style.css")):
        assert f"var({name})" != value.strip(), name


def test_animation_does_not_use_transition_all():
    assert not re.search(r"transition:\s*all\b", read("style.css"))


def test_export_markup_ships_no_invented_results():
    html = read("index.html")
    for text in ("QA: PASSED", "Quality PASSED", "100/100 QUALITY", "25.4 MB", "Length OK (+0.0 s)", "Repeat 0%"):
        assert text not in html, text


def test_cleanup_preview_endpoint_works():
    data = json.load(urllib.request.urlopen(URL + "/api/cleanup/preview", timeout=60))
    assert data["success"] is True and data["recycle_bin_default"] is True and data["groups"]


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        pg = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        pg.goto(URL, wait_until="domcontentloaded")
        pg.wait_for_timeout(1200)
        yield pg
        browser.close()


def _shown(pg, element_id):
    """Set visible by the mode switch. The wizard stage holding it may itself be closed."""
    return pg.evaluate("id => { const e = document.getElementById(id); return !!e && e.style.display !== 'none'; }", element_id)


def _mode(pg, mode):
    pg.evaluate("m => { navigateToStep(2); setVideoType(m, false); }", mode)
    pg.wait_for_timeout(250)
    return pg.evaluate("() => ({...state.config})")


def test_one_new_compilation_button(page):
    for step in (1, 2, 4, 5):
        page.evaluate("n => navigateToStep(n)", step)
        page.wait_for_timeout(200)
        if step == 1:
            assert _shown(page, "hero-btn-new") and page.evaluate("() => document.getElementById('hero-btn-new').offsetParent !== null")
        count = page.evaluate("""() => [...document.querySelectorAll('button')].filter(b =>
            b.offsetParent !== null && /new compilation/i.test(b.innerText || '')).length""")
        assert count == 1, f"step {step}: {count}"


def test_short_shows_only_short_controls(page):
    cfg = _mode(page, "short")
    assert cfg["ASPECT_RATIO"] == "9:16"
    assert not _shown(page, "panel-long-video-controls")
    assert not _shown(page, "panel-long-derived-clips")
    assert not _shown(page, "panel-both-teaser-info")
    assert not _shown(page, "btn-format-169") and not _shown(page, "btn-format-11")


def test_each_mode_remembers_and_nothing_leaks(page):
    _mode(page, "long")
    page.evaluate("() => { setFormat('1:1', false); state.config.TARGET_DURATION_MIN = 3; }")
    short = _mode(page, "short")
    assert short["ASPECT_RATIO"] == "9:16" and short["TARGET_CLIPS"] * short["SHORT_CLIP_SEC"] <= 60
    long_again = _mode(page, "long")
    assert long_again["ASPECT_RATIO"] == "1:1" and float(long_again["TARGET_DURATION_MIN"]) == 3


def test_long_clip_count_is_read_only_and_derived(page):
    cfg = _mode(page, "long")
    assert _shown(page, "panel-long-derived-clips") and not _shown(page, "panel-short-clips-count")
    assert cfg["TARGET_CLIPS"] == round(float(cfg["TARGET_DURATION_MIN"]) * 60 / float(cfg["SHORT_CLIP_SEC"]))


def test_both_shows_the_teaser_note(page):
    _mode(page, "both")
    assert _shown(page, "panel-both-teaser-info") and _shown(page, "panel-long-video-controls")


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_no_horizontal_scroll_and_13px_floor(page, width, theme):
    page.set_viewport_size({"width": width, "height": 860})
    page.evaluate("t => applyTheme(t)", theme)
    for step in range(1, 6):
        page.evaluate("n => navigateToStep(n)", step)
        page.wait_for_timeout(200)
        res = page.evaluate("""() => ({
          scroll: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          small: [...document.querySelectorAll('.workspace-view.active *')].filter(e => e.offsetParent !== null
              && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())
              && parseFloat(getComputedStyle(e).fontSize) < 13).map(e => e.tagName + '.' + e.className).slice(0, 5)})""")
        assert not res["scroll"], f"step {step}"
        assert not res["small"], f"step {step}: {res['small']}"


def test_card_shows_stored_verdict_word_for_word(page):
    res = page.evaluate("""() => ['PASSED WITH WARNINGS', 'PASSED', 'PASSED — READY FOR UPLOAD', 'FAILED', 'REJECTED — X', 'NOT RUN', '', null]
        .map(normalizeVerdict)""")
    assert res == ["PASSED WITH WARNINGS", "PASSED", "PASSED", "FAILED", "FAILED", "NOT RUN", "NOT RUN", "NOT RUN"]


def test_no_card_logic_invents_a_quality_pass():
    js = read("app.js")
    assert 'target.overall_passed !== false' not in js
    assert '"QA: PASSED"' not in js and '"Quality PASSED"' not in js


def test_ledger_panel_shows_one_count_and_colombo_time(page):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.evaluate("() => navigateToStep(1)")
    page.wait_for_timeout(1200)
    page.wait_for_function("() => document.getElementById('pool-cycle-badge').innerText.includes('Colombo')", timeout=5000)
    assert "Colombo" in page.inner_text("#pool-cycle-badge")
    assert "usable now" in page.inner_text("#pool-usage-text")


def test_new_compilation_button_stays_inside_the_header(page):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.evaluate("() => { document.getElementById('topbar-activity-text').innerText = 'Burn safe-zone captions & master audio ducking and more'; }")
    box = page.evaluate("() => document.getElementById('btn-header-new').getBoundingClientRect().right")
    assert box <= 1280


def test_no_css_uppercase_labels():
    assert "text-transform: uppercase" not in read("style.css")


def test_cleanup_select_all(page):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.evaluate("""() => {
        document.getElementById('modal-safe-cleanup').style.display = 'flex';
        _safeCleanupPreviewData = {groups: []};
        document.getElementById('cleanup-groups-list').innerHTML = `
          <input type=checkbox class=cleanup-group-checkbox data-count=2 data-bytes=10 checked>
          <input type=checkbox class=cleanup-group-checkbox data-count=3 data-bytes=20>
          <input type=checkbox class=cleanup-group-checkbox data-count=0 data-bytes=0 disabled>`;
        updateSafeCleanupSelectionSummary();
    }""")
    state = "() => [...document.querySelectorAll('.cleanup-group-checkbox')].map(c => c.checked)"
    assert page.evaluate("() => document.getElementById('cleanup-select-all').indeterminate")
    page.check("#cleanup-select-all")
    assert page.evaluate(state) == [True, True, False]
    assert "5 file" in page.inner_text("#cleanup-selected-summary")
    page.uncheck("#cleanup-select-all")
    assert page.evaluate(state) == [False, False, False]
    page.evaluate("() => { document.getElementById('modal-safe-cleanup').style.display = 'none'; }")


def test_library_select_all_and_delete_selected(page):
    calls = []
    fake = {"files": [{"name": "a.mp4", "sizeBytes": 1048576, "url": "/finished/a.mp4"}, {"name": "b.mp4", "sizeBytes": 2097152, "url": "/finished/b.mp4"}],
            "total_count": 2, "real_count": 2, "test_count": 0}
    if True:
        ctx = page.context.browser.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        pg.route("**/api/finished*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(fake)))

        def on_delete(route):
            calls.append(json.loads(route.request.post_data)["filename"])
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"success": True}))
        pg.route("**/api/delete-file*", on_delete)
        pg.goto(URL, wait_until="domcontentloaded")
        pg.wait_for_timeout(1800)
        pg.evaluate("() => { navigateToStep(1); loadFinishedProjects(); }")
        pg.wait_for_selector("#recent-projects-grid .project-select", state="attached")
        assert pg.is_disabled("#btn-delete-selected")
        pg.check("#library-select-all")
        assert "2 selected" in pg.inner_text("#library-selected-count")
        pg.click("#btn-delete-selected")
        assert "2 videos" in pg.inner_text("#modal-confirm-message") and "Recycle Bin" in pg.inner_text("#modal-confirm-message")
        assert calls == []
        pg.click("#btn-confirm-ok")
        pg.wait_for_timeout(800)
        ctx.close()
    assert calls == ["a.mp4", "b.mp4"]


def test_cleanup_cannot_run_while_scanning(page):
    page.evaluate("""() => {
        document.getElementById('modal-safe-cleanup').style.display = 'flex';
        setSafeCleanupScanning(true);
    }""")
    assert page.is_disabled("#btn-confirm-safe-cleanup") and page.is_disabled("#btn-cleanup-dry-run")
    assert "Scanning" in page.inner_text("#cleanup-selected-summary")
    page.evaluate("() => { setSafeCleanupScanning(false); document.getElementById('modal-safe-cleanup').style.display = 'none'; }")


def test_delete_selected_shows_progress_while_it_runs(page):
    fake = {"files": [{"name": "a.mp4", "sizeBytes": 1048576, "url": "/finished/a.mp4"}, {"name": "b.mp4", "sizeBytes": 2097152, "url": "/finished/b.mp4"}],
            "total_count": 2, "real_count": 2, "test_count": 0}
    ctx = page.context.browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.route("**/api/finished*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(fake)))

    def slow_delete(route):
        import time
        time.sleep(0.5)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"success": True}))
    pg.route("**/api/delete-file*", slow_delete)
    pg.goto(URL, wait_until="domcontentloaded")
    pg.wait_for_timeout(1800)
    pg.evaluate("() => { navigateToStep(1); loadFinishedProjects(); }")
    pg.wait_for_selector("#recent-projects-grid .project-select", state="attached")
    pg.check("#library-select-all")
    pg.click("#btn-delete-selected")
    pg.click("#btn-confirm-ok")
    pg.wait_for_function("() => /Deleting 1 of 2/.test(document.getElementById('btn-delete-selected').innerText)", timeout=3000)
    assert pg.is_disabled("#btn-delete-selected")
    assert pg.evaluate("() => document.querySelector('.project-card.is-working') !== null")
    pg.wait_for_function("() => document.getElementById('btn-delete-selected').innerText.includes('Delete selected')", timeout=8000)
    ctx.close()


def test_motion_uses_only_transform_and_opacity():
    css = read("style.css")
    for block in re.findall(r"@keyframes lr-[\w-]+ \{(.*?)\n\}", css, re.S):
        props = set(re.findall(r"([a-z-]+):", block))
        assert props <= {"opacity", "transform"}, props
    assert "prefers-reduced-motion" in css


def test_step_playhead_travels_to_the_active_step(page):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.evaluate("() => navigateToStep(1)")
    page.wait_for_timeout(600)
    first = page.evaluate("() => document.getElementById('step-playhead').style.transform")
    page.evaluate("() => navigateToStep(4)")
    page.wait_for_timeout(600)
    assert page.evaluate("() => document.getElementById('step-playhead').style.transform") != first


def test_render_timeline_shows_the_real_stage(page):
    page.evaluate("() => navigateToStep(4)")
    page.wait_for_timeout(150)
    page.evaluate("() => updateRenderTimeline(6, 'running')")
    assert page.locator(".render-cell.is-done").count() == 5
    assert page.get_attribute(".render-cell.is-current", "data-stage") == "6"
    page.evaluate("() => updateRenderTimeline(6, 'completed')")
    assert page.locator(".render-cell.is-done").count() == 10


def test_idle_render_says_nothing_is_rendering(page):
    page.evaluate("""() => { navigateToStep(4); applyRenderIdleState({status: 'idle', isRunning: false, isWaiting: false}); }""")
    assert page.inner_text(".render-idle-copy h2") == "Nothing is rendering"
    assert not page.is_visible("#render-headline") and not page.is_visible(".render-stages-card")
    assert page.is_visible("#btn-render-idle-new") and not page.is_visible("#render-percentage-text")
    page.evaluate("() => applyRenderIdleState({status: 'running', isRunning: true})")
    assert page.is_visible("#render-percentage-text")


def test_destructive_actions_are_not_in_the_hero():
    html = read("index.html")
    hero = html[html.index("<!-- Bench: what is being worked on -->"):html.index("<!-- Clip Ledger Pool Status Panel")]
    assert "hero-btn-purge-files" not in hero and "hero-btn-clean-all" not in hero
    assert "library-maintenance" in html and html.count('id="hero-btn-purge-files"') == 1


def test_reel_uses_real_videos_or_empty_frames(page):
    # Read in the same step: the page's own finished-video load may redraw the strip afterwards
    got = page.evaluate("""() => {
        navigateToStep(1);
        state.finishedProjects = [{name: 'x.mp4', thumbnail: '/finished/x.webp'}];
        renderHeroReel();
        const reel = document.getElementById('hero-reel');
        return {
            frames: reel.querySelectorAll('button.film-frame').length,
            empty: reel.querySelectorAll('.film-frame-empty').length,
            height: reel.querySelector('.film-frame-empty').offsetHeight,
            note: document.getElementById('hero-reel-note').innerText,
        };
    }""")
    assert got["frames"] == 1 and got["empty"] == 6
    assert got["height"] > 100
    assert got["note"] == "Latest video"


def test_motion_keyframes_stay_on_transform_and_opacity():
    css = read("style.css")
    for name, block in re.findall(r"@keyframes (lr-[\w-]+) \{(.*?)\n\}", css, re.S):
        assert set(re.findall(r"([a-z-]+):", block)) <= {"opacity", "transform"}, name


def test_render_page_has_no_decorative_pass_ticks():
    html = read("index.html")
    for text in ("quality-checks-grid", "Beat drop synchronized", "1920 60 FPS", "12 Automated Quality Verifications"):
        assert text not in html, text


def test_idle_render_card_has_no_dead_space(page):
    page.evaluate("() => navigateToStep(4)")
    page.wait_for_selector("#render-hero-card.is-idle", timeout=6000)
    gap = page.evaluate("""() => {
        const card = document.getElementById('render-hero-card').getBoundingClientRect();
        const btn = document.getElementById('btn-render-idle-new').getBoundingClientRect();
        return card.bottom - btn.bottom;
    }""")
    assert gap <= 48, gap


def test_top_bar_controls_do_not_touch_at_1440(page):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.evaluate("() => navigateToStep(4)")
    page.wait_for_timeout(300)
    left, step, right = page.evaluate("""() => ['.header-left', '#workflow-stepper', '.header-right'].map(s => {
        const r = document.querySelector(s).getBoundingClientRect();
        return [r.left, r.right];
    })""")
    assert step[0] - left[1] >= 8 and right[0] - step[1] >= 8, (left, step, right)


def test_maintenance_buttons_are_tall_enough_on_a_phone(page):
    ctx = page.context.browser.new_context(viewport={"width": 390, "height": 844})
    pg = ctx.new_page()
    pg.goto(URL, wait_until="domcontentloaded")
    pg.wait_for_timeout(1500)
    pg.evaluate("() => navigateToStep(1)")
    pg.evaluate("() => { document.querySelector('.library-maintenance').open = true; }")
    pg.wait_for_timeout(400)
    heights = pg.evaluate("() => ['hero-btn-purge-files', 'hero-btn-clean-all'].map(i => document.getElementById(i).offsetHeight)")
    ctx.close()
    assert min(heights) >= 44, heights


def test_loading_screen_only_names_steps_it_really_does():
    assert "render tools" not in read("app.js") and "codecs" not in read("index.html").split("STICKY HEADER")[0]


def test_loading_screen_closes_and_marks_all_steps(page):
    ctx = page.context.browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.goto(URL, wait_until="domcontentloaded")
    pg.wait_for_function("() => document.getElementById('app-loading-screen').style.display === 'none'", timeout=8000)
    assert pg.get_attribute("#loading-timeline", "aria-valuenow") == "3"
    assert pg.locator("#loading-timeline .ls-cell.is-done").count() == 3
    assert not pg.is_visible("#loading-error-box")
    ctx.close()


def test_loading_screen_says_so_when_the_server_is_gone(page):
    ctx = page.context.browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.route("**/api/status*", lambda r: r.abort())
    pg.goto(URL, wait_until="domcontentloaded")
    pg.wait_for_selector("#loading-error-box", state="visible", timeout=5000)
    assert "local server" in pg.inner_text("#loading-error-title")
    assert pg.is_visible("#btn-loading-retry")
    pg.wait_for_timeout(1800)
    assert pg.is_visible("#app-loading-screen")
    ctx.close()


@pytest.mark.parametrize("width", [390, 1440, 1921])
def test_film_frame_stops_inside_the_gate(page, width):
    ctx = page.context.browser.new_context(viewport={"width": width, "height": 844})
    pg = ctx.new_page()
    pg.route("**/api/status*", lambda r: r.abort())
    pg.goto(URL, wait_until="domcontentloaded")
    offset = pg.evaluate("""() => {
        const film = document.querySelector('.ls-film');
        film.style.animation = 'none';
        const gate = document.querySelector('.ls-gate').getBoundingClientRect();
        return (gate.left + gate.width / 2 - film.getBoundingClientRect().left) % 110;
    }""")
    assert abs(offset - 55) <= 0.5, offset
    ctx.close()


def test_every_id_in_the_page_is_unique():
    ids = re.findall(r'\bid="([^"$]+)"', read("index.html"))
    assert sorted({i for i in ids if ids.count(i) > 1}) == []


CLIPS = """() => {
    state.selectedClips = [
        {title: 'first clip', trimStart: 1, trimEnd: 6, source_duration: 30},
        {title: 'second clip', trimStart: 2, trimEnd: 7, source_duration: 30},
        {title: 'third clip', trimStart: 3, trimEnd: 8, source_duration: 30},
    ];
    state.activeClipIndex = 0;
    state.trimMode = 'slide';
    document.getElementById('slider-trim-start').max = 30;
    document.getElementById('slider-trim-end').max = 30;
    updateTrimWindow(1, 6, 1);
}"""


def test_trim_nudge_moves_exactly_one_tenth(page):
    page.evaluate(CLIPS)
    page.evaluate("() => document.getElementById('btn-nudge-start-plus').click()")
    assert page.evaluate("() => state.selectedClips[0].trimStart") == pytest.approx(1.1, abs=0.001)


def test_undo_restores_one_step_and_keeps_the_clips(page):
    page.evaluate(CLIPS)
    page.evaluate("""() => {
        state.timelineHistory = [JSON.stringify(state.selectedClips.slice(0, 1)), JSON.stringify(state.selectedClips)];
        document.getElementById('btn-timeline-undo').click();
    }""")
    assert page.evaluate("() => [state.timelineHistory.length, state.selectedClips.length]") == [1, 3]


@pytest.mark.parametrize("button", ["btn-copy-meta-title", "btn-copy-meta-desc", "btn-copy-meta-tags", "btn-copy-meta-all"])
def test_copy_buttons_copy_once(page, button):
    count = page.evaluate("""async (id) => {
        navigateToStep(5);
        await new Promise(r => setTimeout(r, 200));
        setupPlatformDrawerActions();
        let copies = 0;
        const fake = {writeText: () => { copies += 1; return Promise.resolve(); }};
        Object.defineProperty(navigator, 'clipboard', {value: fake, configurable: true});
        for (const f of ['export-meta-title', 'export-meta-desc', 'export-meta-tags']) {
            const el = document.getElementById(f);
            if (el) el.value = 'text';
        }
        document.getElementById(id).click();
        await new Promise(r => setTimeout(r, 100));
        return copies;
    }""", button)
    assert count == 1


def test_new_suggestions_needs_a_video_and_sends_one_request(page):
    ctx = page.context.browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    posts = []
    pg.route("**/metadata/generate*", lambda r: (posts.append(r.request.url), r.fulfill(status=200, content_type="application/json", body="{}")))
    pg.goto(URL, wait_until="domcontentloaded")
    pg.wait_for_function("() => document.getElementById('app-loading-screen').style.display === 'none'", timeout=8000)
    pg.wait_for_timeout(500)
    pg.evaluate("() => { state.currentJobId = null; state.activeFinishedProjectName = null; document.getElementById('btn-meta-generate-fresh').click(); }")
    pg.wait_for_timeout(200)
    assert posts == []
    pg.evaluate("() => { state.currentJobId = 'job_a'; document.getElementById('btn-meta-generate-fresh').click(); }")
    pg.wait_for_timeout(400)
    assert len(posts) == 1
    assert pg.inner_text("#btn-meta-generate-fresh").strip() == "New suggestions"
    ctx.close()


def test_show_test_files_toggles_stay_in_step(page):
    page.evaluate("() => { const t = document.getElementById('toggle-show-test-files-export'); t.checked = true; t.dispatchEvent(new Event('change')); }")
    page.wait_for_timeout(300)
    assert page.evaluate("() => document.getElementById('toggle-show-test-files').checked")
    page.evaluate("() => { const t = document.getElementById('toggle-show-test-files'); t.checked = false; t.dispatchEvent(new Event('change')); }")


def test_maintenance_menu_closes_on_outside_click(page):
    page.evaluate("() => { navigateToStep(1); const m = document.querySelector('.library-maintenance'); m.open = true; document.body.click(); }")
    assert not page.evaluate("() => document.querySelector('.library-maintenance').open")
