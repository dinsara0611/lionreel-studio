"""Auto framing shows a too-wide cat whole on blurred sides, and the final checks judge each clip by its own layout."""
import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import auto_reframe
import qa_check
from test_pet_wider_than_frame import WideCat, landscape  # noqa: F401  (fixture)


def test_auto_shows_a_wide_cat_whole(landscape):
    plan = auto_reframe.AutoReframeEngine(detector=WideCat(0.50)).plan_reframe(
        landscape, 1.0, 7.5, animal_mode="cat", layout_mode="auto", allow_slide=False)
    assert plan["status"] == "pass" and plan["mode"] == "blur_fit", plan.get("reason")


def test_smart_crop_only_still_refuses_a_wide_cat(landscape):
    plan = auto_reframe.AutoReframeEngine(detector=WideCat(0.50)).plan_reframe(
        landscape, 1.0, 7.5, animal_mode="cat", layout_mode="smart_crop", allow_slide=False)
    assert plan["status"] == "reject" and "PET_WIDER_THAN_FRAME" in plan["reason"]


def test_auto_keeps_cropping_a_cat_that_fits(landscape):
    plan = auto_reframe.AutoReframeEngine(detector=WideCat(0.20)).plan_reframe(
        landscape, 1.0, 7.5, animal_mode="cat", layout_mode="auto", allow_slide=False)
    assert plan.get("mode") != "blur_fit"


def test_spans_follow_the_clip_order():
    mapping = [{"clip_index": 2, "duration": 7.5, "crop_mode": "blur_fit"},
               {"clip_index": 1, "duration": 7.5, "crop_mode": "smart_crop"},
               {"clip_index": 3, "duration": 7.65, "crop_mode": "smart_crop"}]
    assert qa_check.blur_fit_spans_from_mapping(mapping) == [(7.5, 15.0)]


@pytest.fixture(scope="module")
def mixed_video(tmp_path_factory):
    """10 s at 1080x1920: first 5 s a sharp strip on blurred bars (whole cat), last 5 s full-frame footage."""
    path = tmp_path_factory.mktemp("mixed") / "mixed.mp4"
    rng = np.random.default_rng(9)
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (1080, 1920))
    for i in range(300):
        full = rng.integers(0, 255, (1920, 1080, 3), dtype=np.uint8)
        if i < 150:
            frame = cv2.GaussianBlur(full, (0, 0), 40)
            frame = cv2.addWeighted(frame, 0.6, np.full_like(frame, 90), 0.4, 0)
            frame[656:1264] = rng.integers(0, 255, (608, 1080, 3), dtype=np.uint8)
        else:
            frame = full
        vw.write(frame)
    vw.release()
    return str(path)


def test_mixed_layout_passes_when_each_clip_is_judged_by_its_own_layout(mixed_video):
    res = qa_check.check_layout_fill(mixed_video, 16, layout_mode="auto", blur_fit_spans=[(0.0, 5.0)])
    assert res["passed"] is True and res["reason"].startswith("AUTO_LAYOUT_VERIFIED"), res


def test_blurred_bars_outside_a_whole_cat_clip_still_fail(mixed_video):
    res = qa_check.check_layout_fill(mixed_video, 16, layout_mode="auto", blur_fit_spans=[])
    assert res["passed"] is False and "BLURRED_BARS" in res["reason"], res
