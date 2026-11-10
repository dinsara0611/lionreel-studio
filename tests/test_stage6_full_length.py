"""A short bank window must become a full-length clip of real footage, never a long freeze."""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lion_automate_v97 as engine
from bank_enlist import clone_pad_seconds, extended_window


def always_free(a, b):
    return True


def test_short_window_grows_forward():
    assert extended_window(101.42, 106.62, 7.5, 300.0, always_free) == pytest.approx((101.42, 108.92))


def test_grows_backward_when_the_footage_after_is_taken():
    assert extended_window(100.0, 105.0, 7.5, 300.0, lambda a, b: b <= 100.0) == (97.5, 105.0)


def test_grows_backward_at_the_end_of_the_source():
    assert extended_window(100.0, 105.0, 7.5, 106.0, always_free) == (97.5, 105.0)


def test_cannot_grow_when_both_sides_are_blocked():
    assert extended_window(100.0, 105.0, 7.5, 300.0, lambda a, b: False) is None


def test_cannot_grow_past_the_source():
    assert extended_window(1.0, 5.0, 7.5, 6.0, always_free) is None


def test_full_length_window_is_left_alone():
    assert extended_window(10.0, 17.5, 7.5, 300.0, lambda a, b: False) == (10.0, 17.5)


@pytest.mark.parametrize("gap, allow_shorter, padded", [
    (0.03, False, 0.0),    # rounding, nothing to do
    (0.30, False, 0.30),   # a few frames, may pad
    (0.50, False, 0.50),
    (0.51, False, 0.0),    # visible freeze, refused
    (2.42, False, 0.0),    # the failed job: 2.42 s of frozen frames
    (0.30, True, 0.0),     # shorter videos were asked for
])
def test_clone_padding_is_only_a_few_frames(gap, allow_shorter, padded):
    assert clone_pad_seconds(gap, allow_shorter) == padded


class FakeReframer:
    gate_ok = True

    def __init__(self):
        self.planned = []
        self.rendered = []

    def plan_reframe(self, src, start, dur, **kw):
        self.planned.append((start, dur))
        return {"crop_w": 608, "active_box": [0, 0, 1920, 1080], "aspect_ratio": "9:16", "out_w": 1080, "mode": "smart_crop"}

    def early_check_segment_gate(self, *a, **kw):
        return True, ""

    def reframe_segment_ffmpeg(self, src, out, start, dur, plan, **kw):
        self.rendered.append((start, dur))
        with open(out, "wb") as f:
            f.write(b"0" * 20000)
        return True

    def verify_post_crop_gate(self, *a, **kw):
        return self.gate_ok, "Centering: 100.0%, Sharpness: 400.0"


class FakeLedger:
    def __init__(self, blocked=()):
        self.blocked = blocked
        self.rejected = []

    def reject_window(self, *a):
        self.rejected.append(a)

    def is_window_rejected_by_overlap(self, src, a, b):
        return (src, a, b) in self.blocked, ""

    def is_window_used_in_production(self, src, a, b, channel=None, exclude_job_id=None):
        return False, "OK"


def render(tmp_path, monkeypatch, cand, ledger=None, source_dur=300.0):
    monkeypatch.setattr(engine, "ensure_local_source_copy", lambda p: p)
    monkeypatch.setattr(engine, "get_video_duration", lambda p: source_dur)
    host = SimpleNamespace(reframer=FakeReframer(), ledger=ledger or FakeLedger())
    result = engine.LionReelV97Pipeline._render_and_gate_candidate(
        host, cand, str(tmp_path), str(tmp_path), 7.5, "smart_crop", "job1", 0)
    return host, result


def test_failed_job_window_renders_at_full_length(tmp_path, monkeypatch):
    cand = {"clip_id": "c_cat_cache_Fca2befwnFw_101_106", "source_id": "cache_Fca2befwnFw", "animal_type": "cat",
            "source_url_or_path": "C:/cache/cache_Fca2befwnFw.mp4", "start_s": 101.42, "end_s": 106.62}
    host, (ok, _, meta, _) = render(tmp_path, monkeypatch, cand)
    assert ok
    assert host.reframer.rendered == [(101.42, 7.5)]
    assert host.reframer.planned == [(101.42, 7.5)]
    assert meta["dur_s"] == 7.5 and meta["output_dur_s"] == 7.5


def test_stale_plan_for_the_short_window_is_not_reused(tmp_path, monkeypatch):
    stale = {"crop_w": 608, "active_box": [0, 0, 1920, 1080], "aspect_ratio": "9:16", "out_w": 1080, "mode": "smart_crop"}
    cand = {"clip_id": "c1", "source_id": "cache_a", "source_url_or_path": "C:/cache/cache_a.mp4",
            "start_s": 50.0, "end_s": 55.0, "dur_s": 5.0, "plan": stale}
    host, _ = render(tmp_path, monkeypatch, cand)
    assert host.reframer.planned == [(50.0, 7.5)]


def test_failed_grown_clip_does_not_reject_the_short_window(tmp_path, monkeypatch):
    # The real job's window: the footage after it has no cat, so the gate refuses the longer clip.
    # The 5.2 s window it verified earlier is still good.
    monkeypatch.setattr(FakeReframer, "gate_ok", False)
    cand = {"clip_id": "c1", "source_id": "cache_a", "source_url_or_path": "C:/cache/cache_a.mp4",
            "start_s": 50.0, "end_s": 55.0}
    host, (ok, _, meta, ret) = render(tmp_path, monkeypatch, cand)
    assert not ok and meta is None
    assert ret["grown_window"] is True
    assert host.ledger.rejected == []


def test_failed_full_length_clip_is_still_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(FakeReframer, "gate_ok", False)
    cand = {"clip_id": "c1", "source_id": "cache_a", "source_url_or_path": "C:/cache/cache_a.mp4",
            "start_s": 50.0, "end_s": 57.5, "dur_s": 7.5}
    host, (ok, _, _, ret) = render(tmp_path, monkeypatch, cand)
    assert not ok and "grown_window" not in ret
    assert len(host.ledger.rejected) == 1


def test_blocked_footage_stays_short_and_is_not_invented(tmp_path, monkeypatch):
    ledger = FakeLedger(blocked=[("cache_a", 55.0, 57.5), ("cache_a", 47.5, 50.0)])
    cand = {"clip_id": "c1", "source_id": "cache_a", "source_url_or_path": "C:/cache/cache_a.mp4",
            "start_s": 50.0, "end_s": 55.0}
    host, (ok, _, meta, _) = render(tmp_path, monkeypatch, cand, ledger=ledger)
    assert ok and meta["dur_s"] == 5.0


def test_full_length_clip_does_not_ask_for_the_source_length(tmp_path, monkeypatch):
    cand = {"clip_id": "c1", "source_id": "cache_a", "source_url_or_path": "C:/cache/cache_a.mp4",
            "start_s": 10.0, "end_s": 17.5, "dur_s": 7.5}
    host, _ = render(tmp_path, monkeypatch, cand, source_dur=0.0)
    assert host.reframer.rendered == [(10.0, 7.5)]


def test_repeat_clip_is_not_grown(tmp_path, monkeypatch):
    cand = {"clip_id": "c1_r1", "source_id": "cache_a", "source_url_or_path": "C:/cache/cache_a.mp4",
            "start_s": 10.0, "end_s": 15.0, "is_repeat": True}
    host, _ = render(tmp_path, monkeypatch, cand)
    assert host.reframer.rendered == [(10.0, 5.0)]
