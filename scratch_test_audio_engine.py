import os
import sys
import json
import subprocess
import numpy as np
import scipy.io.wavfile
import imageio_ffmpeg

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
WORK_DIR = r"C:\LionReel\work\test_audio_fix"
os.makedirs(WORK_DIR, exist_ok=True)

SRC_PATH = r"C:\LionReel\cache\cache_825Za_ZishQ.mp4"
BGM_PATH = r"g:\My Drive\Cat make\assets\funny_bgm.webm"

CLIPS_INFO = [
    {"index": 0, "start_s": 65.0, "dur_s": 10.0},
    {"index": 1, "start_s": 50.5, "dur_s": 7.5},
    {"index": 2, "start_s": 58.5, "dur_s": 7.5},
    {"index": 3, "start_s": 74.5, "dur_s": 5.04}
]

print("=== 1. Extracting 48kHz float PCM for each clip ===")
raw_wavs = []
for c in CLIPS_INFO:
    idx = c["index"]
    out_wav = os.path.join(WORK_DIR, f"clip_{idx:02d}_raw.wav")
    cmd = [
        FFMPEG_EXE, "-y",
        "-ss", f"{c['start_s']:.3f}",
        "-t", f"{c['dur_s']:.3f}",
        "-i", SRC_PATH,
        "-vn",
        "-ar", "48000",
        "-ac", "2",
        "-c:a", "pcm_f32le",
        out_wav
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    raw_wavs.append(out_wav)
    print(f"Extracted clip {idx}: {out_wav} (start={c['start_s']}, dur={c['dur_s']})")

print("\n=== 2. Pass 1: Measure each clip's loudness ===")
clip_measurements = []
for idx, wav_p in enumerate(raw_wavs):
    cmd_p1 = [
        FFMPEG_EXE, "-i", wav_p,
        "-af", "loudnorm=I=-18.0:TP=-2.0:LRA=11.0:print_format=json",
        "-f", "null", "-"
    ]
    res1 = subprocess.run(cmd_p1, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
    j_lines = []
    in_j = False
    for line in res1.stderr.splitlines():
        if line.strip() == "{":
            in_j = True
            j_lines = ["{"]
        elif in_j:
            j_lines.append(line)
            if line.strip() == "}":
                break
    m = json.loads("\n".join(j_lines))
    meas_i = float(m.get("input_i", -99.0))
    meas_tp = float(m.get("input_tp", 99.0))
    meas_lra = float(m.get("input_lra", 0.0))
    meas_thresh = float(m.get("input_thresh", -99.0))
    target_offset = float(m.get("target_offset", 0.0))
    
    # Check if clip is abnormally quiet (source quietness protection)
    # Target is -18.0. Normal gain = -18.0 - meas_i.
    required_gain = -18.0 - meas_i
    is_quiet_source = False
    handling_note = "normal"
    effective_target_i = -18.0

    if required_gain > 7.0 or meas_thresh < -38.0 or meas_i < -25.0:
        is_quiet_source = True
        # Clamp boost to +6.0 dB maximum to prevent noise floor amplification
        max_boost = 6.0
        effective_target_i = meas_i + max_boost
        handling_note = f"quiet_source: clamped boost from +{required_gain:.1f}dB to +{max_boost:.1f}dB (target {effective_target_i:.1f} LUFS)"
        print(f"  [QUIET DETECTED] Clip {idx}: input_i={meas_i:.1f} LUFS, thresh={meas_thresh:.1f} LUFS -> {handling_note}")
    else:
        print(f"  Clip {idx}: input_i={meas_i:.1f} LUFS, TP={meas_tp:.1f} dBTP, thresh={meas_thresh:.1f} LUFS -> target {effective_target_i:.1f} LUFS")

    clip_measurements.append({
        "wav": wav_p,
        "input_i": meas_i,
        "input_tp": meas_tp,
        "input_lra": meas_lra,
        "input_thresh": meas_thresh,
        "target_offset": target_offset,
        "is_quiet_source": is_quiet_source,
        "effective_target_i": effective_target_i,
        "handling_note": handling_note
    })

print("\n=== 3. Pass 2: Apply Two-Pass LINEAR loudnorm + 15ms fades to each clip ===")
normalized_wavs = []
for idx, cm in enumerate(clip_measurements):
    norm_wav = os.path.join(WORK_DIR, f"clip_{idx:02d}_norm.wav")
    rate, data = scipy.io.wavfile.read(cm["wav"])
    exact_dur = len(data) / float(rate)
    fade_d = 0.015
    out_st = max(0.0, exact_dur - fade_d)
    
    tgt_i = cm["effective_target_i"]
    p2_filter = (
        f"loudnorm=I={tgt_i:.1f}:TP=-2.0:LRA=11.0:"
        f"measured_I={cm['input_i']:.2f}:measured_TP={cm['input_tp']:.2f}:"
        f"measured_LRA={cm['input_lra']:.2f}:measured_thresh={cm['input_thresh']:.2f}:"
        f"offset={cm['target_offset']:.2f}:linear=true,"
        f"afade=t=in:st=0:d={fade_d:.3f},"
        f"afade=t=out:st={out_st:.3f}:d={fade_d:.3f}"
    )
    cmd_p2 = [
        FFMPEG_EXE, "-y",
        "-i", cm["wav"],
        "-af", p2_filter,
        "-c:a", "pcm_f32le",
        norm_wav
    ]
    subprocess.run(cmd_p2, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    normalized_wavs.append(norm_wav)

    # Verify per-clip result
    rate_n, data_n = scipy.io.wavfile.read(norm_wav)
    rms_db = 20 * np.log10(np.sqrt(np.mean(data_n**2)) + 1e-12)
    print(f"  Clip {idx} normalized: dur={len(data_n)/rate_n:.3f}s, RMS={rms_db:.1f} dBFS, edge_start={data_n[0,0]:.6f}, edge_end={data_n[-1,0]:.6f}")

print("\n=== 4. Concatenating pet clips into master pet track ===")
concat_txt = os.path.join(WORK_DIR, "pet_concat.txt")
with open(concat_txt, "w", encoding="utf-8") as f:
    for nw in normalized_wavs:
        f.write(f"file '{os.path.abspath(nw)}'\n")

pet_track = os.path.join(WORK_DIR, "pet_track_master.wav")
cmd_cat = [
    FFMPEG_EXE, "-y",
    "-f", "concat", "-safe", "0",
    "-i", concat_txt,
    "-c:a", "pcm_f32le",
    pet_track
]
subprocess.run(cmd_cat, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

print("\n=== 5. Ducking background music under pet track ===")
mixed_wav = os.path.join(WORK_DIR, "mixed_audio.wav")
if os.path.exists(BGM_PATH):
    sc_filter = (
        "[1:a]aloop=loop=-1:size=2e+09,volume=0.30[bgm];"
        "[bgm][0:a]sidechaincompress=threshold=0.08:ratio=4:attack=25:release=250[ducked_bgm];"
        "[0:a][ducked_bgm]amix=inputs=2:weights=1.0 0.5:normalize=0,"
        "alimiter=limit=0.841:attack=5:release=50:asc=0[mixed]"
    )
    cmd_mix = [
        FFMPEG_EXE, "-y",
        "-i", pet_track,
        "-i", BGM_PATH,
        "-filter_complex", sc_filter,
        "-map", "[mixed]",
        "-c:a", "pcm_f32le",
        mixed_wav
    ]
    subprocess.run(cmd_mix, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
else:
    mixed_wav = pet_track

print("\n=== 6. Two-Pass Master Loudness Normalization to -14.0 LUFS with -1.5 dBTP limiter ===")
# Pass 1 on mixed_audio
cmd_m1 = [
    FFMPEG_EXE, "-i", mixed_wav,
    "-af", "loudnorm=I=-14.0:TP=-1.5:LRA=11.0:print_format=json",
    "-f", "null", "-"
]
res_m1 = subprocess.run(cmd_m1, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
j_m1 = []
in_jm = False
for line in res_m1.stderr.splitlines():
    if line.strip() == "{":
        in_jm = True
        j_m1 = ["{"]
    elif in_jm:
        j_m1.append(line)
        if line.strip() == "}":
            break
mm1 = json.loads("\n".join(j_m1))
print("Mixed Audio Pass 1:", mm1)

# Pass 2 with true peak limiter at -1.5 dBTP (limit=0.841)
master_final_wav = os.path.join(WORK_DIR, "master_audio_final.wav")
p2_master = (
    f"loudnorm=I=-14.0:TP=-1.5:LRA=11.0:"
    f"measured_I={mm1.get('input_i')}:measured_TP={mm1.get('input_tp')}:"
    f"measured_LRA={mm1.get('input_lra')}:measured_thresh={mm1.get('input_thresh')}:"
    f"offset={mm1.get('target_offset')}:linear=true,"
    f"alimiter=limit=0.841:attack=5:release=50:asc=0"
)
cmd_m2 = [
    FFMPEG_EXE, "-y",
    "-i", mixed_wav,
    "-af", p2_master,
    "-ar", "48000",
    "-ac", "2",
    "-c:a", "pcm_f32le",
    master_final_wav
]
subprocess.run(cmd_m2, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

print("\n=== 7. Encode to AAC and Mux with Video ===")
# Mux onto assembled video
in_video = r"C:\LionReel\work\lionreel_cat_20261018_220346_6b8cce5c\lionreel_cat_20261018_220346_6b8cce5c.mp4"
out_video = os.path.join(WORK_DIR, "test_output_audio_fixed.mp4")

# Re-encode video with exact 30 CFR and BT.709 tags, muxing the new audio
cmd_mux = [
    FFMPEG_EXE, "-y",
    "-i", in_video,
    "-i", master_final_wav,
    "-map", "0:v:0",
    "-map", "1:a:0",
    "-c:v", "libx264", "-preset", "fast", "-crf", "17",
    "-r", "30", "-fps_mode", "cfr",
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
    "-colorspace", "bt709",
    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
    "-shortest",
    "-movflags", "+faststart",
    out_video
]
subprocess.run(cmd_mux, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

print(f"Created: {out_video} (size: {os.path.getsize(out_video)})")

print("\n=== 8. Measuring Final Encoded File ===")
from test_audio_video_quality import measure_audio_metrics, inspect_video_stream, measure_clip_loudness_jumps, detect_boundary_clicks

metrics = measure_audio_metrics(out_video)
v_info = inspect_video_stream(out_video)
jumps, segs = measure_clip_loudness_jumps(out_video, [10.0, 17.5, 25.0])
clicks = detect_boundary_clicks(out_video, [10.0, 17.5, 25.0])

print(f"Final Integrated LUFS: {metrics['integrated_lufs']:.2f} LUFS (Target: -14.0 +/- 0.5)")
print(f"Final True Peak: {metrics['true_peak_dbtp']:.2f} dBTP (Limit: <= -1.0)")
print(f"Final Video FPS: {v_info['fps']} (Target: 30.00 CFR)")
print(f"Final Video Color Tags: {v_info['color_tags']} (Target: bt709)")
print(f"Segment Loudnesses: {segs}, Max Jump: {max(jumps) if jumps else 0.0:.2f} LU (Limit <= 3.0)")
print(f"Boundary Clicks Detected: {len(clicks)} {clicks}")
