"""Edit order, caption choice and caption timing follow rules a person would use, from measured values only."""
import os
import subprocess
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import human_edit
import lion_automate_v97 as engine

W, H = 270, 480


def write_clip(path, moving, seconds=3, fps=30):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    rng = np.random.default_rng(3)
    base = cv2.GaussianBlur(rng.integers(0, 255, (H, W + 300), dtype=np.uint8), (0, 0), 3)
    for i in range(seconds * fps):
        shift = (i * 6) % 300 if moving else 0
        vw.write(cv2.cvtColor(base[:, shift:shift + W], cv2.COLOR_GRAY2BGR))
    vw.release()
    return str(path)


def test_opening_motion_ranks_a_moving_clip_above_a_still_one(tmp_path):
    still = human_edit.opening_motion(write_clip(tmp_path / "still.mp4", moving=False))
    moving = human_edit.opening_motion(write_clip(tmp_path / "move.mp4", moving=True))
    assert still is not None and moving is not None and moving > still + 1.0


def test_unreadable_clip_is_not_measured(tmp_path):
    assert human_edit.opening_motion(str(tmp_path / "missing.mp4")) is None


def clip(name, src, motion):
    return {"name": name, "source_id": src, "motion": motion}


def names(items):
    return [i["name"] for i in items]


def test_most_active_clip_opens_and_next_most_active_closes():
    items = [clip("a", "s1", 2.0), clip("b", "s2", 9.0), clip("c", "s3", 4.0), clip("d", "s4", 7.0)]
    out = names(human_edit.order_like_an_editor(items))
    assert out[0] == "b" and out[-1] == "d" and sorted(out) == ["a", "b", "c", "d"]


def test_same_source_is_not_back_to_back_when_avoidable():
    # The failed layout seen in a real job: sources A, B, C, B, D, D
    items = [clip("1", "A", 3.0), clip("2", "B", 1.0), clip("3", "C", 2.0),
             clip("4", "B", 1.5), clip("5", "D", 5.0), clip("6", "D", 4.0)]
    out = human_edit.order_like_an_editor(items)
    srcs = [i["source_id"] for i in out]
    assert all(a != b for a, b in zip(srcs, srcs[1:])), srcs
    assert len(out) == 6 and out[0]["name"] == "5"


def test_unmeasured_clips_never_take_the_opening_slot():
    items = [clip("a", "s1", None), clip("b", "s2", 1.0), clip("c", "s3", None)]
    assert names(human_edit.order_like_an_editor(items))[0] == "b"


def test_no_measurements_keeps_every_clip_and_spreads_sources():
    items = [clip("a", "s1", None), clip("b", "s1", None), clip("c", "s2", None)]
    out = human_edit.order_like_an_editor(items)
    assert sorted(names(out)) == ["a", "b", "c"]
    assert [i["source_id"] for i in out] == ["s1", "s2", "s1"]


def test_event_lines_are_never_picked_at_random():
    for _ in range(200):
        cap = engine.get_unique_caption()
        assert not human_edit.is_event_caption(cap), cap
    assert "Nothing to see here, keep scrolling" not in human_edit.general_captions(engine.ENGLISH_CAPTIONS)
    assert len(human_edit.general_captions(engine.ENGLISH_CAPTIONS)) >= 30


def test_first_clip_gets_a_question_hook():
    assert engine.get_unique_caption(hook=True) in human_edit.HOOK_CAPTIONS


def caption_pixels(path, second):
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(second * 30))
    ok, frame = cap.read()
    cap.release()
    assert ok
    band = frame[int(frame.shape[0] * 0.66):int(frame.shape[0] * 0.92)]
    return int((band.min(axis=2) > 235).sum())


def test_caption_leaves_the_screen_after_a_few_seconds(tmp_path):
    src = str(tmp_path / "grey.mp4")
    cmd = [engine.FFMPEG_EXE, "-y", "-f", "lavfi", "-i", "color=c=0x404040:size=1080x1920:rate=30:duration=6",
           "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", src]
    assert subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE).returncode == 0
    out = str(tmp_path / "cap.mp4")
    assert engine.render_safe_zone_caption(src, out, "Main character energy", show_seconds=human_edit.CAPTION_SECONDS)
    assert caption_pixels(out, 1.5) > 500
    assert caption_pixels(out, 5.0) == 0
