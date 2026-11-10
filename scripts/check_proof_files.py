import os
import sys
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
import json
from qa_check import run_ffprobe_analysis, check_loudness_ebur128

files = [
    'finished/lionreel_cat_proof_short_30s.mp4',
    'finished/lionreel_cat_proof_long_3m.mp4',
    'finished/lionreel_cat_proof_both.mp4',
    'finished/lionreel_cat_proof_both_teaser.mp4'
]

print("=== PROOF RUN VERIFICATION METRICS ===")
for rel_fn in files:
    fn = os.path.join(BASE_DIR, rel_fn)
    if not os.path.exists(fn):
        print(f"MISSING: {fn}")
        continue
    probe = run_ffprobe_analysis(fn)
    v_stream = next((s for s in probe.get("streams", []) if s.get("width")), {})
    dur = float(probe.get("format", {}).get("duration", 0.0))
    size_mb = os.path.getsize(fn) / (1024 * 1024)
    w = v_stream.get("width")
    h = v_stream.get("height")
    fps = v_stream.get("r_frame_rate")
    cs = v_stream.get("color_space")
    cp = v_stream.get("color_primaries")
    ct = v_stream.get("color_transfer")
    
    loudness = check_loudness_ebur128(fn)
    
    print(f"File: {rel_fn}")
    print(f"  Resolution: {w}x{h}")
    print(f"  Duration: {dur:.2f}s")
    print(f"  FPS: {fps}")
    print(f"  Color Tags: cs={cs}, cp={cp}, ct={ct}")
    print(f"  Integrated Loudness: {loudness['integrated_lufs']:.2f} LUFS (target: -14.0 +/- 0.5)")
    print(f"  True Peak: {loudness['true_peak_dbtp']:.2f} dBTP (target: <= -1.0)")
    print(f"  Size: {size_mb:.2f} MB")
