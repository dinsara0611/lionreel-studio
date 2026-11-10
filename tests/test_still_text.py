"""Gate 6b: burned-in source text is found by what stays still while the footage moves."""
import os
import sys
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lion_automate_v97 as engine
import overlay_text_detector as otd
import qa_check
from overlay_text_detector import check_window_still_text, find_still_text

H, W = 720, 1280


def scene(shift, seed=1):
    """Textured footage that pans by `shift` px per frame."""
    rng = np.random.default_rng(seed)
    base = cv2.GaussianBlur(rng.integers(0, 255, (H, W + 400), dtype=np.uint8), (0, 0), 4)
    base = cv2.normalize(base, None, 40, 200, cv2.NORM_MINMAX)
    return base[:, shift:shift + W].copy()


def caption(img, text="Sound up please", org=(420, 600), scale=1.2):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, 0, 8, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, 255, 3, cv2.LINE_AA)
    return img


def run_of(fn, n=5):
    return [fn(i) for i in range(n)]


def test_caption_over_moving_footage_is_found():
    boxes = find_still_text(run_of(lambda i: caption(scene(i * 25))))
    assert boxes and all(b["letters"] >= 3 for b in boxes)


def test_moving_footage_alone_is_clean():
    assert find_still_text(run_of(lambda i: scene(i * 25))) == []


def test_text_that_moves_with_the_footage_is_not_an_overlay():
    # A printed sign in the scene pans with the camera: not burned in
    assert find_still_text(run_of(lambda i: caption(scene(i * 25), org=(300 + i * 25, 400)))) == []


def test_text_on_blurred_side_bars_is_cropped_away():
    def frame(i):
        f = scene(i * 25)
        bars = cv2.GaussianBlur(scene(0, seed=2), (0, 0), 25)
        f[:, :340] = bars[:, :340]
        f[:, 940:] = bars[:, 940:]
        return caption(f, "Tac cats", org=(60, 200), scale=1.0)
    assert find_still_text(run_of(frame)) == []


def test_still_scene_texture_is_not_text():
    # A sleeping cat on a tripod shot: nothing moves, and nothing is text
    assert find_still_text(run_of(lambda i: scene(0))) == []


def write_video(path, frames, fps=30):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    for g in frames:
        vw.write(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR))
    vw.release()


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    d = tmp_path_factory.mktemp("still_text")
    clean, text = d / "clean.mp4", d / "text.mp4"
    write_video(clean, [scene(i * 3 % 400) for i in range(90)])
    # The caption shows for the last second only, as in the failed job
    write_video(text, [caption(scene(i * 3 % 400)) if i >= 60 else scene(i * 3 % 400) for i in range(90)])
    return str(clean), str(text)


def test_window_with_a_late_caption_fails(videos):
    r = check_window_still_text(videos[1], 0.0, 3.0)
    assert r["passed"] is False and r["text_runs"] >= 1 and r["reason"].startswith("BURNED_IN_SOURCE_TEXT")


def test_clean_window_passes(videos):
    r = check_window_still_text(videos[0], 0.0, 3.0)
    assert r["passed"] is True and r["runs"] >= 3


def test_missing_source_is_not_a_pass():
    assert check_window_still_text("C:/nope/missing.mp4", 0.0, 5.0)["passed"] is None


def test_gate_6b_reads_each_clip_source(videos):
    clips = [{"clip_id": "a", "source_path": videos[0], "start_s": 0.0, "duration": 3.0},
             {"clip_id": "b", "source_abs_path": videos[1], "start_s": 0.0, "dur_s": 3.0}]
    r = qa_check.check_clips_source_text(clips)
    assert r["passed"] is False and "b" in r["reason"] and "a" not in r["reason"].split(":")[-1]
    assert qa_check.check_clips_source_text(clips[:1])["passed"] is True


@pytest.mark.parametrize("clips", [None, [], [{"clip_id": "x", "source_path": "C:/nope.mp4", "start_s": 0, "duration": 5}],
                                   [{"clip_id": "y", "start_s": 0}]])
def test_gate_6b_without_a_readable_source_is_not_run(clips):
    assert qa_check.check_clips_source_text(clips)["passed"] is None


class FakeReframer:
    def plan_reframe(self, *a, **kw):
        return {"crop_w": 608, "active_box": [0, 0, 1920, 1080], "aspect_ratio": "9:16", "out_w": 1080, "mode": "smart_crop"}

    def early_check_segment_gate(self, *a, **kw):
        return True, ""

    def reframe_segment_ffmpeg(self, *a, **kw):
        raise AssertionError("a clip with source text must not be rendered")


class FakeLedger:
    def __init__(self):
        self.rejected = []

    def reject_window(self, *a):
        self.rejected.append(a)

    def is_window_rejected_by_overlap(self, *a):
        return False, ""

    def is_window_used_in_production(self, *a, **kw):
        return False, "OK"


def render(tmp_path, monkeypatch, cand, source_dur=300.0):
    monkeypatch.setattr(engine, "ensure_local_source_copy", lambda p: p)
    monkeypatch.setattr(engine, "get_video_duration", lambda p: source_dur)
    monkeypatch.setattr(otd, "check_window_still_text",
                        lambda *a, **kw: {"passed": False, "reason": "BURNED_IN_SOURCE_TEXT (2/8 frame runs)"})
    host = SimpleNamespace(reframer=FakeReframer(), ledger=FakeLedger())
    out = engine.LionReelV97Pipeline._render_and_gate_candidate(
        host, cand, str(tmp_path), str(tmp_path), 7.5, "smart_crop", "job1", 0)
    return host, out


def test_render_refuses_a_window_with_source_text(tmp_path, monkeypatch):
    cand = {"clip_id": "c1", "source_id": "cache_a", "source_url_or_path": "C:/cache/cache_a.mp4",
            "start_s": 225.0, "end_s": 232.5, "dur_s": 7.5}
    host, (ok, _, meta, ret) = render(tmp_path, monkeypatch, cand)
    assert not ok and meta is None and ret["reason"].startswith("BURNED_IN_SOURCE_TEXT")
    assert host.ledger.rejected == [("C:/cache/cache_a.mp4", 225.0, 232.5, ret["reason"])]


def test_grown_window_with_text_keeps_the_short_bank_window(tmp_path, monkeypatch):
    cand = {"clip_id": "c1", "source_id": "cache_a", "source_url_or_path": "C:/cache/cache_a.mp4",
            "start_s": 50.0, "end_s": 55.0}
    host, (ok, _, _, ret) = render(tmp_path, monkeypatch, cand)
    assert not ok and ret.get("grown_window") is True
    assert host.ledger.rejected == []
