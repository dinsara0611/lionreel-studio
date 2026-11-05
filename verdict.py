"""
The one verdict function: PASSED / PASSED WITH WARNINGS / FAILED / NOT RUN.

The engine, report, card and qa_report.json all read calculate_unified_verdict.
A gate that crashed, was skipped or left no result is NOT RUN, and a job with a
NOT RUN gate can never be PASSED.
"""

import os
import re
from typing import Any, Dict, List, Optional

REQUIRED_GATES = (
    "gate_1_stream_specs",
    "gate_1b_duration_contract",
    "gate_1c_clip_count",
    "gate_2_stream_defects",
    "gate_3_broadcast_loudness",
    "gate_4_pet_centering",
    "gate_5_layout_fill",
    "gate_6_watermark_cleanliness",
    "gate_6b_clean_overlays",
    "gate_7_peak_quality",
    "gate_8_real_footage",
    "gate_9_visual_sharpness",
    "gate_10_captions_and_spacing",
)
PASS_VERDICTS = ("PASSED", "PASSED WITH WARNINGS")


def is_pass(verdict: Optional[str]) -> bool:
    return verdict in PASS_VERDICTS


def calculate_clip_diversity_stats(clips: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes footage diversity from the real clip table:
    - Unique sources count
    - Unique source windows / moments (distinct source_id + non-overlapping start/end)
    - Overlap-aware unique footage seconds
    - Repeat share percentage = (total_clips - unique_windows) / total_clips
    - Max uses per window, identifying clips exceeding the 8-use cap.
    """
    if not clips:
        return {
            "total_clips": 0,
            "unique_sources": 0,
            "unique_windows": 0,
            "unique_footage_sec": 0.0,
            "repeat_share_pct": 0.0,
            "max_uses_per_window": 0,
            "over_cap_clips": [],
            "overlapping_windows": []
        }

    total_clips = len(clips)
    sources = set()
    window_uses = {}
    source_intervals = {}
    over_cap_clips = []

    for idx, c in enumerate(clips):
        cid = str(c.get("clip_id") or f"clip_{idx+1}")
        src = str(c.get("source_id") or c.get("source_file") or c.get("source_url_or_path") or "source")
        src_clean = os.path.basename(src).replace("\\", "/")
        sources.add(src_clean)

        start_val = c.get("start_s") if c.get("start_s") is not None else c.get("start")
        end_val = c.get("end_s")
        dur = float(c.get("duration") or c.get("duration_s") or 7.5)
        if start_val is None and "source_window" in c:
            m_win = re.search(r'([\d\.]+)s[–\-]([\d\.]+)s', str(c["source_window"]))
            if m_win:
                start_val = float(m_win.group(1))
                end_val = float(m_win.group(2))

        start = round(float(start_val or 0.0), 1)
        end = round(float(end_val if end_val is not None else (start + dur)), 1)

        explicit_use = c.get("use_count")
        if explicit_use is None:
            m_use = re.search(r'use(\d+)', cid)
            explicit_use = int(m_use.group(1)) if m_use else None

        win_key = (src_clean, start, end)
        if win_key not in window_uses:
            window_uses[win_key] = {"count": 0, "clips": [], "explicit_max_use": 1}
        window_uses[win_key]["count"] += 1
        window_uses[win_key]["clips"].append((idx + 1, cid))
        if explicit_use:
            window_uses[win_key]["explicit_max_use"] = max(window_uses[win_key]["explicit_max_use"], explicit_use)

        if explicit_use and explicit_use > 8:
            over_cap_clips.append(f"{cid} (Clip #{idx+1}) used {explicit_use} times (> 8 cap)")

        if src_clean not in source_intervals:
            source_intervals[src_clean] = []
        source_intervals[src_clean].append((start, end))

    for w_key, info in window_uses.items():
        actual_use = max(info["count"], info["explicit_max_use"])
        if actual_use > 8:
            first_clip = info["clips"][0]
            desc = f"{first_clip[1]} (Clip #{first_clip[0]}) used {actual_use} times (> 8 cap)"
            if not any(first_clip[1] in oc for oc in over_cap_clips):
                over_cap_clips.append(desc)

    total_unique_sec = 0.0
    overlapping_windows = []
    for src, ivals in source_intervals.items():
        if not ivals:
            continue
        sorted_ivals = sorted(ivals, key=lambda x: x[0])
        merged = []
        for s, e in sorted_ivals:
            if not merged:
                merged.append([s, e])
            else:
                prev_s, prev_e = merged[-1]
                if s < prev_e:
                    overlapping_windows.append(f"Source {src}: {s:.1f}–{e:.1f}s overlaps {prev_s:.1f}–{prev_e:.1f}s")
                    merged[-1][1] = max(prev_e, e)
                else:
                    merged.append([s, e])
        for m_s, m_e in merged:
            total_unique_sec += (m_e - m_s)

    unique_windows = len(window_uses)
    repeat_share_pct = round(((total_clips - unique_windows) / float(max(1, total_clips))) * 100.0, 2)
    max_uses = max([max(w["count"], w["explicit_max_use"]) for w in window_uses.values()]) if window_uses else 0

    return {
        "total_clips": total_clips,
        "unique_sources": len(sources),
        "unique_windows": unique_windows,
        "unique_footage_sec": round(total_unique_sec, 1),
        "repeat_share_pct": repeat_share_pct,
        "max_uses_per_window": max_uses,
        "over_cap_clips": over_cap_clips,
        "overlapping_windows": overlapping_windows[:5]
    }


def calculate_unified_verdict(
    qa_data: Optional[Dict[str, Any]] = None,
    clips_table: Optional[List[Dict[str, Any]]] = None,
    job_config: Optional[Dict[str, Any]] = None,
    planner_dec: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Unified Single Source of Truth Verdict Engine across PDF, Viewer, Card, and qa_report.json:
    - FAILED (red): Any hard gate failure (duration +/-1.0s, sharpness floor 150.0 on any clip, centering <85%,
      loudness, defects, watermark, burned-in text, or any window used > 8 times).
    - NOT RUN (amber): Any hard gate that crashed, was skipped, or has missing data. Job CANNOT be PASSED.
    - PASSED WITH WARNINGS (amber): All hard gates passed, but soft warnings exist (repeat share > 30%,
      unique sources < 5, windows used > 3 times, overlapping windows, unknown author).
    - PASSED (green): 100% hard gates ran and passed, 0 soft warnings.
    """
    qa_data = qa_data or {}
    clips_table = clips_table or []
    job_config = job_config or {}
    planner_dec = planner_dec or {}

    gates = qa_data.get("gates", {})
    critical_errors: List[str] = []
    not_run_gates: List[str] = []
    warnings: List[str] = []
    attention_items: List[str] = []

    # No QA data, or a required gate that left no result, can never count as a pass
    if not gates:
        not_run_gates.append("QA did not run: no gate results stored")
        attention_items.append("QA did not run: no gate results stored")
    else:
        for req in REQUIRED_GATES:
            if req not in gates:
                not_run_gates.append(f"{req} was NOT RUN (no result stored)")
                attention_items.append(f"{req}: NOT RUN (no result stored)")

    # 1. Evaluate Diversity & Window Usage Caps
    div_stats = calculate_clip_diversity_stats(clips_table)
    if div_stats["over_cap_clips"]:
        for oc in div_stats["over_cap_clips"]:
            critical_errors.append(f"Window usage cap exceeded: {oc}")
            attention_items.append(f"Window cap exceeded: {oc}")

    # 2. Check Hard Gates
    # Stream specs / ratio
    g1 = gates.get("gate_1_stream_specs", gates.get("Gate 1", {}))
    g1_val = g1.get("passed", g1) if isinstance(g1, dict) else g1
    if g1_val is False:
        critical_errors.append("Stream Specs Gate failed: Video format/resolution did not match contract")
        attention_items.append("Resolution / Aspect ratio mismatch with job contract")

    # Duration contract (+/- 1.0s)
    dur_info = qa_data.get("duration_contract", {})
    dur_diff = dur_info.get("duration_diff_s")
    if dur_diff is not None:
        if float(dur_diff) > 1.0:
            critical_errors.append(f"Gate 1B Duration Contract failed: Delivered diff {dur_diff:.1f}s exceeds +/- 1.0s contract")
            attention_items.append(f"Gate 1B Duration: Diff {dur_diff:.1f}s exceeds +/- 1.0s contract")
    elif "gate_1b_duration_contract" in gates:
        g1b = gates["gate_1b_duration_contract"]
        g1b_passed = g1b.get("passed", g1b) if isinstance(g1b, dict) else g1b
        if g1b_passed is False:
            critical_errors.append("Gate 1B Duration Contract failed")
            attention_items.append("Duration mismatch with requested target contract")

    # Centering (>= 85%)
    centering = qa_data.get("pet_centering", {})
    if centering:
        passed_f = centering.get("passed_frames")
        sampled_f = centering.get("sampled_frames")
        if passed_f is not None and sampled_f is not None and sampled_f > 0:
            c_pct = (float(passed_f) / float(sampled_f)) * 100.0
            if c_pct < 85.0:
                critical_errors.append(f"Gate 4 Pet Centering failed: {c_pct:.1f}% ({passed_f}/{sampled_f} frames) below 85% requirement")
                attention_items.append(f"Gate 4 Centering: {c_pct:.1f}% ({passed_f}/{sampled_f} frames) below 85% requirement")

    # Sharpness (every clip >= 150.0 floor)
    sharpness = qa_data.get("sharpness", {})
    if sharpness:
        min_s = sharpness.get("min_sharpness")
        floor_s = sharpness.get("benchmark_floor", 150.0)
        if min_s is not None and float(min_s) < float(floor_s):
            critical_errors.append(f"Gate 9 Visual Sharpness failed: Min clip sharpness {min_s:.1f} is below floor {floor_s:.1f}")
            attention_items.append(f"Gate 9 Sharpness: Minimum clip sharpness {min_s:.1f} below floor {floor_s:.1f}")

    # Check for crashed, skipped, or not-run gates
    for g_id, g_val in gates.items():
        clean_name = g_id.replace("gate_", "").replace("_", " ").title()
        if isinstance(g_val, dict):
            if g_val.get("skipped") or g_val.get("error") or "Check skipped" in str(g_val.get("reason", "")) or "crashed" in str(g_val.get("reason", "")).lower():
                not_run_gates.append(f"{clean_name} was NOT RUN ({g_val.get('error') or g_val.get('reason') or 'Skipped'})")
                attention_items.append(f"{clean_name}: NOT RUN ({g_val.get('reason') or 'Skipped'})")
            elif g_val.get("passed") is False:
                critical_errors.append(f"{clean_name} failed: {g_val.get('reason', 'Quality threshold not met')}")
        elif g_val is False:
            critical_errors.append(f"{clean_name} failed")
        elif g_val is None:
            why = (qa_data.get("gate_reasons") or {}).get(g_id, "no result")
            not_run_gates.append(f"{clean_name} was NOT RUN ({why})")
            attention_items.append(f"{clean_name}: NOT RUN ({why})")

    # Also check burned_in_text_gate & watermark_gate top-level
    tg = qa_data.get("burned_in_text_gate", {})
    if tg.get("skipped") or "Check skipped" in str(tg.get("reason", "")) or "crashed" in str(tg.get("reason", "")).lower():
        if not any("clean" in nr.lower() or "6b" in nr.lower() for nr in not_run_gates):
            not_run_gates.append(f"Gate 6B Clean Overlays was NOT RUN ({tg.get('reason')})")
            attention_items.append(f"Gate 6B Clean Overlays: NOT RUN ({tg.get('reason')})")

    wm = qa_data.get("watermark_gate", {})
    if wm.get("skipped") or "crashed" in str(wm.get("reason", "")).lower() or "skipped" in str(wm.get("reason", "")).lower():
        if not any("watermark" in nr.lower() for nr in not_run_gates):
            not_run_gates.append(f"Gate 6 Watermark was NOT RUN ({wm.get('reason')})")
            attention_items.append(f"Gate 6 Watermark: NOT RUN ({wm.get('reason')})")

    # Reuse off is a contract: a reused window fails the video, whatever path selected it
    reused = (qa_data.get("freshness") or {}).get("reused_windows") or 0
    if job_config.get("allow_reuse") is False and reused > 0:
        msg = f"Fresh footage failed: {reused} clip(s) reuse earlier videos with Allow reuse off"
        critical_errors.append(msg)
        attention_items.append(msg)

    # 3. Soft Warnings
    rep_pct = div_stats["repeat_share_pct"]
    if rep_pct > 30.0:
        w_msg = f"Repeat share {rep_pct:.1f}% ({div_stats['unique_windows']} unique of {div_stats['total_clips']} clips). Add more sources."
        warnings.append(w_msg)
        attention_items.append(w_msg)

    if div_stats["unique_sources"] > 0 and div_stats["unique_sources"] < 5:
        w_msg = f"Footage diversity: Only {div_stats['unique_sources']} unique sources utilized (Recommended >= 5)."
        warnings.append(w_msg)
        attention_items.append(w_msg)

    if div_stats["max_uses_per_window"] > 3 and div_stats["max_uses_per_window"] <= 8:
        w_msg = f"Repeated windows: Maximum uses per window is {div_stats['max_uses_per_window']}x (Warning: > 3x)."
        warnings.append(w_msg)
        attention_items.append(w_msg)

    if div_stats["overlapping_windows"]:
        w_msg = f"Overlapping moments detected across {len(div_stats['overlapping_windows'])} segments."
        warnings.append(w_msg)
        attention_items.append(w_msg)

    # Check unknown authors
    unknown_author_count = sum(1 for c in clips_table if c.get("uploader") in ("Unknown Author", "Original Creator", "not recorded", None, ""))
    if unknown_author_count > 0:
        w_msg = f"Attribution notice: {unknown_author_count} clip(s) have unverified author names."
        warnings.append(w_msg)
        attention_items.append(w_msg)

    unverified = sum(1 for c in clips_table if c.get("license_status") and c.get("license_status") != "verified")
    if unverified > 0:
        w_msg = f"Licence notice: {unverified} clip(s) come from sources with no verified Creative Commons licence."
        warnings.append(w_msg)
        attention_items.insert(0, w_msg)

    # 4. Final Verdict Determination
    if critical_errors:
        badge = "FAILED"
        color = "red"
        status_label = "FAILED / REJECTED"
        badge_class = "badge-failed"
    elif not_run_gates:
        badge = "NOT RUN"
        color = "amber"
        status_label = "NOT RUN / INCOMPLETE AUDIT"
        badge_class = "badge-warning"
    elif warnings:
        badge = "PASSED WITH WARNINGS"
        color = "amber"
        status_label = "PASSED WITH WARNINGS"
        badge_class = "badge-warning"
    else:
        badge = "PASSED"
        color = "green"
        status_label = "PASSED / BROADCAST READY"
        badge_class = "badge-success"

    # Sort attention items by severity (Errors first, then Not-Run, then Warnings)
    # Deduplicate and cap to max 5 items
    unique_att: List[str] = []
    for item in critical_errors + not_run_gates + attention_items:
        if item not in unique_att:
            unique_att.append(item)

    if not unique_att:
        unique_att.append("All QA gates passed with zero warnings.")

    return {
        "badge": badge,
        "color": color,
        "status_label": status_label,
        "badge_class": badge_class,
        "critical_errors": critical_errors,
        "not_run_gates": not_run_gates,
        "warnings": warnings,
        "attention_items": unique_att[:5],
        "diversity_stats": div_stats
    }
