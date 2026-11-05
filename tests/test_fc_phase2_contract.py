"""Full check, Phase 2: every selection reaches the job contract unchanged."""
import pytest

import job_options


def norm(**cfg):
    ok, n, err = job_options.normalize_job_options(cfg)
    assert ok, err
    return n


@pytest.mark.parametrize("seconds,clips", [(30, 4), (45, 6), (60, 8)])
def test_short_lengths(seconds, clips):
    n = norm(type="short", target_duration_s=seconds)
    assert n["target_seconds"] == seconds and n["clips"] == clips and n["ratio"] == "9:16"


def test_length_left_over_from_long_cannot_change_a_short():
    n = norm(type="short", TARGET_CLIPS=4, SHORT_CLIP_SEC=7.5, target_duration_s=300)
    assert n["clips"] == 4 and n["target_seconds"] == 30


def test_short_is_clamped_to_30_60():
    assert norm(type="short", target_duration_s=10)["target_seconds"] == 30
    assert norm(type="short", target_duration_s=300)["target_seconds"] == 60


@pytest.mark.parametrize("stale", ["16:9", "1:1"])
def test_short_ignores_a_leftover_ratio(stale):
    n = norm(type="short", aspect_ratio=stale)
    assert (n["ratio"], n["width"], n["height"]) == ("9:16", 1080, 1920)


@pytest.mark.parametrize("minutes,clips", [(1, 8), (3, 24), (8, 64)])
def test_long_clip_count_is_derived(minutes, clips):
    n = norm(type="long", TARGET_DURATION_MIN=minutes, clips=999)
    assert n["target_seconds"] == minutes * 60 and n["clips"] == clips and n["ratio"] == "16:9"


@pytest.mark.parametrize("ratio,size", [("16:9", (1920, 1080)), ("9:16", (1080, 1920)), ("1:1", (1080, 1080))])
def test_long_ratios(ratio, size):
    n = norm(type="long", TARGET_DURATION_MIN=3, aspect_ratio=ratio)
    assert (n["width"], n["height"]) == size


def test_both_has_a_45s_vertical_teaser_with_its_own_clip_count():
    n = norm(type="both", TARGET_DURATION_MIN=3)
    assert n["ratio"] == "16:9"
    assert n["teaser"] == {"seconds": 45.0, "ratio": "9:16", "resolution": "1080x1920", "clips": 6, "clip_time": 7.5}


def test_reuse_and_shorter_default_off():
    n = norm(type="short")
    assert n["allow_reuse"] is False and n["allow_shorter"] is False


def test_job_config_is_written_once_and_rejects_a_changed_contract(tmp_path):
    n = norm(type="short", target_duration_s=30)
    job_options.load_or_verify_job_config("jobx", n, work_base_dir=str(tmp_path))
    changed = dict(n, clips=8, clip_count=8, clip_time=7.5, target_seconds=60.0)
    with pytest.raises(ValueError):
        job_options.load_or_verify_job_config("jobx", changed, work_base_dir=str(tmp_path))
