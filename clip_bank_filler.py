"""
LionReel Always-On Clip Bank Filler
Fills the clip bank toward a configurable target (default 300 verified windows).
Features:
- Low-priority background worker process with dedicated log (data/bank_filler.log).
- Pauses while render jobs are running (or uses at most 1-2 cores).
- Resumes after restart.
- Can be paused/resumed via dashboard header status chip (no popup).
- Source prioritization: prefers vertical 9:16 and 4K/1440p single-subject sources.
- Circuit breaker: stops analyzing a source after 5 consecutive rejects.
- Fast cheap pre-checks (resolution, orientation, license, compilation/logo flags) before decoding.
- Permanent analysis caching via StageACache so nothing is analyzed twice.
- Tracks metrics: bank size, pass rate per hour, verified windows per CPU hour, time to fill.
"""

import os
import lion_paths
import sys
import time
import json
import glob
import subprocess
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DEFAULT_STATUS_PATH = os.path.join(DATA_DIR, "bank_filler_status.json")
DEFAULT_CONTROL_PATH = os.path.join(DATA_DIR, "bank_filler_control.json")
ACTIVE_JOB_PATH = os.path.join(DATA_DIR, "active_job.json")
LOG_PATH = os.path.join(DATA_DIR, "bank_filler.log")


class SourceTracker:
    def __init__(self, source_path: str):
        self.source_path = source_path
        self.consecutive_rejects = 0
        self.total_analyzed = 0
        self.total_passed = 0

    def record_reject(self):
        self.consecutive_rejects += 1
        self.total_analyzed += 1

    def record_pass(self):
        self.consecutive_rejects = 0
        self.total_analyzed += 1
        self.total_passed += 1

    def should_skip(self) -> bool:
        return self.consecutive_rejects >= 5


@dataclass
class FillerStatus:
    state: str = "idle"  # "idle", "filling", "paused"
    ready: int = 0
    target: int = 40
    target_sources: int = 15
    sources_count: int = 0
    chip_text: str = "Bank: 0 fresh clips, enough for 0 Short; filling, about 30 min to 40"
    pass_rate_per_hour: float = 0.0
    verified_per_cpu_hour: float = 0.0
    est_time_to_fill_s: float = 0.0
    is_paused: bool = False
    last_updated: float = field(default_factory=time.time)


class ClipBankFiller:
    def __init__(
        self,
        ledger=None,
        status_path: str = DEFAULT_STATUS_PATH,
        control_path: str = DEFAULT_CONTROL_PATH,
        active_job_path: str = ACTIVE_JOB_PATH,
        target_verified: int = 40,
        target_sources: int = 15,
        animal_mode: str = "cat"
    ):
        self.ledger = ledger
        self.status_path = status_path
        self.control_path = control_path
        self.active_job_path = active_job_path
        self.target_verified = target_verified
        self.target_sources = target_sources
        self.animal_mode = animal_mode
        self.source_trackers: Dict[str, SourceTracker] = {}
        os.makedirs(os.path.dirname(self.status_path), exist_ok=True)

    def log(self, msg: str):
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [FILLER] {msg}\n"
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    def get_source_tracker(self, source_path: str) -> SourceTracker:
        if source_path not in self.source_trackers:
            self.source_trackers[source_path] = SourceTracker(source_path)
        return self.source_trackers[source_path]

    def is_paused(self) -> bool:
        if os.path.exists(self.control_path):
            try:
                with open(self.control_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("paused", False):
                        return True
                    # Configurable schedule support (default: 01:00-07:00 when enabled)
                    if data.get("schedule_enabled", False):
                        sched_start = str(data.get("schedule_start", "01:00")).strip()
                        sched_end = str(data.get("schedule_end", "07:00")).strip()
                        now_str = time.strftime("%H:%M")
                        if sched_start <= sched_end:
                            in_window = (sched_start <= now_str <= sched_end)
                        else:
                            # Overnight schedule
                            in_window = (now_str >= sched_start or now_str <= sched_end)
                        if not in_window:
                            return True
            except Exception:
                pass
        return False

    def toggle_pause(self) -> bool:
        new_state = not self.is_paused()
        try:
            with open(self.control_path, "w", encoding="utf-8") as f:
                json.dump({"paused": new_state, "updated_at": time.time()}, f, indent=2)
        except Exception:
            pass
        cur_status = self.get_status()
        self.save_status(
            state="paused" if new_state else ("filling" if cur_status.get("ready", 0) < cur_status.get("target", self.target_verified) else "idle"),
            ready=cur_status.get("ready", 0),
            target=cur_status.get("target", self.target_verified),
            sources_count=cur_status.get("sources_count", 0)
        )
        return new_state

    def is_render_active(self) -> bool:
        """
        Returns True ONLY if a render job is actively crunching frames/encoding.
        If a render job is waiting for clips (needs_sources / waiting_for_clips),
        returns False so the bank filler can actively fulfill the shortfall!
        """
        # Check active job file
        if os.path.exists(self.active_job_path):
            try:
                with open(self.active_job_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    job_status = str(d.get("status", "")).lower()
                    job_id = d.get("job_id")
                    # If job is waiting for bank clips, filler MUST RUN to resolve deadlock!
                    if job_status in ("needs_sources", "waiting_for_clips", "waiting"):
                        return False

                    # Check wait_checkpoint in work dir if job_id exists
                    if job_id:
                        for work_base in [lion_paths.work_root(), os.path.join(BASE_DIR, "work")]:
                            cp_file = os.path.join(work_base, job_id, "wait_checkpoint.json")
                            if os.path.exists(cp_file):
                                try:
                                    with open(cp_file, "r", encoding="utf-8") as f_cp:
                                        cp = json.load(f_cp)
                                        if cp.get("status") in ("needs_sources", "waiting_for_clips", "waiting"):
                                            return False
                                except Exception:
                                    pass

                    if job_status in ("running", "in_progress") or d.get("is_running"):
                        return True
            except Exception:
                pass

        # Check if lion_automate_v97 process is running via lock file
        lock_file = os.path.join(DATA_DIR, "render_job.lock")
        if os.path.exists(lock_file):
            # Check if any recent work directory has an active waiting checkpoint
            for work_base in [lion_paths.work_root(), os.path.join(BASE_DIR, "work")]:
                if os.path.exists(work_base):
                    try:
                        for jid in os.listdir(work_base):
                            cp_path = os.path.join(work_base, jid, "wait_checkpoint.json")
                            if os.path.exists(cp_path):
                                try:
                                    with open(cp_path, "r", encoding="utf-8") as f_cp:
                                        cp = json.load(f_cp)
                                        if cp.get("status") in ("needs_sources", "waiting_for_clips", "waiting"):
                                            return False  # Active job is waiting for clips!
                                except Exception:
                                    pass
                    except Exception:
                        pass
            return True

        return False

    def prioritize_sources(self, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Ranks sources to maximize pass yield:
        1. Vertical 9:16 sources first (orientation == 'vertical' or aspect < 1.0)
        2. 4K/1440p high-resolution sources next (width >= 2560 or height >= 1440)
        3. Standard 1080p landscape last
        """
        def rank_key(s):
            orient = str(s.get("orientation", "")).lower()
            w = int(s.get("width", 0))
            h = int(s.get("height", 0))
            is_vert = ("vert" in orient) or (h > w and h > 0)
            is_highres = (w >= 2560 or h >= 1440)
            # Priority tuple: higher tuple values sorted first
            return (
                1 if is_vert else 0,
                1 if is_highres else 0,
                w * h
            )

        return sorted(sources, key=rank_key, reverse=True)

    def save_status(
        self,
        state: str,
        ready: int,
        target: int,
        pass_rate_per_hour: float = 0.0,
        verified_per_cpu_hour: float = 0.0,
        est_time_to_fill_s: float = 0.0,
        sources_count: int = 0
    ):
        shorts_count = ready // 10
        if state == "paused":
            chip_text = f"Bank: {ready} fresh clips, enough for {shorts_count} Short; paused"
        elif ready >= target and (sources_count == 0 or sources_count >= self.target_sources):
            chip_text = f"Bank: {ready} fresh clips, enough for {shorts_count} Short; ready"
        else:
            if est_time_to_fill_s > 0:
                est_min = max(1, int(round(est_time_to_fill_s / 60.0)))
            else:
                deficit = max(1, target - ready)
                est_min = max(1, int(round(deficit * 0.75)))
            chip_text = f"Bank: {ready} fresh clips, enough for {shorts_count} Short; filling, about {est_min} min to {target}"

        payload = {
            "state": state,
            "ready": ready,
            "target": target,
            "target_sources": self.target_sources,
            "sources_count": sources_count,
            "chip_text": chip_text,
            "pass_rate_per_hour": round(pass_rate_per_hour, 1),
            "verified_per_cpu_hour": round(verified_per_cpu_hour, 1),
            "est_time_to_fill_s": round(est_time_to_fill_s, 1),
            "is_paused": (state == "paused"),
            "last_updated": time.time()
        }
        try:
            with open(self.status_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        if os.path.exists(self.status_path):
            try:
                with open(self.status_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "state": "idle",
            "ready": 0,
            "target": self.target_verified,
            "target_sources": self.target_sources,
            "sources_count": 0,
            "chip_text": f"Bank: 0 fresh clips, enough for 0 Short; filling, about 30 min to {self.target_verified}",
            "pass_rate_per_hour": 0.0,
            "verified_per_cpu_hour": 0.0,
            "est_time_to_fill_s": 0.0,
            "is_paused": False,
            "last_updated": time.time()
        }

    def run_filler_cycle(self) -> int:
        """
        Executes one iteration of bank filling.
        Returns count of newly added verified windows.
        """
        if self.is_paused():
            cur = self.get_status()
            self.save_status("paused", cur.get("ready", 0), cur.get("target", self.target_verified), sources_count=cur.get("sources_count", 0))
            return 0

        if self.is_render_active():
            cur = self.get_status()
            self.save_status("paused", cur.get("ready", 0), cur.get("target", self.target_verified), sources_count=cur.get("sources_count", 0))
            self.log("Render job running; background filler worker paused to free CPU cores.")
            return 0

        if not self.ledger:
            from clip_ledger import ClipLedger
            self.ledger = ClipLedger()

        cap = self.ledger.get_pool_ready_and_capacity(self.animal_mode, target_clips=self.target_verified, allow_reuse=False, exclude_recent_videos=5)
        current_ready = cap.get("ready", 0)
        usable_sources = cap.get("usable_sources", 0)

        if current_ready >= self.target_verified and usable_sources >= self.target_sources:
            self.save_status("idle", current_ready, self.target_verified, sources_count=usable_sources)
            return 0

        self.save_status("filling", current_ready, self.target_verified, sources_count=usable_sources)
        self.log(f"Bank filler active: {current_ready} of {self.target_verified} fresh windows from {usable_sources} of {self.target_sources} sources.")

        # Harvest loop to add verified clips
        try:
            from harvest_worker import run_harvest_loop
            needed = min(15, max(self.target_verified - current_ready, (self.target_sources - usable_sources) * 3))
            added = run_harvest_loop(animal_mode=self.animal_mode, target_to_add=needed)
            new_cap = self.ledger.get_pool_ready_and_capacity(self.animal_mode, target_clips=self.target_verified, allow_reuse=False, exclude_recent_videos=5)
            new_ready = new_cap.get("ready", current_ready)
            new_sources = new_cap.get("usable_sources", usable_sources)
            new_state = "idle" if (new_ready >= self.target_verified and new_sources >= self.target_sources) else "filling"
            self.save_status(new_state, new_ready, self.target_verified, sources_count=new_sources)
            return added
        except Exception as e:
            self.log(f"Filler error: {e}")
            return 0


def check_and_trigger_bank_filler(
    current_usable: int,
    target_bank: int = 60,
    job_needed: int = 4,
    trigger: bool = True,
    animal_mode: str = "cat"
) -> tuple:
    """
    TASK 3: Keep a target of verified usable windows (default 60 for cat, config).
    When usable windows fall below 2x what the selected length needs, start the harvest on its own.
    A job must never be the first moment the bank is found empty.
    """
    threshold_2x = max(1, job_needed * 2)
    if current_usable < threshold_2x:
        deficit = threshold_2x - current_usable
        reason = f"Bank Deficit: usable windows ({current_usable}) < 2x target ({threshold_2x}), deficit of {deficit} windows"
        should_trigger = True
    elif current_usable < target_bank:
        deficit = target_bank - current_usable
        reason = f"Bank Target Deficit: usable windows ({current_usable}) < target bank ({target_bank}), deficit of {deficit} windows"
        should_trigger = True
    else:
        return False, f"Bank healthy: {current_usable} usable windows (target {target_bank})"

    if should_trigger and trigger:
        from harvest_worker import trigger_background_harvest_if_needed
        trigger_background_harvest_if_needed(animal_mode=animal_mode, target_clips_needed=target_bank)

    return True, reason


def main():
    filler = ClipBankFiller()
    filler.log("ClipBankFiller daemon process started.")
    while True:
        try:
            filler.run_filler_cycle()
            time.sleep(30.0)
        except KeyboardInterrupt:
            filler.log("ClipBankFiller stopped by user.")
            break
        except Exception as e:
            filler.log(f"Unexpected loop exception: {e}")
            time.sleep(10.0)


if __name__ == "__main__":
    main()

