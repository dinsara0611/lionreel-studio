"""The wizard shows only what is real: no made-up sources, licences or clip lists, and no duplicated functions."""
import os
import re

GUI = os.path.join(os.path.dirname(__file__), "..", "gui")


def read(name):
    with open(os.path.join(GUI, name), "r", encoding="utf-8") as f:
        return f.read()


def test_no_function_is_declared_twice():
    # A second declaration silently replaces the first: that left the source list blank
    names = re.findall(r"^(?:async )?function ([A-Za-z0-9_]+)", read("app.js"), flags=re.M)
    twice = sorted({n for n in names if names.count(n) > 1})
    assert twice == []


def test_no_made_up_sources_or_licences():
    js = read("app.js")
    assert re.search(r"const CURATED_SOURCES = \[\];", js)
    for invented in ("CC-BY 4.0", "CC Archive", "ViralWhiskers", "qualityScore: 9"):
        assert invented not in js, invented


def test_missing_licence_says_not_recorded():
    assert read("app.js").count('clip.license || "not recorded"') + read("app.js").count("clip.license || 'not recorded'") == 2


def test_source_step_shows_the_clip_bank_only():
    html = read("index.html")
    for gone in ("tab-curated", "tab-youtube", "tab-upload", "custom-video-url-input", "hero-btn-sample", "review-clips-grid"):
        assert gone not in html, gone
    for needed in ("source-bank-ready", "source-bank-verdict", "btn-source-bank-add", "job-sheet-ready"):
        assert f'id="{needed}"' in html, needed


def test_clip_bank_numbers_come_from_the_count_function():
    js = read("app.js")
    body = js[js.index("async function renderSourceBank()"):js.index("async function renderJobSheet()")]
    assert "/api/pool?animal=" in body and "counts.usable_now" in body
    assert '"not measured"' in body


def test_engine_is_never_sent_mock_clip_selections():
    js = read("app.js")
    assert 'state.config.SOURCE_MODE = "classic";\n        state.config.SELECTED_CLIPS = [];' in js
    assert 'SOURCE_MODE = "curated"' not in js


def test_messages_do_not_cover_the_wizard_buttons():
    css = read("style.css")
    block = css[css.index(".toast-container {"):]
    block = block[:block.index("}")]
    assert "top:" in block and "bottom:" not in block
