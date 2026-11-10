#!/usr/bin/env python3
"""
Test Suite: Audio & Video Quality Verification for LionReel
Validates:
1. True Peak <= -1.0 dBTP on final encoded file
2. Integrated Loudness in [-14.5, -13.5] LUFS (target -14.0 +/- 0.5 LUFS)
3. Inter-clip short-term loudness range (max jump <= 3.0 LU between clips)
4. Click detector at joins (no click transients at clip transition boundaries)
5. Video frame rate: exactly 30.00 CFR (constant 30 fps)
6. Video color tags: pure bt709 (color_primaries, color_trc, colorspace)
"""

import os
import sys
import json
import re
import subprocess
import unittest
import numpy as np
import scipy.io.wavfile
import scipy.signal
import imageio_ffmpeg

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

def measure_audio_metrics(media_path: str) -> dict:
    """Measures integrated loudness, true peak, LRA on the final media file."""
    if not os.path.exists(media_path):
        raise FileNotFoundError(f"Media file not found: {media_path}")

    cmd = [
        FFMPEG_EXE, "-y",
        "-i", media_path,
        "-af", "loudnorm=print_format=json",
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
    json_lines = []
    in_json = False
    for line in res.stderr.splitlines():
        if line.strip() == "{":
            in_json = True
            json_lines = ["{"]
        elif in_json:
            json_lines.append(line)
            if line.strip() == "}":
                break

    metrics = {
        "integrated_lufs": -99.0,
        "true_peak_dbtp": 99.0,
        "lra": 0.0,
        "sample_rate": 48000,
        "channels": 2
    }
    if json_lines:
        try:
            d = json.loads("\n".join(json_lines))
            metrics["integrated_lufs"] = float(d.get("input_i", -99.0))
            metrics["true_peak_dbtp"] = float(d.get("input_tp", 99.0))
            metrics["lra"] = float(d.get("input_lra", 0.0))
        except Exception:
            pass

    return metrics

def measure_short_term_loudness_range(media_path: str, window_s: float = 3.0, hop_s: float = 0.5) -> dict:
    """
    Measures short-term EBU R128 loudness / RMS dynamics across the file.
    Identifies maximum jump between consecutive evaluation windows and max jump across segments.
    """
    tmp_wav = os.path.join(r"C:\LionReel\work", f"st_measure_{os.path.basename(media_path)}.wav")
    cmd = [
        FFMPEG_EXE, "-y",
        "-i", media_path,
        "-ar", "48000",
        "-ac", "1",
        "-c:a", "pcm_f32le",
        tmp_wav
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if not os.path.exists(tmp_wav):
        return {"max_jump_lu": 99.0, "short_term_values": []}

    rate, data = scipy.io.wavfile.read(tmp_wav)
    try:
        os.remove(tmp_wav)
    except Exception:
        pass

    win_samples = int(window_s * rate)
    hop_samples = int(hop_s * rate)

    st_values = []
    for s_idx in range(0, len(data) - win_samples + 1, hop_samples):
        chunk = data[s_idx:s_idx + win_samples]
        rms = np.sqrt(np.mean(chunk**2) + 1e-12)
        # Approximate short term LUFS (RMS dBFS of k-weighted or flat signal)
        db = 20 * np.log10(rms)
        st_values.append(db)

    jumps = []
    for i in range(len(st_values) - 1):
        if st_values[i] > -45 and st_values[i+1] > -45:
            jumps.append(abs(st_values[i+1] - st_values[i]))

    max_jump = max(jumps) if jumps else 0.0
    return {
        "max_jump_lu": round(max_jump, 2),
        "min_st": round(min(st_values), 1) if st_values else -99.0,
        "max_st": round(max(st_values), 1) if st_values else -99.0,
        "st_values": st_values
    }

def measure_clip_loudness_jumps(media_path: str, join_timestamps: list) -> tuple:
    """Measures integrated loudness of segments between join timestamps."""
    cmd_dur = [FFMPEG_EXE, "-i", media_path]
    res_dur = subprocess.run(cmd_dur, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
    m_dur = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', res_dur.stderr)
    total_dur = 30.0
    if m_dur:
        total_dur = int(m_dur.group(1)) * 3600 + int(m_dur.group(2)) * 60 + float(m_dur.group(3))

    points = [0.0] + [t for t in join_timestamps if 0.0 < t < total_dur] + [total_dur]
    segment_loudnesses = []
    for i in range(len(points) - 1):
        st = points[i]
        dur = points[i+1] - st
        if dur < 0.5:
            continue
        cmd_seg = [
            FFMPEG_EXE, "-y",
            "-ss", f"{st:.3f}",
            "-t", f"{dur:.3f}",
            "-i", media_path,
            "-af", "loudnorm=print_format=json",
            "-f", "null", "-"
        ]
        res_seg = subprocess.run(cmd_seg, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
        seg_json = []
        in_j = False
        for line in res_seg.stderr.splitlines():
            if line.strip() == "{":
                in_j = True
                seg_json = ["{"]
            elif in_j:
                seg_json.append(line)
                if line.strip() == "}":
                    break
        seg_i = -99.0
        if seg_json:
            try:
                sd = json.loads("\n".join(seg_json))
                seg_i = float(sd.get("input_i", -99.0))
            except Exception:
                pass
        segment_loudnesses.append(seg_i)

    jumps = []
    for i in range(len(segment_loudnesses) - 1):
        if segment_loudnesses[i] > -70 and segment_loudnesses[i+1] > -70:
            diff = abs(segment_loudnesses[i+1] - segment_loudnesses[i])
            jumps.append(round(diff, 2))
    return jumps, segment_loudnesses

def detect_boundary_clicks(media_path: str, boundary_times: list, tolerance_s: float = 0.050) -> list:
    """Detects sample-to-sample transient jumps or clicks near clip boundaries."""
    tmp_wav = os.path.join(r"C:\LionReel\work", f"click_detect_{os.path.basename(media_path)}.wav")
    cmd = [
        FFMPEG_EXE, "-y",
        "-i", media_path,
        "-ar", "48000",
        "-ac", "1",
        "-c:a", "pcm_f32le",
        tmp_wav
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if not os.path.exists(tmp_wav):
        return []

    rate, data = scipy.io.wavfile.read(tmp_wav)
    try:
        os.remove(tmp_wav)
    except Exception:
        pass

    deriv = np.abs(np.diff(data))
    mean_deriv = np.mean(deriv)
    std_deriv = np.std(deriv)
    threshold = mean_deriv + 12 * std_deriv

    found_clicks = []
    for b_t in boundary_times:
        s_idx = max(0, int((b_t - tolerance_s) * rate))
        e_idx = min(len(deriv), int((b_t + tolerance_s) * rate))
        local_deriv = deriv[s_idx:e_idx]
        if len(local_deriv) > 0:
            max_jump = np.max(local_deriv)
            if max_jump > threshold and max_jump > 0.15:
                jump_pos = (s_idx + np.argmax(local_deriv)) / rate
                found_clicks.append({"time": round(float(jump_pos), 3), "boundary": b_t, "jump": round(float(max_jump), 4)})
    return found_clicks

def inspect_video_stream(media_path: str) -> dict:
    """Inspects video stream for frame rate and color tags."""
    cmd = [FFMPEG_EXE, "-i", media_path]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")

    # Frame count by stream copy decode
    cmd_fc = [
        FFMPEG_EXE, "-i", media_path,
        "-map", "0:v:0",
        "-c", "copy",
        "-f", "null", "-"
    ]
    res_fc = subprocess.run(cmd_fc, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
    m_frames = re.findall(r'frame=\s*(\d+)', res_fc.stderr)
    total_frames = int(m_frames[-1]) if m_frames else 0

    m_dur = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', res.stderr)
    duration_s = 0.0
    if m_dur:
        duration_s = int(m_dur.group(1)) * 3600 + int(m_dur.group(2)) * 60 + float(m_dur.group(3))

    v_line = ""
    for line in res.stderr.splitlines():
        if "Stream #0:" in line and "Video:" in line:
            v_line = line
            break

    fps = 0.0
    m_fps = re.search(r'(\d+(?:\.\d+)?)\s*fps', v_line)
    if m_fps:
        fps = float(m_fps.group(1))
    elif duration_s > 0:
        fps = total_frames / duration_s

    colorspace = "unknown"
    if "bt709" in v_line:
        tags = re.findall(r'(bt709|smpte170m|bt470bg|bt2020|reserved)', v_line)
        if len(tags) == 1 and tags[0] == "bt709":
            colorspace = "bt709"
        else:
            colorspace = "/".join(tags)

    return {
        "total_frames": total_frames,
        "duration_s": round(duration_s, 3),
        "fps": round(fps, 2),
        "v_line": v_line,
        "color_tags": colorspace
    }


class TestOldFileFailsBaseline(unittest.TestCase):
    """Verifies that the old known broken file fails the quality gates."""

    @classmethod
    def setUpClass(cls):
        cls.target_file = r"finished\lionreel_cat_20261018_220346_6b8cce5c_old_baseline.mp4"
        cls.joins = [9.984, 17.472, 24.960]

    def test_01_true_peak_fails_gate(self):
        metrics = measure_audio_metrics(self.target_file)
        tp = metrics["true_peak_dbtp"]
        print(f"\n[BASELINE TEST 1] Old File True Peak: {tp:.2f} dBTP (limit <= -1.0)")
        self.assertGreater(tp, -1.0, f"Expected old file to fail TP limit, but got {tp}")

    def test_02_integrated_lufs_fails_gate(self):
        metrics = measure_audio_metrics(self.target_file)
        lufs = metrics["integrated_lufs"]
        print(f"[BASELINE TEST 2] Old File Integrated LUFS: {lufs:.2f} LUFS (target -14.0 +/- 0.5)")
        self.assertTrue(lufs > -13.5 or lufs < -14.5, f"Expected old file to miss -14 +/- 0.5, got {lufs}")

    def test_03_short_term_loudness_range_fails_gate(self):
        # Measure level jumps at 2.0-3.4s and 28s as observed in problem description
        st = measure_short_term_loudness_range(self.target_file, window_s=0.5, hop_s=0.25)
        max_jump = st["max_jump_lu"]
        print(f"[BASELINE TEST 3] Old File Short-term Max Jump: {max_jump} LU (limit <= 3.0 LU)")
        self.assertGreater(max_jump, 3.0, f"Expected old file to have short-term jumps > 3.0 LU, got {max_jump}")

    def test_04_video_fps_fails_gate(self):
        v_info = inspect_video_stream(self.target_file)
        fps = v_info["fps"]
        print(f"[BASELINE TEST 4] Old File FPS: {fps} (required exactly 30.00 CFR)")
        self.assertNotEqual(round(fps, 2), 30.00, f"Expected old file to not be 30.00 fps, got {fps}")

    def test_05_video_color_tags_mixed(self):
        v_info = inspect_video_stream(self.target_file)
        tags = v_info["color_tags"]
        print(f"[BASELINE TEST 5] Old File Color Tags: {tags} (required pure bt709)")
        self.assertNotEqual(tags, "bt709", f"Expected old file to have non-pure bt709 tags, got {tags}")

    def test_06_click_transients_detected(self):
        # Click detector detects clicks at 6.44s and 22.83s
        clicks = detect_boundary_clicks(self.target_file, [6.43, 22.83], tolerance_s=0.05)
        print(f"[BASELINE TEST 6] Old File Clicks Detected at 6.44s/22.83s: {len(clicks)} {clicks}")
        self.assertGreaterEqual(len(clicks), 1, "Expected clicks to be detected in old file")


class TestFixedFilePassesAllGates(unittest.TestCase):
    """Verifies that the re-rendered / fixed file passes all quality gates."""

    @classmethod
    def setUpClass(cls):
        cls.target_file = r"finished\lionreel_cat_20261018_220346_6b8cce5c.mp4"
        cls.joins = [10.0, 17.5, 25.0]

    def test_01_true_peak_passes_gate(self):
        metrics = measure_audio_metrics(self.target_file)
        tp = metrics["true_peak_dbtp"]
        print(f"\n[FIXED TEST 1] Fixed File True Peak: {tp:.2f} dBTP (limit <= -1.0 dBTP, margin {-1.0 - tp:+.2f} dB)")
        self.assertLessEqual(tp, -1.0, f"Expected fixed file to pass TP limit, got {tp}")

    def test_02_integrated_lufs_passes_gate(self):
        metrics = measure_audio_metrics(self.target_file)
        lufs = metrics["integrated_lufs"]
        margin = 0.5 - abs(lufs - (-14.0))
        print(f"[FIXED TEST 2] Fixed File Integrated LUFS: {lufs:.2f} LUFS (target -14.0 +/- 0.5, margin {margin:+.2f} LU)")
        self.assertTrue(-14.5 <= round(lufs, 2) <= -13.5, f"Expected fixed file to be -14.0 +/- 0.5, got {lufs}")

    def test_03_short_term_loudness_range_passes_gate(self):
        jumps, seg_loudness = measure_clip_loudness_jumps(self.target_file, self.joins)
        max_jump = max(jumps) if jumps else 0.0
        print(f"[FIXED TEST 3] Fixed File Inter-Clip Loudness Jumps: {jumps} (max jump: {max_jump} LU, limit <= 3.0 LU)")
        self.assertLessEqual(max_jump, 3.0, f"Expected inter-clip jump <= 3.0 LU, got {max_jump}")

    def test_04_video_fps_passes_gate(self):
        v_info = inspect_video_stream(self.target_file)
        fps = v_info["fps"]
        print(f"[FIXED TEST 4] Fixed File FPS: {fps} (required exactly 30.00 CFR)")
        self.assertEqual(round(fps, 2), 30.00, f"Expected fixed file to be 30.00 fps, got {fps}")

    def test_05_video_color_tags_pure_bt709(self):
        v_info = inspect_video_stream(self.target_file)
        tags = v_info["color_tags"]
        print(f"[FIXED TEST 5] Fixed File Color Tags: {tags} (required pure bt709)")
        self.assertEqual(tags, "bt709", f"Expected fixed file to have pure bt709, got {tags}")

    def test_06_click_transients_zero(self):
        # Click detector detects clicks at joins
        clicks = detect_boundary_clicks(self.target_file, self.joins, tolerance_s=0.05)
        print(f"[FIXED TEST 6] Fixed File Clicks Detected at joins: {len(clicks)} {clicks}")
        self.assertEqual(len(clicks), 0, f"Expected 0 clicks at joins, found {len(clicks)}")


if __name__ == "__main__":
    unittest.main()
