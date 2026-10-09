import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from auto_reframe import AutoReframeEngine
from lion_automate_v97 import ensure_local_source_copy

engine = AutoReframeEngine()
for f in ['cache_8R_7KCtShkU.mp4', 'cache_hY7m5jjJ9mM.mp4', 'cache_SB-qEYVdvXA.mp4', 'sel_yt_1791105357_2.mp4', 'raw_ZXNIiZWklsk_1791108652.f616.mp4']:
    src = os.path.join('raw', f)
    if not os.path.exists(src): continue
    local_src = ensure_local_source_copy(src)
    for start in [2.0, 10.0, 20.0]:
        plan = engine.plan_reframe(local_src, start, 10.0, layout_mode='smart_crop')
        st = plan.get('status')
        sc = plan.get('framing_score', 0.0) * 100
        sh = plan.get('sharpness', 0.0)
        re = plan.get('reason', '')
        print(f"{f} @ {start:4.1f}s -> {st.upper():<6} | Score: {sc:5.1f}% | Sharp: {sh:5.1f} | Reason: {re[:50]}")
