import subprocess
import json
import imageio_ffmpeg
import numpy as np
import scipy.io.wavfile

ff = imageio_ffmpeg.get_ffmpeg_exe()
mp4_path = r"finished\lionreel_cat_20261018_220346_6b8cce5c.mp4"
tmp_wav = r"C:\LionReel\work\lionreel_cat_20261018_220346_6b8cce5c\audio_mastering\analyzed_full.wav"

cmd = [
    ff, "-y",
    "-i", mp4_path,
    "-ar", "48000",
    "-ac", "2",
    "-c:a", "pcm_f32le",
    tmp_wav
]
subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

rate, data = scipy.io.wavfile.read(tmp_wav)
total_s = len(data) / rate
print(f"Total duration: {total_s:.3f}s")

# Let's compute RMS in 500ms windows
window_size = int(0.5 * rate)
hop_size = int(0.25 * rate)

print("Time (s) | Left RMS (dBFS) | Right RMS (dBFS)")
for start_idx in range(0, len(data) - window_size, hop_size):
    t_sec = start_idx / rate
    chunk = data[start_idx:start_idx + window_size]
    rms_l = np.sqrt(np.mean(chunk[:, 0]**2) + 1e-12)
    rms_r = np.sqrt(np.mean(chunk[:, 1]**2) + 1e-12)
    db_l = 20 * np.log10(rms_l)
    db_r = 20 * np.log10(rms_r)
    # Print interesting ranges
    if (1.5 <= t_sec <= 4.0) or (5.5 <= t_sec <= 7.0) or (9.0 <= t_sec <= 10.5) or (22.0 <= t_sec <= 25.5) or (27.5 <= t_sec <= 30.0):
        print(f"{t_sec:5.2f}s | {db_l:6.1f} dBFS     | {db_r:6.1f} dBFS")
