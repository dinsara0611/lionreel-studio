"""Channel marks that stay put for a whole source are found; busy texture and still cameras are not marks."""
import json
import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import persistent_mark as pm

W, H = 640, 360


def scene(seed, sigma=4):
    """A different shot each seed: large soft shapes like real footage, or fine texture when sigma is small."""
    rng = np.random.default_rng(seed)
    if sigma <= 1:
        img = cv2.GaussianBlur(rng.integers(0, 255, (H, W), dtype=np.uint8), (0, 0), sigma)
        return cv2.normalize(img, None, 30, 220, cv2.NORM_MINMAX)
    cells = rng.integers(20, 235, (9, 16), dtype=np.uint8)
    return cv2.GaussianBlur(cv2.resize(cells, (W, H), interpolation=cv2.INTER_NEAREST), (0, 0), sigma * 3)


def with_mark(img, alpha=0.55):
    # A see-through channel name, like the one found on real sources
    over = img.copy()
    cv2.putText(over, "Cozy Cat Corner", (380, 335), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 2, cv2.LINE_AA)
    return cv2.addWeighted(over, alpha, img, 1 - alpha, 0)


def frames_of(n_scenes, per_scene, make):
    out = []
    for s in range(n_scenes):
        for k in range(per_scene):
            out.append(make(s, k))
    return out


def test_see_through_channel_name_over_changing_footage_is_a_mark():
    frames = frames_of(40, 1, lambda s, k: with_mark(scene(s)))
    marks = pm.find_marks_in_frames(frames)
    assert marks, "the channel name must be found"
    x, y, bw, bh = marks[0][:4]
    assert x >= 330 and y >= 280


def test_changing_footage_without_a_mark_is_clean():
    assert pm.find_marks_in_frames(frames_of(40, 1, lambda s, k: scene(s))) == []


def test_busy_texture_in_every_scene_is_not_a_mark():
    # Gravel or paving: dense edges everywhere, never in the same place
    assert pm.find_marks_in_frames(frames_of(40, 1, lambda s, k: scene(s, sigma=1))) == []


def test_still_camera_scene_is_not_a_mark():
    # A tripod shot: the room never moves, only a small subject does
    base = scene(7)

    def frame(s, k):
        f = base.copy()
        cv2.circle(f, (100 + s * 10, 180), 30, 240, -1)
        return f
    assert pm.find_marks_in_frames(frames_of(40, 1, frame)) == []


def test_too_few_frames_is_not_run():
    assert pm.find_marks_in_frames([scene(1)] * 3) is None


def test_missing_source_is_not_a_pass(tmp_path):
    assert pm.check_source_marks(str(tmp_path / "missing.mp4"))["passed"] is None


@pytest.fixture
def marked_video(tmp_path):
    path = tmp_path / "cache_abc.mp4"
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (W, H))
    for s in range(30):
        f = cv2.cvtColor(with_mark(scene(s)), cv2.COLOR_GRAY2BGR)
        for _ in range(15):
            vw.write(f)
    vw.release()
    return str(path)


def test_marked_video_fails_and_the_result_is_remembered(marked_video, tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "_cache_path", lambda: str(tmp_path / "source_marks.json"))
    res = pm.check_source_marks_cached(marked_video)
    assert res["passed"] is False and res["reason"].startswith("CHANNEL_MARK")
    cache = json.loads((tmp_path / "source_marks.json").read_text())
    assert cache["abc"]["passed"] is False
    monkeypatch.setattr(pm, "check_source_marks", lambda p: pytest.fail("a measured source is not measured again"))
    assert pm.check_source_marks_cached(marked_video)["passed"] is False
