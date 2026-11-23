"""A vertical clip where the cat runs off both sides of the frame shows a body part, not the cat."""
import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import qa_check

W, H = 540, 960


class BoxDetector:
    def __init__(self, box):
        self.box = box

    def detect(self, frame, conf_threshold=0.22):
        return [{"box": self.box, "class_name": "cat", "conf": 0.9}]


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("cut") / "clip.mp4"
    rng = np.random.default_rng(2)
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (W, H))
    for i in range(60):
        f = rng.integers(0, 255, (H, W, 3), dtype=np.uint8)
        vw.write(f)
    vw.release()
    return str(path)


def test_cat_wider_than_the_frame_fails(clip):
    ok, reason = qa_check.verify_single_pass_post_crop_gate(clip, detector=BoxDetector((0, 300, W, 900)))
    assert not ok and "PET_CUT_OFF" in reason


def test_whole_cat_inside_the_frame_is_not_cut_off(clip):
    ok, reason = qa_check.verify_single_pass_post_crop_gate(clip, detector=BoxDetector((90, 300, 450, 800)))
    assert "PET_CUT_OFF" not in reason
