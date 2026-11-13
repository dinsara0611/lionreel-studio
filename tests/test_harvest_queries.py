"""Harvest asks the platform plain questions, per animal, and does not re-ask about videos it already ruled out."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import harvest_worker as hw
import source_licenses as sl


def test_queries_are_plain_words():
    for animal in ("cat", "dog"):
        for q in hw.harvest_queries(animal, "all", rotate=0):
            assert "creative commons" not in q.lower() and "cc-by" not in q.lower(), q


def test_dog_mode_searches_for_dogs():
    qs = hw.harvest_queries("dog", "all", rotate=0)
    assert qs and all(("dog" in q or "pupp" in q) for q in qs), qs
    assert not any("cat" in q or "kitten" in q for q in qs)


def test_cat_type_queries_come_first():
    qs = hw.harvest_queries("cat", "kitten", rotate=0)
    assert qs[0] == "cute kittens playing" and len(qs) == len(set(qs)) and len(qs) >= 8


def test_rotation_changes_the_first_question_and_keeps_the_set():
    a, b = hw.harvest_queries("cat", "all", rotate=0), hw.harvest_queries("cat", "all", rotate=1)
    assert a[0] != b[0] and sorted(a) == sorted(b)


def record(**kw):
    base = {"status": sl.VERIFIED, "creator": "Someone", "width": 1920, "height": 1080, "duration": 120}
    base.update(kw)
    return base


def test_known_unusable_reasons():
    assert hw.known_unusable(record(), 20.0) == ""
    assert hw.known_unusable(record(width=1280, height=720), 20.0) == "LOW_RESOLUTION"
    assert hw.known_unusable(record(duration=8), 20.0) == "TOO_SHORT"
    assert hw.known_unusable(record(status="unverified"), 20.0) == "NOT_CC_LICENSED"
    assert hw.known_unusable(record(creator=""), 20.0) == "NOT_CC_LICENSED"


def test_a_video_never_looked_up_is_not_ruled_out():
    assert hw.known_unusable({}, 20.0) == ""
    assert hw.known_unusable({"status": sl.VERIFIED, "creator": "x"}, 20.0) == ""


def test_short_sharp_single_moment_clip_is_accepted():
    # Seen in a real harvest: a 30 s 2560x1440 clip was skipped as TOO_SHORT under the old 60 s floor
    assert sl.worth_downloading(record(width=2560, height=1440, duration=30), hw.MIN_SOURCE_SECONDS) == (True, "OK")


def test_long_source_is_sampled_not_scanned():
    # An 11-minute source took a whole 1800 s harvest for 63 windows; now at most 24 windows cover it
    assert hw.source_window_step(60.0) == 10.0
    step = hw.source_window_step(640.0)
    assert step > 10.0 and (640.0 - 12.5) / step <= hw.MAX_WINDOWS_PER_SOURCE + 0.001
    assert hw.MAX_VERIFIED_PER_SOURCE <= 4


def test_harvest_target_is_small():
    # A job 2 clips short used to look for 8 windows (four 4-minute downloads); now 3
    assert hw.harvest_target(1) == 2
    assert hw.harvest_target(2) == 3
    assert hw.harvest_target(6) == 9
    assert hw.harvest_target(0) == 2
    assert hw.RECHECK_MAX_SECONDS <= 60
