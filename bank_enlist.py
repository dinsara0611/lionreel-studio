"""
LIONREEL STUDIO — BANK GROWTH & ENLISTMENT ENGINE (SHORTAGE FIX 2)
Fixes the bank growth bug:
- Coalesces repeated identical growth notifications into a single event
- Evaluates newly verified windows immediately
- Logs exact rejection reason if a new window cannot be enlisted
"""

import os
from typing import Dict, Any, List

class BankGrowthManager:
    def __init__(self, initial_count: int = 0):
        self.last_count = initial_count
        self.last_event_time = 0.0

    def update_count(self, count: int):
        self.last_count = count

    def handle_growth(self, current_count: int) -> Dict[str, Any]:
        """
        Deduplicates identical growth counts into one event.
        Returns should_enlist=True only on genuine positive growth.
        """
        if current_count > self.last_count:
            growth = current_count - self.last_count
            prev = self.last_count
            self.last_count = current_count
            return {
                "should_enlist": True,
                "growth": growth,
                "prev_count": prev,
                "new_count": current_count
            }
        return {
            "should_enlist": False,
            "growth": 0,
            "prev_count": self.last_count,
            "new_count": current_count,
            "reason": "IDENTICAL_OR_NO_GROWTH"
        }

def evaluate_candidate_for_enlistment(
    cand: Dict[str, Any],
    job_id: str,
    animal_type: str,
    ledger,
    selected_clips: List[Dict[str, Any]],
    target_clips_count: int = 4,
    allow_reuse: bool = False
) -> Dict[str, Any]:
    """
    Evaluates whether a candidate can be enlisted right now, or logs the exact reason why not.
    """
    cid = cand.get("clip_id")
    src = cand.get("source_id") or os.path.basename(str(cand.get("source_url_or_path") or ""))
    src_base = os.path.splitext(src)[0].lower()
    st = float(cand.get("start_s") or 0.0)
    en = float(cand.get("end_s") or (st + 7.5))

    # 1. Rejection memory check
    is_rej, rej_reason = ledger.is_window_rejected_by_overlap(src_base, st, en)
    if is_rej:
        return {"usable": False, "reason": f"OVERLAPS_REJECTED_WINDOW: {rej_reason}"}

    # 2. Reuse off: never a moment already in a finished video. Cooldown only orders choices,
    # so during a shortage a fresh window from a recent source is still allowed.
    if not allow_reuse:
        is_used, used_reason = ledger.is_window_used_in_production(src_base, st, en, channel=animal_type, exclude_job_id=job_id)
        if is_used:
            return {"usable": False, "reason": f"ALREADY_USED: {used_reason}"}

    # 3. 50% max clips per source
    max_per_source = max(1, target_clips_count // 2)
    curr_from_source = sum(
        1 for c in selected_clips
        if os.path.splitext(os.path.basename(str(c.get("source_id") or c.get("source_url_or_path") or "")))[0].lower() == src_base
    )
    if curr_from_source >= max_per_source:
        return {"usable": False, "reason": f"SOURCE_CAP_EXCEEDED: already using {curr_from_source}/{max_per_source} clips from '{src_base}'"}

    # 4. 3.0s spacing between windows of same source
    for prev in selected_clips:
        p_src = os.path.splitext(os.path.basename(str(prev.get("source_id") or prev.get("source_url_or_path") or "")))[0].lower()
        if p_src == src_base:
            p_st = float(prev.get("start_s") or 0.0)
            p_en = float(prev.get("end_s") or (p_st + 7.5))
            if not (st - p_en >= 3.0 or p_st - en >= 3.0):
                return {"usable": False, "reason": f"TOO_CLOSE_TO_EXISTING_CLIP: [{st:.1f}-{en:.1f}] overlaps/is within 3.0s of [{p_st:.1f}-{p_en:.1f}]"}

    return {"usable": True, "reason": "OK", "candidate": cand}
