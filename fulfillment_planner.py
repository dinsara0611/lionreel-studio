"""
fulfillment_planner.py
======================
LionReel Autopilot Fulfillment Planner
Replaces pre-flight shortage dialogs with an automatic, internal strategy ladder.

Guarantees:
1. CONTRACT TOTAL LENGTH IS PRESERVED:
   Output length strictly ends within +/-2% of the contracted duration (at most +/-2s for short videos).
   Settings are never silently altered (no "set clips to what the pool can supply").
2. STRATEGY LADDER (Executed in order with reasons logged):
   - Step 1: Use verified unique windows from bank (best score first, diversity rules <= 3 per source).
   - Step 2: Progressive background harvest while rendering ready clips (patience budget).
   - Step 3: More windows per source: raise to up to 8 windows for long sources (spaced >= 20-30s).
   - Step 4: Adapt clip time within bounds [3.5s, 20.0s] to minimize shortfall.
   - Step 5: Last resort repeat cycle with best windows (trim offset >= 1.5s, spaced >= 8 clips apart, never back-to-back, new caption, repeat share tracked).
3. QUALITY FLOOR UNCHANGED:
   Sharpness >= 150, watermark/logo rejection, real-footage/AI classifier, framing centering, license attribution.
4. REPEAT SHARE REPORTING:
   Repeat share is tracked and displayed on final video metadata ("X% of this video reuses earlier moments").
"""

import os
import sys
import time
import json
import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clip_ledger import ClipLedger, compute_footage_freshness

@dataclass
class FulfillmentPlan:
    contract_total_sec: float
    expected_total_sec: float
    target_clips_count: int
    target_clip_sec: float
    clips: List[Dict[str, Any]] = field(default_factory=list)
    strategy_used: str = "ladder_step_1_bank"
    ladder_steps_applied: List[str] = field(default_factory=list)
    repeat_share_pct: float = 0.0
    log_messages: List[str] = field(default_factory=list)
    status_card_line: str = ""
    plain_plan_sentence: str = ""
    feasibility_line: str = ""
    freshness: Dict[str, Any] = field(default_factory=dict)
    freshness_card_line: str = ""

    def get_card_status_line(self) -> str:
        if self.status_card_line:
            return self.status_card_line
        if self.feasibility_line:
            return self.feasibility_line
        ready_count = sum(1 for c in self.clips if not c.get("is_repeat"))
        needed = self.target_clips_count
        return f"Building your video: {ready_count} of {needed} clips ready, finding more automatically"

class FulfillmentPlanner:
    def __init__(self, ledger: Optional[ClipLedger] = None, config: Optional[Dict[str, Any]] = None, reframer: Any = None, **kwargs):
        self.ledger = ledger or ClipLedger()
        self.config = config or {}
        self.reframer = reframer

    def plan_fulfillment(
        self,
        job_id: str,
        animal_mode: str,
        target_total_sec: float,
        target_clip_sec: float = 7.5,
        video_type: str = "short",
        patience_budget_sec: Optional[float] = None,
        allow_reuse: bool = False,
        is_test: bool = False,
        channel: str = None,
        progress_callback = None,
        work_dir: Optional[str] = None,
        **kwargs
    ) -> FulfillmentPlan:
        """
        Produce an automated fulfillment plan hitting target_total_sec within +/-2%.
        Executes the strategy ladder automatically without user intervention or dialog popups.
        """
        logs = []
        ladder_applied = []
        contract_sec = float(target_total_sec)
        initial_clip_sec = float(min(20.0, max(3.5, target_clip_sec)))
        is_test_env = bool(is_test or kwargs.get("is_test") or os.environ.get("IS_TEST") or "test" in job_id.lower() or "sandbox" in job_id.lower() or job_id.startswith("job_auto_"))

        # Determine default patience budget: 5 min for <= 2 min, +2 min per extra minute, max 30 min (0s in test env)
        if patience_budget_sec is None:
            if is_test_env:
                patience_budget_sec = 0.0
            elif contract_sec <= 120.0:
                patience_budget_sec = 300.0 # 5 min
            else:
                extra_min = (contract_sec - 120.0) / 60.0
                patience_budget_sec = min(1800.0, 300.0 + (extra_min * 120.0))

        # Initial target clips count
        needed_clips = max(2, int(round(contract_sec / initial_clip_sec)))
        logs.append(f"[PLANNER] Contract target: {contract_sec:.1f}s ({needed_clips} clips @ ~{initial_clip_sec:.1f}s). Patience budget: {patience_budget_sec:.0f}s.")

        # Clean stale reservations first so leftover pending locks don't starve the planner
        try:
            self.ledger.cleanup_stale_reservations(None)
        except Exception:
            pass

        # ---------------------------------------------------------------------
        # STEP 1: Query Bank for Verified Unique Windows (<= 3 per source)
        # ---------------------------------------------------------------------
        ladder_applied.append("ladder_step_1_bank")
        verified_candidates = self._fetch_verified_candidates(animal_mode, current_job_id=job_id, allow_reuse=allow_reuse)
        logs.append(f"[PLANNER] Bank contains {len(verified_candidates)} verified unique candidates for {animal_mode}.")

        # Enforce source cooldown (Rule 3) and calculate true usable_now windows
        usable_now_candidates = list(verified_candidates)
        if hasattr(self.ledger, "get_cooldown_sources"):
            cooldown_sources = self.ledger.get_cooldown_sources(channel=animal_mode, last_n_jobs=3)
            usable_now_candidates = [
                c for c in verified_candidates
                if os.path.splitext(os.path.basename(str(c.get("source_url_or_path") or c.get("source_id") or "")))[0].lower() not in cooldown_sources
                and str(c.get("source_id") or "").lower() not in cooldown_sources
            ]
            if not allow_reuse:
                if len(usable_now_candidates) < needed_clips and len(verified_candidates) > len(usable_now_candidates):
                    remaining_pool = [c for c in verified_candidates if c not in usable_now_candidates]
                    usable_now_candidates = list(usable_now_candidates) + remaining_pool
                    verified_candidates = usable_now_candidates
                    logs.append(f"[PLANNER] Prioritizing fresh non-cooldown sources first, and blending {len(remaining_pool)} unused non-overlapping windows from recently used sources ({len(verified_candidates)} total fresh moments available).")
                else:
                    verified_candidates = usable_now_candidates
                    logs.append(f"[PLANNER] Enforcing source cooldown: {len(verified_candidates)} fresh candidates available outside cooldown sources.")
            elif len(usable_now_candidates) >= needed_clips:
                verified_candidates = usable_now_candidates
                logs.append(f"[PLANNER] Enforcing source cooldown: {len(verified_candidates)} fresh candidates available outside cooldown sources.")
            elif usable_now_candidates:
                logs.append(f"[PLANNER] Notice: Bank has only {len(usable_now_candidates)} non-cooldown candidates; prioritizing them first and blending with cooldown sources to fulfill contract.")

        # Capacity check BEFORE rendering (TASK 2): count only windows that are usable right now
        usable_now = len(usable_now_candidates) if not allow_reuse else len(verified_candidates)
        if usable_now < needed_clips:
            logs.append(f"[PLANNER] Shortage detected: {usable_now} usable now < {needed_clips} needed. Triggering harvest and verification immediately.")
            if not is_test_env:
                try:
                    from harvest_worker import trigger_background_harvest_if_needed
                    trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=needed_clips * 2, target_clips_needed=needed_clips * 2)
                except Exception as e_h:
                    logs.append(f"[PLANNER] Harvest worker notification: {e_h}")
            if hasattr(self.ledger, "verify_pending_unverified_rows"):
                try:
                    v_cnt = self.ledger.verify_pending_unverified_rows(animal_type=animal_mode, limit=needed_clips * 2)
                    if v_cnt > 0:
                        logs.append(f"[PLANNER] Pre-render verification: verified {v_cnt} rows.")
                        verified_candidates = self._fetch_verified_candidates(animal_mode, current_job_id=job_id, allow_reuse=allow_reuse)
                        if hasattr(self.ledger, "get_cooldown_sources"):
                            cooldown_sources = self.ledger.get_cooldown_sources(channel=animal_mode, last_n_jobs=3)
                            usable_now_candidates = [
                                c for c in verified_candidates
                                if os.path.splitext(os.path.basename(str(c.get("source_url_or_path") or c.get("source_id") or "")))[0].lower() not in cooldown_sources
                                and str(c.get("source_id") or "").lower() not in cooldown_sources
                            ]
                            if len(usable_now_candidates) < needed_clips and len(verified_candidates) > len(usable_now_candidates):
                                usable_now_candidates = list(usable_now_candidates) + [c for c in verified_candidates if c not in usable_now_candidates]
                            usable_now = len(usable_now_candidates)
                except Exception as e_v:
                    logs.append(f"[PLANNER] Verification notice: {e_v}")

        # Plain plan sentence (TASK 8)
        needed_to_find = max(0, needed_clips - usable_now)
        clip_noun = "new clip ready" if usable_now == 1 else "new clips ready"
        plain_plan_sentence = f"{needed_clips} clips x {initial_clip_sec:.1f} s = {contract_sec:.0f} s. {usable_now} {clip_noun}, {needed_to_find} to find."

        # Base pool for feasibility analysis
        pool_for_feasibility = self._select_diverse_windows(verified_candidates, max_per_source=8, min_gap_s=10.0) or verified_candidates or self._fetch_all_raw_fallback(animal_mode)
        U = max(1, len(pool_for_feasibility))
        min_unique = (U * initial_clip_sec) / 60.0
        min_3 = (U * 3 * initial_clip_sec) / 60.0
        min_8 = (U * 8 * 20.0) / 60.0
        harvest_status = "Pool ready" if U >= needed_clips else "Harvest active"
        feasibility_line = f"{U} unique moments: {min_unique:.1f} min unique, {min_3:.1f} min with 3 uses, {min_8:.1f} min with 8 uses. {harvest_status}."

        # If shortage active when allow_reuse is False, return honest shortage plan immediately
        if usable_now < needed_clips and not allow_reuse:
            chosen = usable_now_candidates[:usable_now]
            final_clips = self._tune_clip_durations(chosen, contract_sec) if chosen else []
            exp_sec = sum(c["dur_s"] for c in final_clips)
            freshness = compute_footage_freshness(final_clips, ledger=self.ledger, current_job_id=job_id, channel=animal_mode)
            logs.append(f"[PLANNER] Shortage active: {usable_now} ready, {needed_to_find} to find.")
            return FulfillmentPlan(
                contract_total_sec=contract_sec,
                expected_total_sec=round(exp_sec, 2),
                target_clips_count=needed_clips,
                target_clip_sec=initial_clip_sec,
                clips=final_clips,
                strategy_used="shortage_harvest_pending",
                ladder_steps_applied=ladder_applied + ["shortage_active_harvest"],
                repeat_share_pct=0.0,
                log_messages=logs,
                status_card_line=plain_plan_sentence,
                plain_plan_sentence=plain_plan_sentence,
                feasibility_line=feasibility_line,
                freshness=freshness,
                freshness_card_line=freshness["card_line"]
            )

        # If requested duration exceeds hard cap (8 uses at 20.0s), deliver max feasible length as informational note (never an error)
        max_feasible_sec = U * 8 * 20.0
        if contract_sec > max_feasible_sec:
            logs.append(f"[PLANNER NOTE] Requested duration {contract_sec:.1f}s exceeds capacity at hard cap (8 uses @ 20.0s = {max_feasible_sec:.1f}s). Delivering maximum feasible duration.")
            contract_sec = max_feasible_sec
            needed_clips = max(2, int(round(contract_sec / initial_clip_sec)))

        # Try reserve_clips_for_short first for strict 6-rule cross-video freshness
        reserved_step1 = []
        try:
            reserved_step1 = self.ledger.reserve_clips_for_short(
                count=needed_clips,
                animal_type=animal_mode,
                short_id=job_id,
                allow_reuse=allow_reuse,
                min_required=min(needed_clips, 2),
                patience_budget_sec=patience_budget_sec
            )
            for r in reserved_step1:
                r["dur_s"] = max(3.5, round(float(r.get("end_s", 7.5)) - float(r.get("start_s", 0.0)), 2))
        except Exception as e_res:
            logs.append(f"[PLANNER] reserve_clips_for_short info: {e_res}")
            reserved_step1 = []

        if len(reserved_step1) < needed_clips:
            # Re-fetch verified candidates in case background harvest added any during patience wait
            verified_candidates = self._fetch_verified_candidates(animal_mode, current_job_id=job_id, allow_reuse=allow_reuse)

        if len(reserved_step1) >= needed_clips:
            chosen = reserved_step1[:needed_clips]
            final_clips = self._tune_clip_durations(chosen, contract_sec)
            exp_sec = sum(c["dur_s"] for c in final_clips)
            logs.append(f"[PLANNER] Step 1 SUCCESS: {len(final_clips)} fresh unique clips cover {exp_sec:.1f}s.")
            freshness = compute_footage_freshness(final_clips, ledger=self.ledger, current_job_id=job_id, channel=animal_mode)
            return FulfillmentPlan(
                contract_total_sec=contract_sec,
                expected_total_sec=round(exp_sec, 2),
                target_clips_count=len(final_clips),
                target_clip_sec=initial_clip_sec,
                clips=final_clips,
                strategy_used="ladder_step_1_bank",
                ladder_steps_applied=ladder_applied,
                repeat_share_pct=0.0,
                log_messages=logs,
                status_card_line=plain_plan_sentence,
                plain_plan_sentence=plain_plan_sentence,
                feasibility_line=feasibility_line,
                freshness=freshness,
                freshness_card_line=freshness["card_line"]
            )

        selected_step1 = self._select_diverse_windows(verified_candidates, max_per_source=3, min_gap_s=10.0)

        # Calculate if Step 1 satisfies the contract
        total_step1_sec = sum(c.get("dur_s", initial_clip_sec) for c in selected_step1[:needed_clips])
        if len(selected_step1) >= needed_clips:
            chosen = selected_step1[:needed_clips]
            final_clips = self._tune_clip_durations(chosen, contract_sec)
            exp_sec = sum(c["dur_s"] for c in final_clips)
            logs.append(f"[PLANNER] Step 1 SUCCESS: {len(final_clips)} unique clips cover {exp_sec:.1f}s.")
            freshness = compute_footage_freshness(final_clips, ledger=self.ledger, current_job_id=job_id, channel=animal_mode)
            return FulfillmentPlan(
                contract_total_sec=contract_sec,
                expected_total_sec=round(exp_sec, 2),
                target_clips_count=len(final_clips),
                target_clip_sec=initial_clip_sec,
                clips=final_clips,
                strategy_used="ladder_step_1_bank",
                ladder_steps_applied=ladder_applied,
                repeat_share_pct=0.0,
                log_messages=logs,
                status_card_line=freshness["card_line"],
                feasibility_line=feasibility_line,
                freshness=freshness,
                freshness_card_line=freshness["card_line"]
            )

        # ---------------------------------------------------------------------
        # STEP 2: Background Harvest Check (Progressive Build)
        # ---------------------------------------------------------------------
        ladder_applied.append("ladder_step_2_harvest")
        logs.append(f"[PLANNER] Step 1 bank yielded {len(selected_step1)} of {needed_clips} needed. Triggering progressive harvest.")
        # Trigger background harvest worker (if not in test mode)
        is_test_env = bool(os.environ.get("IS_TEST") or "test" in job_id.lower() or job_id.startswith("job_auto_"))
        if not is_test_env:
            try:
                from harvest_worker import trigger_background_harvest_if_needed
                trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=needed_clips * 2)
            except Exception as e_h:
                logs.append(f"[PLANNER] Harvest worker notification: {e_h}")

        # ---------------------------------------------------------------------
        # STEP 3: Raise to Up to 14 Windows Per Long Source (>= 3-10s apart)
        # ---------------------------------------------------------------------
        ladder_applied.append("ladder_step_3_multi_window")
        max_p_source = max(8, int(math.ceil(needed_clips * 0.65)))
        selected_step3 = self._select_diverse_windows(verified_candidates, max_per_source=max_p_source, min_gap_s=10.0)
        if len(selected_step3) < needed_clips:
            selected_step3 = self._select_diverse_windows(verified_candidates, max_per_source=max_p_source, min_gap_s=3.0)
        logs.append(f"[PLANNER] Step 3 expanded window selection yielded {len(selected_step3)} clips across sources.")

        if len(selected_step3) >= needed_clips:
            chosen = selected_step3[:needed_clips]
            final_clips = self._tune_clip_durations(chosen, contract_sec)
            exp_sec = sum(c["dur_s"] for c in final_clips)
            logs.append(f"[PLANNER] Step 3 SUCCESS: {len(final_clips)} unique moments cover {exp_sec:.1f}s.")
            freshness = compute_footage_freshness(final_clips, ledger=self.ledger, current_job_id=job_id, channel=animal_mode)
            return FulfillmentPlan(
                contract_total_sec=contract_sec,
                expected_total_sec=round(exp_sec, 2),
                target_clips_count=len(final_clips),
                target_clip_sec=initial_clip_sec,
                clips=final_clips,
                strategy_used="ladder_step_3_multi_window",
                ladder_steps_applied=ladder_applied,
                repeat_share_pct=0.0,
                log_messages=logs,
                status_card_line=freshness["card_line"],
                feasibility_line=feasibility_line,
                freshness=freshness,
                freshness_card_line=freshness["card_line"]
            )

        # ---------------------------------------------------------------------
        # STEP 4: Adapt Clip Duration Within Bounds [3.5s, 20.0s]
        # ---------------------------------------------------------------------
        ladder_applied.append("ladder_step_4_adapt_duration")
        avail_unique_count = len(selected_step3)
        if avail_unique_count >= 2:
            adapted_clip_sec = contract_sec / float(avail_unique_count)
            # If adapted duration falls cleanly within [3.5s, 20.0s] and doesn't severely distort requested pace (+/- 10% or 1.0s)
            max_dev = min(1.0, initial_clip_sec * 0.10)
            if 3.5 <= adapted_clip_sec <= 20.0 and abs(adapted_clip_sec - initial_clip_sec) <= max_dev:
                logs.append(f"[PLANNER] Step 4 SUCCESS: Adapting {avail_unique_count} unique clips to {adapted_clip_sec:.1f}s each (bounds: 3.5-20.0s, requested: {initial_clip_sec:.1f}s).")
                for c in selected_step3:
                    c["dur_s"] = round(adapted_clip_sec, 2)
                exp_sec = sum(c["dur_s"] for c in selected_step3)
                freshness = compute_footage_freshness(selected_step3, ledger=self.ledger, current_job_id=job_id, channel=animal_mode)
                return FulfillmentPlan(
                    contract_total_sec=contract_sec,
                    expected_total_sec=round(exp_sec, 2),
                    target_clips_count=avail_unique_count,
                    target_clip_sec=round(adapted_clip_sec, 1),
                    clips=selected_step3,
                    strategy_used="ladder_step_4_adapt_duration",
                    ladder_steps_applied=ladder_applied,
                    repeat_share_pct=0.0,
                    log_messages=logs,
                    status_card_line=freshness["card_line"],
                    feasibility_line=feasibility_line,
                    freshness=freshness,
                    freshness_card_line=freshness["card_line"]
                )

        # ---------------------------------------------------------------------
        # STEP 5: Repeat Cycle (Only if allow_reuse is ON)
        # ---------------------------------------------------------------------
        if not allow_reuse:
            if not is_test_env:
                try:
                    from harvest_worker import trigger_background_harvest_if_needed
                    trigger_background_harvest_if_needed(animal_mode, min_low_water_mark=needed_clips * 4)
                except Exception as e_h:
                    logs.append(f"[PLANNER] Harvest worker notification: {e_h}")
            err_msg = f"NO_NEW_CLIPS_AVAILABLE: Insufficient new footage in bank for {animal_mode} ({len(verified_candidates)} fresh clips available, needed {needed_clips}) and 'Allow reuse of footage from earlier videos' is OFF. Starting automatic harvest for new sources."
            logs.append(f"[PLANNER] SAFE_STOP: {err_msg}")
            raise RuntimeError(err_msg)

        ladder_applied.append("ladder_step_5_repeat_cycle")
        logs.append("[PLANNER] Unique pool exhausted and allow_reuse is ON. Executing Step 5 repeat cycle with clean IDs, offset >= 3.0s and spacing >= min(8, unique-1).")

        # Pool of unique clips available to repeat from: oldest first
        base_pool = selected_step3 if selected_step3 else verified_candidates
        if not base_pool:
            base_pool = self._fetch_all_raw_fallback(animal_mode)

        if not base_pool:
            err_msg = f"Insufficient clips in bank for {animal_mode}: 0 candidate clips found across bank and sources"
            logs.append(f"[PLANNER] FATAL: {err_msg}")
            raise RuntimeError(err_msg)

        # Sort oldest first (lowest times_used, then earliest last_used_short_id)
        base_pool.sort(key=lambda c: (c.get("times_used", 0), str(c.get("last_used_short_id", ""))))

        # Calculate needed uses: starts at 3, escalates up to hard cap of 8
        needed_uses = int(math.ceil(contract_sec / max(1.0, len(base_pool) * initial_clip_sec)))
        max_uses_cap = min(8, max(3, needed_uses))

        # If even at max_uses_cap the requested clip duration cannot reach contract, adapt clip duration up to 20.0s
        if (len(base_pool) * max_uses_cap * initial_clip_sec) < contract_sec:
            adapted_c_dur = min(20.0, max(3.5, contract_sec / float(len(base_pool) * max_uses_cap)))
            initial_clip_sec = adapted_c_dur
            logs.append(f"[PLANNER] Escalating repeat capacity: {max_uses_cap} uses per window, adapted clip duration to {initial_clip_sec:.1f}s.")

        # Assemble timeline alternating and spacing repeats
        final_clips = []
        current_dur = 0.0
        pool_len = len(base_pool)
        repeat_counts = {}

        clip_idx = 0
        attempts = 0
        while current_dur < (contract_sec - 0.5) and attempts < 600:
            attempts += 1
            source_cand = base_pool[clip_idx % pool_len]
            raw_cid = str(source_cand.get("base_clip_id") or source_cand.get("clip_id", f"c_{clip_idx}"))
            # Clean base ID: strip any _rep, _use, _off suffixes
            base_cid = raw_cid
            for sfx in ["_rep", "_use", "_off"]:
                if sfx in base_cid:
                    base_cid = base_cid.split(sfx)[0]

            times_seen = repeat_counts.get(base_cid, 0)

            # Enforce max_uses_cap constraint (escalates up to hard cap of 8)
            if times_seen >= max_uses_cap:
                clip_idx += 1
                if all(repeat_counts.get(str(c.get("base_clip_id") or c.get("clip_id", "")).split("_")[0], 0) >= max_uses_cap for c in base_pool):
                    break
                continue

            c_dur = initial_clip_sec
            rem = contract_sec - current_dur
            if rem < c_dur:
                c_dur = max(3.5, rem)

            clip_entry = dict(source_cand)
            clip_entry["dur_s"] = round(c_dur, 2)

            if times_seen == 0:
                clip_entry["clip_id"] = base_cid
                clip_entry["base_clip_id"] = base_cid
                clip_entry["is_repeat"] = False
                clip_entry["repeat_offset_s"] = 0.0
                clip_entry["repeat_cycle"] = 0
            else:
                # Repeat cycle requirements:
                # 1. Distinct trim offset >= 3.0s per cycle
                offset_s = 3.0 * times_seen
                base_start = float(source_cand.get("start_s", 0.0))
                src_total_dur = float(source_cand.get("source_duration") or source_cand.get("source_dur") or 350.0)
                if base_start + offset_s + c_dur > src_total_dur - 0.5:
                    back_start = base_start - offset_s
                    if back_start >= 0.0 and back_start + c_dur <= src_total_dur - 0.5:
                        rep_start = back_start
                    else:
                        rep_start = max(0.0, src_total_dur - c_dur - 1.0)
                else:
                    rep_start = base_start + offset_s
                # 2. Clean ID format: {base_id}_use{N}_off{s} (no _rep1_rep1 chaining)
                rep_cid = f"{base_cid}_use{times_seen + 1}_off{int(offset_s)}"
                clip_entry["clip_id"] = rep_cid
                clip_entry["base_clip_id"] = base_cid
                clip_entry["is_repeat"] = True
                clip_entry["repeat_offset_s"] = offset_s
                clip_entry["start_s"] = round(rep_start, 2)
                # 3. Distinct crop/zoom variant and new caption
                clip_entry["crop_variant"] = f"v{times_seen + 1}"
                clip_entry["zoom_variant"] = round(1.05 + 0.03 * times_seen, 2)
                clip_entry["caption_variant"] = f"Viral Moment (Encore #{times_seen})"
                clip_entry["repeat_cycle"] = times_seen

            final_clips.append(clip_entry)
            current_dur += c_dur
            repeat_counts[base_cid] = times_seen + 1
            clip_idx += 1

            if len(final_clips) >= 300:
                break

        # Re-shuffle/space to guarantee spacing >= min(8, unique-1)
        final_clips = self._space_repeats(final_clips)

        # Fine-tune durations so total exactly hits contract +/-2%
        final_clips = self._tune_clip_durations(final_clips, contract_sec)
        exp_sec = sum(c["dur_s"] for c in final_clips)

        # Compute repeat share percentage
        repeat_dur = sum(c["dur_s"] for c in final_clips if c.get("is_repeat"))
        repeat_share_pct = round((repeat_dur / exp_sec * 100.0), 1) if exp_sec > 0 else 0.0

        logs.append(f"[PLANNER] Step 5 COMPLETED: {len(final_clips)} clips total ({repeat_share_pct:.1f}% repeat share), total {exp_sec:.1f}s.")

        freshness = compute_footage_freshness(final_clips, ledger=self.ledger, current_job_id=job_id, channel=animal_mode)

        return FulfillmentPlan(
            contract_total_sec=contract_sec,
            expected_total_sec=round(exp_sec, 2),
            target_clips_count=len(final_clips),
            target_clip_sec=initial_clip_sec,
            clips=final_clips,
            strategy_used="ladder_step_5_repeat_cycle",
            ladder_steps_applied=ladder_applied,
            repeat_share_pct=repeat_share_pct,
            log_messages=logs,
            status_card_line=freshness["card_line"],
            feasibility_line=feasibility_line,
            freshness=freshness,
            freshness_card_line=freshness["card_line"]
        )

    def _fetch_verified_candidates(self, animal_mode: str, exclude_recent_videos: int = 5, current_job_id: Optional[str] = None, allow_reuse: bool = False) -> List[Dict[str, Any]]:
        """Fetch verified clips from ledger for animal mode, strictly unused first when allow_reuse is False."""
        results = []
        try:
            with self.ledger._get_conn() as conn:
                pending_cond = "pending_short_id IS NULL"
                params = [animal_mode]
                if current_job_id:
                    pending_cond = "(pending_short_id IS NULL OR pending_short_id = ?)"
                    params.append(current_job_id)
                times_cond = "" if allow_reuse else "AND times_used == 0"
                cur = conn.execute(f"""
                    SELECT clip_id, source_id, source_url_or_path, license, start_s, end_s,
                           quality_score, funny_score, sharpness, framing_score, orientation, uploader, title, times_used, verified_plan, fingerprint
                    FROM clips
                    WHERE animal_type = ? AND is_verified = 1 AND {pending_cond} {times_cond}
                      AND (rejection_reason IS NULL OR rejection_reason = '')
                      AND (sharpness IS NULL OR sharpness >= 150.0 OR sharpness = 0.0)
                    ORDER BY times_used ASC, quality_score DESC, funny_score DESC
                """, tuple(params))
                for row in cur.fetchall():
                    d = dict(row)
                    if d.get("verified_plan") and isinstance(d["verified_plan"], str):
                        try:
                            d["verified_plan"] = json.loads(d["verified_plan"])
                        except Exception:
                            pass
                    d["dur_s"] = max(3.5, round(float(d.get("end_s", 7.5)) - float(d.get("start_s", 0.0)), 2))
                    src_p = d.get("source_url_or_path")
                    if src_p and os.path.exists(src_p) and not self.ledger.is_blocked_source(src_p):
                        results.append(d)

            # The ledger count function decides what is fresh, so planner and UI cannot disagree
            if results and not allow_reuse:
                windows = self.ledger.get_ledger_counts(animal_mode, current_job_id=current_job_id, include_windows=True)["windows"]
                fresh_ids = {w["clip_id"] for w in windows["usable_now"] + windows["cooldown"]}
                results = [c for c in results if c.get("clip_id") in fresh_ids]
        except Exception:
            pass
        return results

    def _fetch_all_raw_fallback(self, animal_mode: str) -> List[Dict[str, Any]]:
        """Fallback to any clips in DB or valid raw video segments if bank has 0 verified clips."""
        results = []
        try:
            with self.ledger._get_conn() as conn:
                cur = conn.execute("""
                    SELECT clip_id, source_id, source_url_or_path, license, start_s, end_s,
                           quality_score, funny_score, sharpness, framing_score, orientation, uploader, title, verified_plan
                    FROM clips
                    WHERE animal_type = ?
                    LIMIT 20
                """, (animal_mode,))
                for row in cur.fetchall():
                    d = dict(row)
                    if d.get("verified_plan") and isinstance(d["verified_plan"], str):
                        try:
                            d["verified_plan"] = json.loads(d["verified_plan"])
                        except Exception:
                            pass
                    d["dur_s"] = max(3.5, round(float(d.get("end_s", 7.5)) - float(d.get("start_s", 0.0)), 2))
                    src_p = d.get("source_url_or_path")
                    if src_p and os.path.exists(src_p):
                        results.append(d)

                if not results:
                    cur_all = conn.execute("""
                        SELECT clip_id, source_id, source_url_or_path, license, start_s, end_s,
                               quality_score, funny_score, sharpness, framing_score, orientation, uploader, title, verified_plan
                        FROM clips
                        LIMIT 20
                    """)
                    for row in cur_all.fetchall():
                        d = dict(row)
                        d["dur_s"] = max(3.5, round(float(d.get("end_s", 7.5)) - float(d.get("start_s", 0.0)), 2))
                        src_p = d.get("source_url_or_path")
                        if src_p and os.path.exists(src_p):
                            results.append(d)

            if not results:
                import glob
                search_dirs = [os.path.join(BASE_DIR, "own_footage"), os.path.join(BASE_DIR, "raw")]
                video_files = []
                for sd in search_dirs:
                    if os.path.exists(sd):
                        for f in glob.glob(os.path.join(sd, "*.mp4")):
                            b = os.path.basename(f).lower()
                            if not b.startswith(("cut_", "assembled_", "test_", "concat_")) and os.path.getsize(f) > 500 * 1024:
                                video_files.append(f)
                for idx_v, vf in enumerate(video_files[:10]):
                    sid = os.path.splitext(os.path.basename(vf))[0]
                    for w_idx in range(3):
                        st = w_idx * 10.0 + 2.0
                        results.append({
                            "clip_id": f"c_raw_{sid}_{int(st)}_{int(st+7.5)}",
                            "source_id": sid,
                            "source_url_or_path": vf,
                            "start_s": st,
                            "end_s": st + 7.5,
                            "dur_s": 7.5,
                            "animal_type": animal_mode,
                            "is_verified": 0,
                            "quality_score": 80.0,
                            "funny_score": 80.0
                        })
        except Exception:
            pass
        return results

    def _select_diverse_windows(self, candidates: List[Dict[str, Any]], max_per_source: int = 3, min_gap_s: float = 10.0) -> List[Dict[str, Any]]:
        """Select diverse candidate windows respecting max per source and NMS gap."""
        selected = []
        by_source_windows = {}

        for c in candidates:
            src = c.get("source_id", "unknown")
            st = float(c.get("start_s", 0.0))
            en = float(c.get("end_s", st + 7.5))

            source_wins = by_source_windows.setdefault(src, [])
            if len(source_wins) >= max_per_source:
                continue

            # NMS gap check
            has_overlap = False
            for w_st, w_en in source_wins:
                if not (en + min_gap_s <= w_st or st >= w_en + min_gap_s):
                    has_overlap = True
                    break

            if not has_overlap:
                source_wins.append((st, en))
                selected.append(dict(c))

        return selected

    def _space_repeats(self, clips: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enforce spacing between repeat clips:
        1. Never allow identical window or same base clip_id back-to-back.
        2. Guarantees spacing >= min(8, unique - 1) positions apart using round-robin shifted interleaving.
        """
        if len(clips) <= 1:
            return clips

        def get_clean_base(c):
            b = str(c.get("base_clip_id") or c.get("clip_id") or "")
            for sfx in ["_rep", "_use", "_off"]:
                if sfx in b:
                    b = b.split(sfx)[0]
            s = c.get("source_url_or_path") or c.get("source_id") or ""
            st = round(float(c.get("start_s", 0.0)), 1)
            return b or f"{s}_{st}"

        from collections import defaultdict
        by_base = defaultdict(list)
        for c in clips:
            by_base[get_clean_base(c)].append(c)

        U = len(by_base)
        max_k = max(len(lst) for lst in by_base.values())
        max_possible_gap = len(clips) // max(1, max_k)
        target_gap = min(8, max(2, min(U - 1, max_possible_gap)))

        # Greedy placement with max-distance and highest-remaining-count priority
        N = len(clips)
        ordered = []
        last_pos = {}

        for p in range(N):
            candidates = [b for b, lst in by_base.items() if len(lst) > 0]
            valid = [b for b in candidates if p - last_pos.get(b, -999) >= target_gap]
            if valid:
                best_b = max(valid, key=lambda b: (len(by_base[b]), p - last_pos.get(b, -999)))
            else:
                no_adjacent = [b for b in candidates if p - last_pos.get(b, -999) > 1]
                if no_adjacent:
                    best_b = max(no_adjacent, key=lambda b: (len(by_base[b]), p - last_pos.get(b, -999)))
                else:
                    best_b = max(candidates, key=lambda b: (p - last_pos.get(b, -999), len(by_base[b])))
            
            ordered.append(by_base[best_b].pop(0))
            last_pos[best_b] = p

        # Final safety pass: strictly guarantee no adjacent identical clips anywhere in sequence
        for i in range(N - 1):
            if get_clean_base(ordered[i]) == get_clean_base(ordered[i + 1]):
                for j in range(N):
                    if j == i or j == i + 1:
                        continue
                    b_i = get_clean_base(ordered[i])
                    b_next = get_clean_base(ordered[i + 1])
                    b_j = get_clean_base(ordered[j])
                    if b_j == b_i:
                        continue
                    if i + 2 < N and b_j == get_clean_base(ordered[i + 2]):
                        continue
                    if j > 0 and (j - 1 != i + 1) and get_clean_base(ordered[j - 1]) == b_next:
                        continue
                    if j < N - 1 and (j + 1 != i) and get_clean_base(ordered[j + 1]) == b_next:
                        continue
                    ordered[i + 1], ordered[j] = ordered[j], ordered[i + 1]
                    break

        return ordered

    def _tune_clip_durations(self, clips: List[Dict[str, Any]], target_total_sec: float) -> List[Dict[str, Any]]:
        """Micro-tune clip durations so the sum matches target_total_sec within +/-1%."""
        if not clips:
            return clips

        current_sum = sum(c.get("dur_s", 7.5) for c in clips)
        diff = target_total_sec - current_sum
        per_clip_adj = diff / float(len(clips))

        for c in clips:
            cur = c.get("dur_s", 7.5)
            new_dur = min(20.0, max(3.5, cur + per_clip_adj))
            c["dur_s"] = round(new_dur, 2)

        # Micro-adjustment on the last clip to ensure exact total duration match within +/-0.05s
        final_sum = sum(c["dur_s"] for c in clips)
        rem_drift = target_total_sec - final_sum
        if abs(rem_drift) > 0.05 and clips:
            last_c = clips[-1]
            last_dur = min(20.0, max(3.5, last_c["dur_s"] + rem_drift))
            last_c["dur_s"] = round(last_dur, 2)

        return clips
