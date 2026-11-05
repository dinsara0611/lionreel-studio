"""Full check, Phase 3: a gate that did not run can never look like a pass."""
import json
import os
import subprocess

import cv2
import imageio_ffmpeg
import numpy as np
import pytest

import qa_check
import verdict as verdict_mod

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOOD_GATES = {g: True for g in verdict_mod.REQUIRED_GATES}


def _probe(**video):
    v = dict(codec_type="video", width=1080, height=1920, codec_name="h264", profile="High", pix_fmt="yuv420p",
             r_frame_rate="30/1", avg_frame_rate="30/1", color_space="bt709", color_transfer="bt709", color_primaries="bt709")
    v.update(video)
    a = dict(codec_type="audio", codec_name="aac", bit_rate="192000")
    return {"streams": [v, a], "format": {"duration": "30.0", "size": str(40_000_000)}}


def test_all_gates_pass_is_passed():
    assert verdict_mod.calculate_unified_verdict({"gates": dict(GOOD_GATES)}, [], {})["badge"] == "PASSED"


def test_crashed_gate_is_not_run_and_cannot_pass():
    gates = dict(GOOD_GATES, gate_6b_clean_overlays=None)
    v = verdict_mod.calculate_unified_verdict({"gates": gates, "gate_reasons": {"gate_6b_clean_overlays": "Check crashed: boom"}}, [], {})
    assert v["badge"] == "NOT RUN"
    assert not verdict_mod.is_pass(v["badge"])


def test_failed_gate_beats_not_run():
    gates = dict(GOOD_GATES, gate_6b_clean_overlays=None, gate_9_visual_sharpness=False)
    assert verdict_mod.calculate_unified_verdict({"gates": gates}, [], {})["badge"] == "FAILED"


def test_missing_required_gate_is_not_run():
    gates = dict(GOOD_GATES)
    del gates["gate_9_visual_sharpness"]
    assert verdict_mod.calculate_unified_verdict({"gates": gates}, [], {})["badge"] == "NOT RUN"


def test_no_qa_data_is_not_run():
    assert verdict_mod.calculate_unified_verdict({}, [], {})["badge"] == "NOT RUN"


def test_unverified_licence_shows_in_attention():
    clips = [{"uploader": "A", "license_status": "no licence shown", "clip_id": "c1", "source_id": "s", "start_s": 0, "duration": 7}]
    v = verdict_mod.calculate_unified_verdict({"gates": dict(GOOD_GATES)}, clips, {})
    assert v["badge"] == "PASSED WITH WARNINGS"
    assert any("icence" in a for a in v["attention_items"])


def test_report_generator_uses_the_same_function():
    import report_generator
    assert report_generator.calculate_unified_verdict is verdict_mod.calculate_unified_verdict


def test_run_gate_turns_a_crash_into_not_run():
    def boom(*a, **k):
        raise TypeError("unexpected keyword argument 'is_master_with_captions'")
    res = qa_check.run_gate(boom)
    assert res["passed"] is None and res["skipped"] is True and "unexpected keyword" in res["reason"]


def test_defect_check_crash_is_not_a_pass(monkeypatch):
    monkeypatch.setattr(qa_check.imageio_ffmpeg, "get_ffmpeg_exe", lambda: (_ for _ in ()).throw(RuntimeError("no ffmpeg")))
    res = qa_check.run_gate(qa_check.check_black_and_freeze, "missing.mp4")
    assert res["passed"] is None


@pytest.mark.parametrize("bad,word", [
    (dict(r_frame_rate="29/1", avg_frame_rate="29/1"), "frame rate"),
    (dict(avg_frame_rate="82913280/2764427"), "frame rate"),
    (dict(color_primaries="bt470bg"), "color_primaries"),
    (dict(width=1081), "odd"),
    (dict(pix_fmt="yuv444p"), "pixel format"),
    (dict(profile="Main"), "profile"),
])
def test_stream_contract_catches_each_defect(bad, word):
    res = qa_check.check_stream_contract(_probe(**bad), "9:16")
    assert res["passed"] is False and word in res["reason"]


def test_stream_contract_clean_file_passes():
    assert qa_check.check_stream_contract(_probe(), "9:16")["passed"] is True


def test_no_ffprobe_means_not_run_not_an_opencv_guess(monkeypatch):
    monkeypatch.setattr(qa_check.lion_paths, "ffprobe_exe", lambda: "definitely_missing_ffprobe")
    probe = qa_check.run_gate(qa_check.run_ffprobe_analysis, "x.mp4")
    assert qa_check.check_stream_contract(probe)["passed"] is None


def _video(path, dark_blur_second_clip=False, seconds=4):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (1080, 1920))
    rng = np.random.default_rng(1)
    sharp = (rng.random((1920, 1080, 3)) * 255).astype(np.uint8)
    blur = cv2.GaussianBlur(sharp, (151, 151), 0)
    for i in range(seconds * 30):
        w.write(blur if dark_blur_second_clip and 30 <= i < 60 else sharp)
    w.release()


def test_sharpness_checks_every_clip_not_a_median(tmp_path):
    p = tmp_path / "v.mp4"
    _video(p, dark_blur_second_clip=True)
    clips = [{"duration": 1.0} for _ in range(4)]
    res = qa_check.check_clip_sharpness(str(p), clips)
    assert res["passed"] is False and res["failing_count"] == 1


def test_sharpness_without_clip_map_is_not_run(tmp_path):
    p = tmp_path / "v.mp4"
    _video(p)
    assert qa_check.check_clip_sharpness(str(p), None)["passed"] is None


def test_loudness_is_measured_on_the_file_with_ebur128(tmp_path):
    out = tmp_path / "tone.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x240:r=30:d=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-shortest", str(out)], capture_output=True, timeout=60)
    res = qa_check.check_loudness_ebur128(str(out))
    assert res.get("measured_on") == "final_file_ebur128"
    assert isinstance(res["integrated_lufs"], float)


def test_silent_file_loudness_is_not_invented(tmp_path):
    p = tmp_path / "v.mp4"
    _video(p, seconds=1)
    res = qa_check.check_loudness_ebur128(str(p))
    assert res["passed"] is None or res["integrated_lufs"] != -99.0


def test_server_never_defaults_to_a_pass():
    src = open(os.path.join(BASE, "web_server.py"), encoding="utf8").read()
    assert 'qa_data.get("overall_passed", True)' not in src
    assert 'qa_data.get("verdict", "PASSED")' not in src
    assert "quality_score = 96.0" not in src


def test_engine_has_no_hardcoded_gate_success_text():
    assert "passed 10/10 automated QA gates" not in open(os.path.join(BASE, "lion_automate_v97.py"), encoding="utf8").read()


def test_fresh_share_is_not_invented_when_unknown():
    src = open(os.path.join(BASE, "qa_check.py"), encoding="utf8").read()
    assert '"New footage: 100% / Reused from earlier videos: 0%")' not in src
