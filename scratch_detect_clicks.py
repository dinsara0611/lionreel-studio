import numpy as np
import scipy.io.wavfile

tmp_wav = r"C:\LionReel\work\lionreel_cat_20261018_220346_6b8cce5c\audio_mastering\analyzed_full.wav"
rate, data = scipy.io.wavfile.read(tmp_wav)

# Check 6.44s
s_idx = int(6.43 * rate)
e_idx = int(6.46 * rate)
diff_l = np.diff(data[s_idx:e_idx, 0])
max_jump = np.max(np.abs(diff_l))
jump_pos = (s_idx + np.argmax(np.abs(diff_l))) / rate
print(f"Around 6.44s: max sample-to-sample jump = {max_jump:.4f} at {jump_pos:.5f}s")

# Check 22.83s
s_idx2 = int(22.80 * rate)
e_idx2 = int(22.86 * rate)
diff_l2 = np.diff(data[s_idx2:e_idx2, 0])
max_jump2 = np.max(np.abs(diff_l2))
jump_pos2 = (s_idx2 + np.argmax(np.abs(diff_l2))) / rate
print(f"Around 22.83s: max sample-to-sample jump = {max_jump2:.4f} at {jump_pos2:.5f}s")

# General click detector across whole file:
# Look for sharp transients (sample-to-sample derivative exceeding threshold relative to local envelope)
deriv = np.abs(np.diff(data[:, 0]))
mean_deriv = np.mean(deriv)
std_deriv = np.std(deriv)
threshold = mean_deriv + 12 * std_deriv
click_indices = np.where(deriv > threshold)[0]
print(f"Total potential click points (> 12 std dev): {len(click_indices)}")
click_times = click_indices / rate
# Group clicks within 50ms
grouped = []
for t in click_times:
    if not grouped or (t - grouped[-1]) > 0.05:
        grouped.append(t)
print("Significant click/transient burst times (s):", [round(t, 3) for t in grouped[:25]])
