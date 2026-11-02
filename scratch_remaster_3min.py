import os, sys, json, subprocess, shutil
import scipy.io.wavfile
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from lion_automate_v97 import BGM_PATH, FFMPEG_EXE, get_video_duration
from tests.test_audio_video_quality import detect_boundary_clicks, measure_clip_loudness_jumps, measure_audio_metrics, inspect_video_stream

job_id = 'job_real_3min_cat_1792378985'
work_dir = r'C:\LionReel\work\job_real_3min_cat_1792378985'
audio_work_dir = os.path.join(work_dir, 'audio_mastering')
out_dir = os.path.join(BASE_DIR, 'output', job_id)
final_mp4 = os.path.join(out_dir, f'{job_id}.mp4')
raw_assembled = final_mp4

mapping_p = os.path.join(out_dir, f'{job_id}_mapping.json')
with open(mapping_p) as f:
    m = json.load(f)

print("Step 1: Normalizing 24 raw clip WAVs to 48kHz with 2-pass linear loudnorm & 15ms fades...")
faded_wavs = []
for idx in range(24):
    base_wav = os.path.join(audio_work_dir, f'clip_{idx:03d}_raw.wav')
    norm_wav = os.path.join(audio_work_dir, f'clip_{idx:03d}_faded.wav')

    # Read duration
    rate, data = scipy.io.wavfile.read(base_wav)
    exact_dur = len(data) / float(rate)

    # Pass 1 measurement
    cmd_p1 = [
        FFMPEG_EXE, '-i', base_wav,
        '-af', 'loudnorm=I=-18.0:TP=-2.0:LRA=11.0:print_format=json',
        '-f', 'null', '-'
    ]
    res_p1 = subprocess.run(cmd_p1, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
    j_lines = []
    in_j = False
    for line in res_p1.stderr.splitlines():
        if line.strip() == '{':
            in_j = True
            j_lines = ['{']
        elif in_j:
            j_lines.append(line)
            if line.strip() == '}':
                break

    meas_i = -18.0
    meas_tp = -2.0
    meas_lra = 11.0
    meas_thresh = -28.0
    target_offset = 0.0
    if j_lines:
        try:
            m_data = json.loads('\n'.join(j_lines))
            meas_i = float(m_data.get('input_i', -18.0))
            meas_tp = float(m_data.get('input_tp', -2.0))
            meas_lra = float(m_data.get('input_lra', 11.0))
            meas_thresh = float(m_data.get('input_thresh', -28.0))
            target_offset = float(m_data.get('target_offset', 0.0))
        except Exception:
            pass

    # Quiet source protection
    required_gain = -18.0 - meas_i
    effective_target_i = -18.0
    if required_gain > 7.0 or meas_thresh < -38.0 or meas_i < -26.0:
        max_boost = 6.0
        effective_target_i = meas_i + max_boost

    # Pass 2 linear loudnorm + 15ms fades strictly at 48000 Hz
    fade_dur = min(0.015, exact_dur / 4.0)
    out_start = max(0.0, exact_dur - fade_dur)
    af_filters = (
        f"loudnorm=I={effective_target_i:.1f}:TP=-2.0:LRA=11.0:"
        f"measured_I={meas_i:.2f}:measured_TP={meas_tp:.2f}:"
        f"measured_LRA={meas_lra:.2f}:measured_thresh={meas_thresh:.2f}:"
        f"offset={target_offset:.2f}:linear=true,"
        f"afade=t=in:st=0:d={fade_dur:.3f},"
        f"afade=t=out:st={out_start:.3f}:d={fade_dur:.3f}"
    )

    cmd_norm = [
        FFMPEG_EXE, '-y',
        '-i', base_wav,
        '-af', af_filters,
        '-ar', '48000',
        '-ac', '2',
        '-c:a', 'pcm_f32le',
        norm_wav
    ]
    subprocess.run(cmd_norm, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    faded_wavs.append(norm_wav)

print(f"Step 2: Concatenating {len(faded_wavs)} 48kHz faded WAVs...")
pet_track_master = os.path.join(audio_work_dir, f'pet_track_master_{job_id}.wav')
concat_txt = os.path.join(audio_work_dir, f'pet_audio_concat_{job_id}.txt')
with open(concat_txt, 'w', encoding='utf-8') as f_c:
    for tw in faded_wavs:
        f_c.write(f"file '{os.path.abspath(tw)}'\n")

cmd_cat = [
    FFMPEG_EXE, '-y',
    '-f', 'concat', '-safe', '0',
    '-i', concat_txt,
    '-ar', '48000',
    '-ac', '2',
    '-c:a', 'pcm_f32le',
    pet_track_master
]
subprocess.run(cmd_cat, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

print("Step 3: Sidechain ducking BGM music under pet audio...")
mixed_audio = os.path.join(audio_work_dir, f'mixed_audio_{job_id}.wav')
sc_filter = (
    "[1:a]aloop=loop=-1:size=2e+09,volume=0.30[bgm];"
    "[bgm][0:a]sidechaincompress=threshold=0.08:ratio=4:attack=25:release=250[ducked_bgm];"
    "[0:a][ducked_bgm]amix=inputs=2:weights=1.0 0.5:normalize=0,"
    "alimiter=limit=0.841:attack=5:release=50:asc=0:level=disabled[mixed]"
)
cmd_mix = [
    FFMPEG_EXE, '-y',
    '-i', pet_track_master,
    '-i', BGM_PATH,
    '-filter_complex', sc_filter,
    '-map', '[mixed]',
    '-ar', '48000',
    '-ac', '2',
    '-c:a', 'pcm_f32le',
    mixed_audio
]
subprocess.run(cmd_mix, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

print("Step 4: Master 2-pass EBU R128 loudness normalization to -14.0 LUFS with -1.5 dBTP limiter...")
p1_cmd = [
    FFMPEG_EXE, '-i', mixed_audio,
    '-af', 'loudnorm=I=-14.0:TP=-2.0:LRA=11.0:print_format=json',
    '-f', 'null', '-'
]
res1 = subprocess.run(p1_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
json_lines = []
in_json = False
for line in res1.stderr.splitlines():
    if line.strip() == '{':
        in_json = True
        json_lines = ['{']
    elif in_json:
        json_lines.append(line)
        if line.strip() == '}':
            break

mi = "-14.0"
mtp = "-2.0"
mlra = "11.0"
mth = "-24.0"
off = "0.0"
if json_lines:
    try:
        m_js = json.loads('\n'.join(json_lines))
        mi = m_js.get('input_i', '-14.0')
        mtp = m_js.get('input_tp', '-2.0')
        mlra = m_js.get('input_lra', '11.0')
        mth = m_js.get('input_thresh', '-24.0')
        off = m_js.get('target_offset', '0.0')
    except Exception:
        pass

p2_af = (
    f"loudnorm=I=-14.0:TP=-2.0:LRA=11.0:"
    f"measured_I={mi}:measured_TP={mtp}:measured_LRA={mlra}:"
    f"measured_thresh={mth}:offset={off}:linear=true,"
    f"alimiter=limit=0.841:attack=5:release=50:asc=0:level=disabled"
)

master_norm_wav = os.path.join(audio_work_dir, f'master_loudnorm_{job_id}.wav')
cmd_ln = [
    FFMPEG_EXE, '-y',
    '-i', mixed_audio,
    '-af', p2_af,
    '-ar', '48000',
    '-ac', '2',
    '-c:a', 'pcm_f32le',
    master_norm_wav
]
subprocess.run(cmd_ln, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

# Step 5: Exact duration alignment to video frame count
v_dur = get_video_duration(raw_assembled)
cmd_fc = [FFMPEG_EXE, "-i", raw_assembled, "-map", "0:v:0", "-c", "copy", "-f", "null", "-"]
res_fc = subprocess.run(cmd_fc, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
import re
m_fc = re.findall(r'frame=\s*(\d+)', res_fc.stderr)
v_frames = int(m_fc[-1]) if m_fc else int(round(v_dur * 30.0))
target_exact_dur = round(v_frames / 30.0, 3)

cmd_ad = [FFMPEG_EXE, "-i", master_norm_wav]
res_ad = subprocess.run(cmd_ad, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
m_ad = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', res_ad.stderr)
a_dur = int(m_ad.group(1)) * 3600 + int(m_ad.group(2)) * 60 + float(m_ad.group(3)) if m_ad else v_dur

pad_dur = max(0.0, target_exact_dur - a_dur)
master_aligned_wav = os.path.join(audio_work_dir, f"master_aligned_{job_id}.wav")
af_pad = f"apad=pad_dur={pad_dur:.3f}" if pad_dur > 0.001 else "anull"

cmd_pad = [
    FFMPEG_EXE, "-y",
    "-i", master_norm_wav,
    "-af", af_pad,
    "-t", f"{target_exact_dur:.3f}",
    "-ar", "48000",
    "-ac", "2",
    "-c:a", "pcm_f32le",
    master_aligned_wav
]
subprocess.run(cmd_pad, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

print("Step 6: Muxing 48kHz master audio onto assembled video with BT.709 tags...")
master_out_mp4 = os.path.join(work_dir, f"master_audio_{job_id}.mp4")
cmd_mux = [
    FFMPEG_EXE, "-y",
    "-i", raw_assembled,
    "-i", master_aligned_wav,
    "-map", "0:v:0",
    "-map", "1:a:0",
    "-c:v", "copy",
    "-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1",
    "-c:a", "aac", "-b:a", "192k",
    "-movflags", "+faststart",
    master_out_mp4
]
subprocess.run(cmd_mux, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
shutil.copy2(master_out_mp4, final_mp4)

print("Step 7: Measuring all compliance metrics on final master file...")
joins = []
cum = 0.0
for c in m['clips'][:-1]:
    cum += c['duration']
    joins.append(round(cum, 3))

aud = measure_audio_metrics(final_mp4)
v_inf = inspect_video_stream(final_mp4)
jumps, segs = measure_clip_loudness_jumps(final_mp4, joins)
clicks = detect_boundary_clicks(final_mp4, joins, tolerance_s=0.05)

max_jump = max(jumps) if jumps else 0.0

res = {
    'job_id': job_id,
    'master_mp4': final_mp4,
    'duration_s': v_inf['duration_s'],
    'total_frames': v_inf['total_frames'],
    'fps': v_inf['fps'],
    'fps_compliant': bool(abs(v_inf['fps'] - 30.0) < 0.1),
    'color_tags': v_inf['color_tags'],
    'color_compliant': bool(v_inf['color_tags'] == 'bt709'),
    'integrated_lufs': aud['integrated_lufs'],
    'lufs_compliant': bool(-14.5 <= aud['integrated_lufs'] <= -13.5),
    'margin_lufs': round(0.5 - abs(aud['integrated_lufs'] - (-14.0)), 2),
    'true_peak_dbtp': aud['true_peak_dbtp'],
    'tp_compliant': bool(aud['true_peak_dbtp'] <= -1.0),
    'margin_tp': round(-1.0 - aud['true_peak_dbtp'], 2),
    'max_clip_jump_lu': max_jump,
    'jumps_compliant': bool(max_jump <= 3.0),
    'boundary_clicks': len(clicks),
    'clicks_compliant': bool(len(clicks) == 0)
}

result_json_path = os.path.join(BASE_DIR, 'analysis', 'real_3min_job_results.json')
with open(result_json_path, 'w', encoding='utf-8') as f_out:
    json.dump(res, f_out, indent=2)

print(f"\nFinal Remastered Results successfully written to: {result_json_path}")
print(json.dumps(res, indent=2))
