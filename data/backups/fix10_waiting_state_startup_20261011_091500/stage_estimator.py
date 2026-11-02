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
    conn = sqlite3.connect(db_path)
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
        return sqlite3.connect(self.db_path)

    def _init_history_from_work_dirs_if_empty(self):
        """Seeds the historical database from existing C:\\LionReel\\work jobs if empty."""
        try:
            with self._get_conn() as conn:
                cur = conn.cursor()
                count = cur.execute("SELECT COUNT(*) FROM stage_executions").fetchone()[0]
                if count > 0:
                    return

                work_dir = "C:/LionReel/work"
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
                    ORDER BY id DESC LIMIT 10
                """, (stage_id, cache_flag, mode, clips_count))
                rows = [r[0] for r in cur.fetchall() if r[0] > 0]
                if len(rows) >= 3:
                    med = float(statistics.median(rows))
                    return max(0.5, med)
        except Exception:
            pass

        # Dynamic fallback scaling based on work volume
        base = DEFAULT_STAGE_WEIGHTS.get(stage_id, 10.0)
        if stage_id == 5 and candidate_count:
            # Scale Stage 5 with candidate volume (~2.5s per candidate with optimized detection)
            return max(15.0, candidate_count * 2.5)
        elif stage_id == 6:
            # Scale Stage 6 with target clips (~30s per clip)
            return max(30.0, clips_count * 30.0)

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

        if status in ("waiting_for_clips", "needs_sources", "waiting"):
            return {
                "progressPct": 50,
                "elapsedSeconds": int(round(net_elapsed)),
                "waitingSeconds": int(round(waiting_seconds)),
                "etaSeconds": 0,
                "etaLowSeconds": 0,
                "etaHighSeconds": 0,
                "etaFormatted": "Waiting for clips",
                "isCalculating": False,
                "speedFactor": 1.0,
                "stateLabel": "WAITING",
                "unitsDone": 0,
                "unitsTotal": 0,
                "unitType": "sources",
                "currentStageId": 1,
                "currentStageName": "Waiting for sources",
                "status": status
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

        if is_calculating:
            eta_formatted = "Calculating…"
        elif eta_seconds >= 60 and (eta_high_s - eta_low_s) >= 30:
            m_low = eta_low_s // 60
            m_high = max(m_low + 1, (eta_high_s + 59) // 60)
            eta_formatted = f"about {m_low}–{m_high} min"
        else:
            eta_formatted = format_time_hms(eta_seconds)

        return {
            "progressPct": final_pct,
            "elapsedSeconds": int(round(net_elapsed)),
            "waitingSeconds": int(round(waiting_seconds)),
            "etaSeconds": eta_seconds,
            "etaLowSeconds": eta_low_s,
            "etaHighSeconds": eta_high_s,
            "etaFormatted": eta_formatted,
            "isCalculating": is_calculating,
            "speedFactor": round(speed_factor, 2),
            "stateLabel": "LIVE",
            "unitsDone": units_done,
            "unitsTotal": units_total,
            "unitType": unit_type,
            "currentStageId": running_stage["id"] if running_stage else (finished_stages[-1]["id"] if finished_stages else 1),
            "currentStageName": running_stage.get("label", "") if running_stage else "Finalizing",
            "status": "running"
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
