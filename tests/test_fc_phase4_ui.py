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
    page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
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
    assert "Colombo" in page.inner_text("#pool-cycle-badge")
    assert "usable now" in page.inner_text("#pool-usage-text")


def test_new_compilation_button_stays_inside_the_header(page):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.evaluate("() => { document.getElementById('topbar-activity-text').innerText = 'Burn safe-zone captions & master audio ducking and more'; }")
    box = page.evaluate("() => document.getElementById('btn-header-new').getBoundingClientRect().right")
    assert box <= 1280


def test_no_css_uppercase_labels():
    assert "text-transform: uppercase" not in read("style.css")
