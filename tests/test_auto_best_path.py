"""When the footage search runs out, a short job finishes a shorter video by itself if it is still a real short."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lion_automate_v97 as engine


def test_five_of_six_clips_finishes_a_shorter_video():
    # The 23 Nov job stopped at 5 of 6 clips and waited for 50 minutes
    assert engine.auto_shorter_ok(5, 6, 7.5) is True


def test_four_clips_of_seven_and_a_half_seconds_is_still_a_short():
    assert engine.auto_shorter_ok(4, 6, 7.5) is True


def test_too_few_clips_keeps_searching():
    assert engine.auto_shorter_ok(3, 6, 7.5) is False
    assert engine.auto_shorter_ok(4, 6, 5.0) is False   # 20 s is too short


def test_long_videos_are_not_cut_short_automatically():
    assert engine.auto_shorter_ok(20, 40, 7.5) is False


def test_a_complete_job_is_not_touched():
    assert engine.auto_shorter_ok(6, 6, 7.5) is False


def test_the_rule_sits_in_the_shortfall_branch():
    src = open(engine.__file__, encoding="utf-8").read()
    i = src.index("elif (allow_shorter and len(rendered_candidates_pool) >= 2) or auto_shorter_ok(")
    assert "record_shorter_delivery(work_job_dir" in src[i:i + 1500]
