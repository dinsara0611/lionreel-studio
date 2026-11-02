import subprocess
import json
import imageio_ffmpeg
import numpy as np
import scipy.io.wavfile
import scipy.signal
import os

ff = imageio_ffmpeg.get_ffmpeg_exe()
src = r"G:\My Drive\Cat make\raw\cache_825Za_ZishQ.mp4"
raw_wav = r"C:\LionReel\work\scratch_src_audio.wav"

cmd = [
    ff, "-y",
    "-ss", "50", "-t", "35",
    "-i", src,
    "-ar", "48000",
    "-ac", "2",
    "-c:a", "pcm_f32le",
    raw_wav
]
subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

rate, data = scipy.io.wavfile.read(raw_wav)
print(f"Source audio: sample_rate={rate}, shape={data.shape}, duration={len(data)/rate:.2f}s")

sample_chunk = data[:, 0]
freqs, psd = scipy.signal.welch(sample_chunk, fs=rate, nperseg=4096)
idx_10k = np.argmin(np.abs(freqs - 10000))
idx_14k = np.argmin(np.abs(freqs - 14000))
idx_15k = np.argmin(np.abs(freqs - 15000))
idx_16k = np.argmin(np.abs(freqs - 16000))
idx_17k = np.argmin(np.abs(freqs - 17000))
idx_20k = np.argmin(np.abs(freqs - 20000))

print(f"PSD at 10 kHz: {10*np.log10(psd[idx_10k]):.1f} dB")
print(f"PSD at 14 kHz: {10*np.log10(psd[idx_14k]):.1f} dB")
print(f"PSD at 15 kHz: {10*np.log10(psd[idx_15k]):.1f} dB")
print(f"PSD at 16 kHz: {10*np.log10(psd[idx_16k]):.1f} dB")
print(f"PSD at 17 kHz: {10*np.log10(psd[idx_17k]):.1f} dB")
print(f"PSD at 20 kHz: {10*np.log10(psd[idx_20k]):.1f} dB")
