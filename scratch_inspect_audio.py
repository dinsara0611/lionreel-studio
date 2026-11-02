import subprocess
import json
import imageio_ffmpeg
import os

ff = imageio_ffmpeg.get_ffmpeg_exe()
work = r'C:\LionReel\work\lionreel_cat_20261018_220346_6b8cce5c\audio_mastering'

for idx in range(4):
    for kind in ['raw', 'faded']:
        p = os.path.join(work, f"clip_{idx:03d}_{kind}.wav")
        if not os.path.exists(p):
            print(f"clip_{idx:03d}_{kind}: NOT FOUND")
            continue
        cmd = [ff, '-i', p, '-af', 'loudnorm=print_format=json', '-f', 'null', '-']
        res = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
        try:
            j_part = '{' + res.stderr.split('{', 1)[-1].split('}', 1)[0] + '}'
            d = json.loads(j_part)
            print(f"clip_{idx:03d}_{kind}: input_i={d.get('input_i')} input_tp={d.get('input_tp')} input_lra={d.get('input_lra')}")
        except Exception as e:
            print(f"clip_{idx:03d}_{kind}: ERROR {e}")
