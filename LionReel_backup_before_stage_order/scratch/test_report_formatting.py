candidate_reports = [
    {'candidate': 1, 'source': 'cache_ByH9LuSILxU.mp4', 'score': 0.8, 'sharpness': 608.8, 'result': 'REJECT', 'reason': 'PREDICTED_BAD_FRAMING'},
    {'candidate': 6, 'source': 'cache_ByH9LuSILxU.mp4', 'score': None, 'sharpness': None, 'result': 'REJECT', 'reason': 'WATERMARK (bottom_left: WOA Network logo)'},
    {'candidate': 7, 'source': 'cache_ByH9LuSILxU.mp4', 'score': 0.25, 'sharpness': 1111.9, 'result': 'REJECT', 'reason': 'PREDICTED_BAD_FRAMING'}
]

print(f"{'CANDIDATE':<10} | {'SOURCE':<24} | {'FRAMING SCORE':<14} | {'SHARP':<8} | {'RESULT':<8} | {'REASON'}")
print("-" * 100)
for r in candidate_reports:
    sh_val = r.get("sharpness")
    sh_str = f"{float(sh_val):.1f}" if (sh_val is not None and isinstance(sh_val, (int, float))) else "N/A"
    sc_val = r.get("score")
    sc_str = f"{float(sc_val)*100:<13.1f}%" if (sc_val is not None and isinstance(sc_val, (int, float))) else f"{'N/A':<14}"
    c_cand = r.get("candidate", "-")
    c_src = (r.get("source") or "-")[:24]
    c_res = r.get("result", "-")
    c_reason = r.get("reason", "-")
    print(f"{c_cand:<10} | {c_src:<24} | {sc_str} | {sh_str:<8} | {c_res:<8} | {c_reason}")
print("=" * 100)
print("SUCCESS: Candidate reports formatting works flawlessly with None values!")
