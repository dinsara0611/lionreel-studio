"""A cat wider than the vertical crop is refused while planning, before a 20-30 s render."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import auto_reframe


def test_old_feasibility_check_is_gone():
    src = open(auto_reframe.__file__, encoding="utf-8").read()
    assert "1.95 * float(orig_w)" not in src
    assert re.search(r"PET_WIDER_THAN_CROP \* float\(crop_w\)", src)


def test_threshold_matches_the_clip_gate():
    import qa_check
    # the clip gate calls a pet cut off when it reaches within 2% of both edges: 96% of the width
    assert abs(auto_reframe.PET_WIDER_THAN_CROP - (1 - 2 * qa_check.CUT_OFF_EDGE)) < 1e-9


def test_crash_label_is_not_used_for_a_waiting_stop():
    js = open(os.path.join(os.path.dirname(__file__), "..", "gui", "app.js"), encoding="utf-8").read()
    assert 'data.exitCode === 3' in js and '"NEEDS_FOOTAGE"' in js


import cv2
import numpy as np
import pytest


class WideCat:
    """Detector that reports one cat of a fixed share of the 320 px analysis width."""
    def __init__(self, share):
        self.share = share

    def detect(self, frame, conf_threshold=0.2, include_objects=False):
        w = frame.shape[1]
        bw = w * self.share
        x1 = (w - bw) / 2
        return [{"box": [x1, 40, x1 + bw, 170], "center": (w / 2, 105), "class_name": "cat", "conf": 0.9}]


@pytest.fixture(scope="module")
def landscape(tmp_path_factory):
    path = tmp_path_factory.mktemp("wide") / "src.mp4"
    rng = np.random.default_rng(4)
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (1920, 1080))
    for _ in range(300):
        vw.write(rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8))
    vw.release()
    return str(path)


def test_cat_wider_than_the_crop_is_refused_while_planning(landscape):
    # crop is 608 of 1920 px (32%); this cat is 50% of the frame
    plan = auto_reframe.AutoReframeEngine(detector=WideCat(0.50)).plan_reframe(
        landscape, 1.0, 7.5, animal_mode="cat", layout_mode="smart_crop", allow_slide=False)
    assert plan["status"] == "reject" and "PET_WIDER_THAN_FRAME" in plan["reason"], plan.get("reason")


def test_cat_that_fits_the_crop_is_not_refused_for_width(landscape):
    plan = auto_reframe.AutoReframeEngine(detector=WideCat(0.20)).plan_reframe(
        landscape, 1.0, 7.5, animal_mode="cat", layout_mode="smart_crop", allow_slide=False)
    assert "PET_WIDER_THAN_FRAME" not in str(plan.get("reason"))
