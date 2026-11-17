"""The source guard really compares frames; a guard that crashes is NOT RUN, never a pass."""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import qa_check
from clip_ledger import compute_phash


def make_video(path, value=90):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (320, 240))
    rng = np.random.default_rng(5)
    base = cv2.GaussianBlur(rng.integers(0, 255, (240, 320, 3), dtype=np.uint8), (0, 0), 3)
    for _ in range(60):
        vw.write(base)
    vw.release()
    return base


def test_guard_matches_a_blocked_frame(tmp_path, monkeypatch):
    frame = make_video(tmp_path / "v.mp4")
    cap = cv2.VideoCapture(str(tmp_path / "v.mp4"))
    ok, first = cap.read()
    cap.release()
    blocked = tmp_path / "blocked.json"
    blocked.write_text(json.dumps({"blocked_hashes": [{"phash": compute_phash(first)}]}))
    monkeypatch.setattr(qa_check, "BLOCKED_SOURCES_PATH", str(blocked))
    res = qa_check.check_source_guard(str(tmp_path / "v.mp4"))
    assert "error" not in res, res
    assert res["passed"] is False and res["blocked_match"] is True


def test_guard_that_crashes_is_not_run(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked.json"
    blocked.write_text(json.dumps({"blocked_hashes": [{"phash": "not-a-hash"}]}))
    monkeypatch.setattr(qa_check, "BLOCKED_SOURCES_PATH", str(blocked))
    monkeypatch.setattr(qa_check.cv2, "VideoCapture", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert qa_check.check_source_guard(str(tmp_path / "missing.mp4"))["passed"] is None
