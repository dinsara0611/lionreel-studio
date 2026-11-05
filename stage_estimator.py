"""
LionReel Studio — Server-Side Pipeline Estimator & Historical Duration Engine
=============================================================================
Single source of truth for pipeline progress, elapsed time, and ETA.
Features:
- Historical stage duration database (SQLite) partitioned by mode, clip count, layout, cached state.
- Median calculations over the last 10 comparable jobs with robust fallbacks.
- Sub-stage work-unit tracking (candidates analyzed, clips rendered, frames encoded).
- Strictly monotonic progress percentage (never decreases, even during scope growth).
- Real ETA ranges with smoothed speed-factor scaling (EMA, clamped 0.5 - 2.0).
- "Calculating..." state during initial stages before reliable work units exist.
- Pure server-side elapsed time accounting (excludes waiting states).
"""

import os
import lion_paths
import sys
import time
import json
import sqlite3
import statistics

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "stage_history.db")

# Default stage duration fallbacks in seconds for a standard 6-clip short
DEFAULT_STAGE_WEIGHTS = {
    1: 1.0,    # Collect candidate moments from ledger
    2: 0.5,    # Prepare raw source video files
    3: 1.5,    # Check source resolution & frame rate
    4: 8.0,    # Detect watermarks & logos
    5: 60.0,   # Predict pet framing (scales with candidates count, ~2-4s/candidate with parallel fastpath)
    6: 180.0,  # Reframe & render vertical clip cuts (~30s per clip)
    7: 0.1,    # Auto color grading (usually fast or skipped)
    8: 60.0,   # Safe-zone captions & master audio ducking
    9: 75.0,   # Final MP4 assembly & 10-gate QA validation
    10: 1.5    # Save master & register credits
}

def init_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=10.0)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stage_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            stage_id INTEGER NOT NULL,
            stage_key TEXT,
            duration_sec REAL NOT NULL,
            units_done INTEGER DEFAULT 0,
            units_total INTEGER DEFAULT 0,
            clips_count INTEGER DEFAULT 6,
            clip_time REAL DEFAULT 7.5,
            mode TEXT DEFAULT 'short',
            layout TEXT DEFAULT 'smart_crop',
            is_cached INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_stage_lookup ON stage_executions(stage_id, mode, clips_count, is_cached)")
    conn.commit()
    conn.close()

init_db()

class StageEstimator:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        init_db(self.db_path)
        self._init_history_from_work_dirs_if_empty()

    def _get_conn(self):
        return sqlite3.connect(self.db_path, timeout=10.0)

    def _init_history_from_work_dirs_if_empty(self):
        """Seeds the historical database from existing C:\\LionReel\\work jobs if empty."""
        try:
            with self._get_conn() as conn:
                cur = conn.cursor()
                count = cur.execute("SELECT COUNT(*) FROM stage_executions").fetchone()[0]
                if count > 0:
                    return

                work_dir = lion_paths.work_root()
                if not os.path.exists(work_dir):
                    return

                entries = []
                for entry_name in os.listdir(work_dir):
                    job_path = os.path.join(work_dir, entry_name)
                    st_path = os.path.join(job_path, "stages_state.json")
                    if os.path.exists(st_path):
                        try:
                            with open(st_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            stages = data.get("stages", [])
                            for s in stages:
                                if s.get("status") in ("DONE", "SKIPPED") and s.get("duration_sec", 0) > 0:
                                    s_id = s.get("id")
                                    dur = float(s.get("duration_sec", 0))
                                    entries.append((
                                        entry_name, s_id, s.get("key", ""), dur,
                                        0, 0, 6, 7.5, "short", "smart_crop",
                                        1 if dur < 0.5 and s_id in (4, 5, 6) else 0
                                    ))
                        except Exception:
                            pass

                if entries:
                    cur.executemany("""
                        INSERT INTO stage_executions 
                        (job_id, stage_id, stage_key, duration_sec, units_done, units_total, clips_count, clip_time, mode, layout, is_cached)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, entries)
                    conn.commit()
        except Exception as e:
            print(f"Notice during history seed: {e}")

    def record_stage_execution(self, job_id, stage_id, stage_key, duration_sec, units_done=0, units_total=0,
                               clips_count=6, clip_time=7.5, mode="short", layout="smart_crop", is_cached=0):
        """Records a completed stage duration in the historical database."""
        try:
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT INTO stage_executions 
                    (job_id, stage_id, stage_key, duration_sec, units_done, units_total, clips_count, clip_time, mode, layout, is_cached)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (job_id, stage_id, stage_key, float(duration_sec), int(units_done), int(units_total),
                      int(clips_count), float(clip_time), str(mode), str(layout), int(is_cached)))
                conn.commit()
        except Exception:
            pass

    def get_expected_stage_duration(self, stage_id, mode="short", clips_count=6, clip_time=7.5, is_cached=False, candidate_count=None):
        """Computes expected duration of a stage using median of last 10 comparable jobs."""
        cache_flag = 1 if is_cached else 0
        if is_cached:
            return 0.2  # Cached stages are nearly instant

        try:
            with self._get_conn() as conn:
                cur = conn.cursor()
                # Query last 10 comparable runs
                cur.execute("""
                    SELECT duration_sec FROM stage_executions
                    WHERE stage_id = ? AND is_cached = ?
                    AND (mode = ? OR mode IS NULL)
                    AND (ABS(clips_count - ?) <= 2 OR clips_count IS NULL)
                    AND job_id NOT LIKE 'test_%'
                    AND duration_sec >= 1.0
                    ORDER BY id DESC LIMIT 10
                """, (stage_id, cache_flag, mode, clips_count))
                rows = [r[0] for r in cur.fetchall() if r[0] > 0]
                if len(rows) >= 3:
                    med = float(statistics.median(rows))
                    min_floor = 0.5
                    if stage_id == 6:
                        min_floor = max(30.0, clips_count * 12.0)
                    elif stage_id == 8:
                        min_floor = 20.0
                    elif stage_id == 9:
                        min_floor = 30.0
                    elif stage_id == 5:
                        min_floor = 15.0
                    return max(min_floor, med)
        except Exception:
            pass

        # Dynamic fallback scaling based on work volume
        base = DEFAULT_STAGE_WEIGHTS.get(stage_id, 10.0)
        if mode == "short" and clips_count <= 4:
            # Calibrated baseline from measured 30s Short timings (~82s total without waiting)
            short_30s = {
                1: 0.5,
                2: 0.5,
                3: 0.5,
                4: 2.0,
                5: 15.0,
                6: 40.0,
                7: 0.1,
                8: 10.0,
                9: 12.0,
                10: 1.0
            }
            return short_30s.get(stage_id, base)

        if stage_id == 5 and candidate_count:
            # Scale Stage 5 with candidate volume (~2.5s per candidate with optimized detection)
            return max(15.0, candidate_count * 2.5)
        elif stage_id == 6:
            # Scale Stage 6 with target clips (~25s per clip)
            return max(30.0, clips_count * 25.0)
        elif stage_id == 8:
            return max(20.0, clips_count * 5.0)
        elif stage_id == 9:
            return max(35.0, clips_count * 6.0)

        return base

    def compute_job_telemetry(self, job_id, stages_data, config=None, start_time_epoch=None,
                              is_running=True, status="running", waiting_seconds=0.0):
        """
        Computes honest progress %, elapsed time, ETA ranges, and telemetry.
        Single source of truth for the entire pipeline.
        """
        config = config or {}
        clips_count = int(config.get("TARGET_CLIPS") or 6)
        clip_time = float(config.get("SHORT_CLIP_SEC") or 7.5)
        mode = str(config.get("VIDEO_TYPE") or "short").lower()
        layout = str(config.get("LAYOUT_MODE") or "smart_crop").lower()

        now = time.time()
        start_time = float(start_time_epoch) if start_time_epoch else now
        raw_elapsed = max(0.0, now - start_time)
        net_elapsed = max(0.0, raw_elapsed - float(waiting_seconds))

        stages = stages_data if isinstance(stages_data, list) else stages_data.get("stages", [])

        # 1. Terminal / special states
        if status in ("completed", "done", "success"):
            return {
                "progressPct": 100,
                "elapsedSeconds": int(round(net_elapsed)),
                "waitingSeconds": int(round(waiting_seconds)),
                "etaSeconds": 0,
                "etaLowSeconds": 0,
                "etaHighSeconds": 0,
                "etaFormatted": "00:00",
                "isCalculating": False,
                "speedFactor": 1.0,
                "stateLabel": "DONE",
                "unitsDone": clips_count,
                "unitsTotal": clips_count,
                "unitType": "clips",
                "currentStageId": 10,
                "currentStageName": "Completed",
                "status": "completed"
            }

        if status in ("error", "failed"):
            return {
                "progressPct": 100,
                "elapsedSeconds": int(round(net_elapsed)),
                "waitingSeconds": int(round(waiting_seconds)),
                "etaSeconds": 0,
                "etaLowSeconds": 0,
                "etaHighSeconds": 0,
                "etaFormatted": "Failed",
                "isCalculating": False,
                "speedFactor": 1.0,
                "stateLabel": "FAILED",
                "unitsDone": 0,
                "unitsTotal": 0,
                "unitType": "",
                "currentStageId": 0,
                "currentStageName": "Failed",
                "status": "failed"
            }

        if status in ("waiting_for_clips", "needs_sources", "waiting") and not stages:
            eta_base = 60 if clips_count <= 4 else 120
            eta_l = max(5, int(eta_base * 0.8))
            eta_h = int(eta_base * 1.2)
            return {
                "progressPct": 50,
                "elapsedSeconds": int(round(raw_elapsed)),
                "waitingSeconds": int(round(waiting_seconds)),
                "waitingBudgetIncluded": False,
                "etaSeconds": eta_base,
                "etaLowSeconds": eta_l,
                "etaHighSeconds": eta_h,
                "etaFormatted": f"{format_time_hms(eta_l)} – {format_time_hms(eta_h)}",
                "isCalculating": False,
                "speedFactor": 1.0,
                "stateLabel": "WAITING",
                "unitsDone": 0,
                "unitsTotal": 0,
                "unitType": "sources",
                "currentStageId": 6,
                "currentStageName": "Finding new footage",
                "status": "waiting"
            }

        # 2. Identify running, finished, and pending stages
        finished_stages = []
        running_stage = None
        pending_stages = []

        candidate_count = 30
        for s in stages:
            s_id = s.get("id")
            s_st = s.get("status", "PENDING").upper()
            if s_st in ("DONE", "SKIPPED", "CACHED"):
                finished_stages.append(s)
            elif s_st == "RUNNING" and running_stage is None:
                running_stage = s
            else:
                pending_stages.append(s)

        # Detect candidate count from Stage 1/5 proof if available
        for s in finished_stages + ([running_stage] if running_stage else []):
            if s and s.get("id") in (1, 5):
                det = s.get("details", {}) or {}
                if "candidate_target" in det:
                    candidate_count = det["candidate_target"]
                elif "items_count" in det and det["items_count"] > 0:
                    candidate_count = det["items_count"]

        # 3. Calculate expected stage durations
        stage_expectations = {}
        for s in stages:
            s_id = s["id"]
            is_c = (s.get("status") == "CACHED")
            stage_expectations[s_id] = self.get_expected_stage_duration(
                s_id, mode=mode, clips_count=clips_count, clip_time=clip_time,
                is_cached=is_c, candidate_count=candidate_count
            )

        # 4. Measure speed factor from completed stages (actual vs expected)
        finished_actual = 0.0
        finished_expected = 0.0
        for s in finished_stages:
            s_id = s["id"]
            dur = float(s.get("duration_sec", 0.0))
            is_c = (s.get("status") == "CACHED")
            if not is_c and dur > 0.3:
                finished_actual += dur
                finished_expected += stage_expectations[s_id]

        if running_stage:
            r_id = running_stage["id"]
            r_dur = float(running_stage.get("duration_sec", 0.0))
            r_exp = stage_expectations.get(r_id, 30.0)
            if r_dur > r_exp and r_exp > 0:
                finished_actual += r_dur
                finished_expected += r_exp

        if finished_expected >= 5.0 and finished_actual > 0:
            raw_speed = finished_actual / finished_expected
            speed_factor = max(0.5, min(2.0, raw_speed))
        else:
            speed_factor = 1.0

        # 5. Intra-stage work-unit progress for running stage
        running_fraction = 0.0
        units_done = 0
        units_total = 0
        unit_type = ""

        if running_stage:
            r_id = running_stage["id"]
            r_det = running_stage.get("details", {}) or {}
            units_done = int(r_det.get("units_done", 0))
            units_total = int(r_det.get("units_total", 0))
            unit_type = str(r_det.get("unit_type", ""))

            if units_total > 0 and units_done >= 0:
                running_fraction = min(0.98, max(0.01, float(units_done) / float(units_total)))
            else:
                # Time-based interpolation inside running stage capped at 0.90
                exp_dur = stage_expectations.get(r_id, 30.0) * speed_factor
                st_time = float(running_stage.get("start_time") or now)
                stage_elapsed = max(0.0, now - st_time)
                running_fraction = min(0.90, max(0.05, stage_elapsed / max(1.0, exp_dur)))

        # 6. Monotonic Progress Percentage
        total_pipeline_expected = sum(stage_expectations.values())
        finished_pipeline_expected = sum(stage_expectations[s["id"]] for s in finished_stages)
        running_pipeline_expected = (stage_expectations[running_stage["id"]] * running_fraction) if running_stage else 0.0

        earned_expected = finished_pipeline_expected + running_pipeline_expected
        calc_pct = min(99, max(2, int(round((earned_expected / max(1.0, total_pipeline_expected)) * 100))))

        # Monotonicity floor: retrieve last saved max_seen_pct from job checkpoint/state
        max_seen_pct = calc_pct
        if isinstance(stages_data, dict):
            max_seen_pct = max(calc_pct, int(stages_data.get("max_seen_pct", 0)))
            stages_data["max_seen_pct"] = max_seen_pct

        final_pct = max_seen_pct

        # 7. Accurate ETA Calculation
        remaining_in_running = 0.0
        if running_stage:
            r_id = running_stage["id"]
            remaining_in_running = (1.0 - running_fraction) * stage_expectations[r_id]

        remaining_in_pending = sum(stage_expectations[s["id"]] for s in pending_stages)
        eta_base_seconds = (remaining_in_running + remaining_in_pending) * speed_factor

        # "Calculating..." condition: before at least 2 stages finished OR running stage has measured units
        is_calculating = (len(finished_stages) < 2 and (not running_stage or units_total <= 0) and net_elapsed < 8.0)

        eta_seconds = max(5, int(round(eta_base_seconds)))
        # Range representation when variance is higher
        uncertainty = 0.25 if len(finished_stages) < 4 else 0.12
        eta_low_s = max(5, int(round(eta_seconds * (1.0 - uncertainty))))
        eta_high_s = max(eta_low_s + 5, int(round(eta_seconds * (1.0 + uncertainty))))

        # Waiting detection
        waiting_stage = next((s for s in stages if s.get("status") == "WAITING"), None)
        is_waiting = bool(waiting_stage or (isinstance(stages_data, dict) and stages_data.get("status") in ("waiting_for_clips", "needs_sources")))

        if is_waiting:
            state_label = "WAITING"
            cur_stg_id = waiting_stage["id"] if waiting_stage else 6
            cur_stg_name = waiting_stage.get("label", "Finding new footage") if waiting_stage else "Finding new footage"
            # Always show a formatted time range or calculating, never sentences
            if is_calculating:
                eta_formatted = "Calculating…"
            elif eta_high_s > eta_low_s:
                eta_formatted = f"{format_time_hms(eta_low_s)} – {format_time_hms(eta_high_s)}"
            else:
                eta_formatted = format_time_hms(eta_seconds)
        else:
            state_label = "LIVE"
            if running_stage:
                cur_stg_id = running_stage["id"]
                cur_stg_name = running_stage.get("label", "")
            elif finished_stages:
                if len(finished_stages) == len(stages):
                    cur_stg_id = finished_stages[-1]["id"]
                    cur_stg_name = "Completed"
                else:
                    next_p = next((s for s in pending_stages), None)
                    cur_stg_id = next_p["id"] if next_p else finished_stages[-1]["id"]
                    cur_stg_name = next_p.get("label", "Processing") if next_p else "Finalizing"
            else:
                cur_stg_id = 1
                cur_stg_name = stages[0].get("label", "Initializing") if stages else "Initializing"

            if is_calculating:
                eta_formatted = "Calculating…"
            elif eta_high_s > eta_low_s and (eta_high_s - eta_low_s) >= 15:
                eta_formatted = f"{format_time_hms(eta_low_s)} – {format_time_hms(eta_high_s)}"
            else:
                eta_formatted = format_time_hms(eta_seconds)

        return {
            "progressPct": final_pct,
            "elapsedSeconds": int(round(raw_elapsed)),
            "waitingSeconds": int(round(waiting_seconds)),
            "waitingBudgetIncluded": False,
            "etaSeconds": eta_seconds,
            "etaLowSeconds": eta_low_s,
            "etaHighSeconds": eta_high_s,
            "etaFormatted": eta_formatted,
            "isCalculating": is_calculating and not is_waiting,
            "speedFactor": round(speed_factor, 2),
            "stateLabel": state_label,
            "unitsDone": units_done,
            "unitsTotal": units_total,
            "unitType": unit_type,
            "currentStageId": cur_stg_id,
            "currentStageName": cur_stg_name,
            "status": "waiting" if is_waiting else "running"
        }

    def compute_predicted_time_and_deadline(
        self,
        target_clips_count: int,
        target_clip_sec: float,
        contract_total_sec: float,
        bank_verified_count: int = 0,
        start_epoch: float = None,
        job_id: str = None,
        work_dir: str = None
    ) -> dict:
        """
        Builds the plan deadline and predicted total time range [low, high]
        from MEASURED numbers on this computer:
          - render seconds per clip: ~28s (libx264) / ~18s (h264_mf); ~12-14s effective with workers
          - post-crop gate seconds: ~2.4s (sampling 12 frames); ~1.0s effective
          - analysis seconds per window: ~2.5s; pass rate ~30%
          - assembly: ~18s + clips * 0.4s
          - QA: ~35s + (dur/60)*5s
          - copy to Google Drive: ~12s + (dur/60)*3s
        Persists deadline D = high estimate + 10%, monotonic deadline that survives restarts.
        """
        start_epoch = float(start_epoch) if start_epoch else time.time()

        # Check if already persisted
        if work_dir and os.path.exists(os.path.join(work_dir, "deadline.json")):
            try:
                with open(os.path.join(work_dir, "deadline.json"), "r", encoding="utf-8") as f:
                    persisted = json.load(f)
                    if persisted.get("deadline_epoch"):
                        return persisted
            except Exception:
                pass

        clips = max(1, int(target_clips_count))
        dur_sec = max(10.0, float(contract_total_sec))

        # Measured throughput on this PC (Intel Core i5 / Intel Iris Xe, 2-3 parallel render workers)
        # Empirical numbers from production run lionreel_cat_20261014_132813_d25ddf09:
        # - Fixed setup (startup, prepare, watermark): ~110s
        # - Framing prediction & YOLO tracking per candidate: ~25.0s
        # - Video reframing & hardware encoding (h264_mf): ~15.8s per clip
        # - Caption burning (drawtext): ~8.0s per clip
        # - Audio mastering (EBU R128 two-pass): ~8.5s per clip
        # - Segment concat: ~2.5s
        # - Post-render QA validation (blackdetect, EBUR128, centering, contact sheet): ~180s + (dur/60)*120s
        # - Drive export copy: ~15s + (dur/60)*3s
        t_fixed_setup = 110.0
        t_per_clip_pipeline = 25.0 + 15.8 + 8.0 + 8.5  # ~57.3s per clip end-to-end
        t_assembly = 5.0 + (clips * 0.2)
        t_qa = 180.0 + (dur_sec / 60.0) * 120.0
        t_copy = 15.0 + (dur_sec / 60.0) * 3.0

        t_finish = t_fixed_setup + (clips * t_per_clip_pipeline) + t_assembly + t_qa + t_copy

        # Search/analysis time needed based on bank state
        verified_avail = max(0, int(bank_verified_count))
        needed_from_search = max(0, clips - verified_avail)

        t_analysis_per_win = 4.0
        pass_rate = 0.30  # measured ~30% pass rate on cat sources
        search_time = (needed_from_search / pass_rate) * t_analysis_per_win if needed_from_search > 0 else 0.0

        t_total_expected = t_finish + search_time

        # Range computation [low, high]
        low_sec = max(30, int(round(t_total_expected * 0.90)))
        high_sec = max(low_sec + 30, int(round(t_total_expected * 1.15)))

        # Monotonic deadline D = high estimate + 10%
        deadline_sec = int(round(high_sec * 1.10))
        deadline_epoch = start_epoch + deadline_sec

        # Range string format
        if high_sec < 60:
            range_str = f"about {low_sec}–{high_sec} s"
        else:
            low_min = max(1, low_sec // 60)
            high_min = max(low_min + 1, (high_sec + 59) // 60)
            range_str = f"about {low_min}–{high_min} min"

        # Expected finish clock time
        finish_dt = time.localtime(start_epoch + t_total_expected)
        finish_clock_str = f"done by about {finish_dt.tm_hour:02d}:{finish_dt.tm_min:02d}"

        # Minimum feasible time for display when requested length is high
        min_feasible_sec = int(round(t_finish))
        if min_feasible_sec >= 3600:
            mf_h = min_feasible_sec // 3600
            mf_m = (min_feasible_sec % 3600) // 60
            mf_str = f"{mf_h} h {mf_m:02d} min"
        elif min_feasible_sec >= 60:
            mf_m = min_feasible_sec // 60
            mf_s = min_feasible_sec % 60
            mf_str = f"{mf_m} min {mf_s:02d} s" if mf_s > 0 else f"{mf_m} min"
        else:
            mf_str = f"{min_feasible_sec} s"

        video_min = int(round(dur_sec / 60.0))
        min_feasible_msg = f"Minimum time for {video_min} min on this computer: {mf_str}"

        plan_summary = f"Plan: {clips} clips × {target_clip_sec:.1f}s ({range_str})"

        deadline_data = {
            "job_id": job_id,
            "start_epoch": start_epoch,
            "predicted_low_sec": low_sec,
            "predicted_high_sec": high_sec,
            "predicted_range_str": range_str,
            "finish_clock_str": finish_clock_str,
            "deadline_epoch": deadline_epoch,
            "deadline_sec": deadline_sec,
            "t_finish_sec": round(t_finish, 1),
            "min_feasible_sec": min_feasible_sec,
            "min_feasible_str": min_feasible_msg,
            "plan_summary": plan_summary,
            "is_monotonic": True
        }

        if work_dir:
            try:
                os.makedirs(work_dir, exist_ok=True)
                with open(os.path.join(work_dir, "deadline.json"), "w", encoding="utf-8") as f:
                    json.dump(deadline_data, f, indent=2)
            except Exception:
                pass

        return deadline_data

    def record_job_completion_accuracy(self, job_id: str, predicted_low: float, predicted_high: float, actual_sec: float) -> dict:
        """Records accuracy of predicted range vs actual wall-clock duration."""
        acc_file = os.path.join(DATA_DIR, "accuracy_history.json")
        history = []
        if os.path.exists(acc_file):
            try:
                with open(acc_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                pass

        inside = (predicted_low <= actual_sec <= predicted_high)
        midpoint = (predicted_low + predicted_high) / 2.0
        err_pct = abs(actual_sec - midpoint) / max(1.0, midpoint) * 100.0

        entry = {
            "job_id": job_id,
            "timestamp": time.time(),
            "predicted_low": predicted_low,
            "predicted_high": predicted_high,
            "actual_sec": actual_sec,
            "inside_range": inside,
            "error_pct": round(err_pct, 1)
        }
        history.append(entry)
        try:
            with open(acc_file, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
        except Exception:
            pass

        # Calculate accuracy over last 5 jobs
        last_5 = history[-5:]
        mean_err = sum(e["error_pct"] for e in last_5) / max(1, len(last_5))
        inside_count = sum(1 for e in last_5 if e.get("inside_range"))

        return {
            "mean_error_pct": round(mean_err, 1),
            "inside_count": inside_count,
            "total_evaluated": len(last_5),
            "accuracy_summary_str": f"estimate accuracy: within {mean_err:.1f}% over the last {len(last_5)} jobs",
            "inside_range": inside,
            "error_pct": round(err_pct, 1),
            "last_entry": entry
        }

def format_time_hms(total_sec):
    total_sec = max(0, int(round(total_sec)))
    if total_sec >= 3600:
        h = total_sec // 3600
        m = (total_sec % 3600) // 60
        s = total_sec % 60
        return f"{h}:{m:02d}:{s:02d}"
    m = total_sec // 60
    s = total_sec % 60
    return f"{m:02d}:{s:02d}"
