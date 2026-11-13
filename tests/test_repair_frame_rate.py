"""After an auto-repair re-assembly the master must be re-timed to exactly 30 fps constant."""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lion_automate_v97 as engine


@pytest.fixture
def drifting_video(tmp_path):
    # 3 s clip whose frame timestamps drift (avg fps ~29.99), as a re-assembled concat can leave it
    out = str(tmp_path / "drift.mp4")
    cmd = [engine.FFMPEG_EXE, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=3",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
           "-vf", "setpts=N/(29.9915*TB)", "-fps_mode", "vfr", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", out]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert res.returncode == 0, res.stderr[-300:]
    return out


def test_drifting_frame_rate_is_retimed_to_constant_30(drifting_video):
    assert engine.video_fps_is_constant_30(drifting_video) is False
    assert engine.make_constant_30fps(drifting_video) is True
    assert engine.video_fps_is_constant_30(drifting_video) is True


def test_unreadable_file_is_not_reported_as_30fps(tmp_path):
    assert engine.video_fps_is_constant_30(str(tmp_path / "missing.mp4")) is None
    assert engine.make_constant_30fps(str(tmp_path / "missing.mp4")) is False
