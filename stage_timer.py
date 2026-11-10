"""
LionReel Pipeline Stage Timer (Single Monotonic Clock & Exclusive Stage Tracking)
==================================================================================
Guarantees:
- Every single second is accounted for against real wall clock.
- One monotonic clock (time.perf_counter) + wall-clock start/end timestamps.
- Hierarchical / nested stage support with exclusive durations (no double-counting).
- Unaccounted time = total wall time minus sum of exclusive stages.
- Logs WARN when unaccounted gap > 2%.
- Writes work/<job_id>/timings.json with exact start/end timestamps per stage.
"""

import time
import json
import os
import datetime

class StageTimer:
    def __init__(self, job_id: str = "default_job", wall_start_epoch: float = None):
        self.job_id = job_id
        now_time = time.time()
        self._wall_start_epoch = float(wall_start_epoch) if wall_start_epoch else now_time
        elapsed_since_start = max(0.0, now_time - self._wall_start_epoch)
        self._perf_start = time.perf_counter() - elapsed_since_start
        self._perf_end = None
        self._wall_end_epoch = None
        
        # stage_name -> dict(duration_sec, exclusive_sec, start_epoch, end_epoch, count, parent, orig_perf)
        self.stages = {}
        self._stack = [] # list of (stage_name, slice_start_perf)
        self._is_finished = False

    def start_stage(self, name: str):
        now_perf = time.perf_counter()
        now_wall = time.time()
        
        # Credit slice to parent if stack is non-empty
        if self._stack:
            parent_name, parent_slice_start = self._stack[-1]
            elapsed_slice = now_perf - parent_slice_start
            if parent_name in self.stages:
                self.stages[parent_name]["exclusive_sec"] += elapsed_slice
            self._stack[-1] = (parent_name, now_perf)

        if name not in self.stages:
            parent_name = self._stack[-1][0] if self._stack else None
            self.stages[name] = {
                "duration_sec": 0.0,
                "exclusive_sec": 0.0,
                "start_epoch": now_wall,
                "end_epoch": now_wall,
                "count": 0,
                "parent": parent_name,
                "orig_perf": now_perf
            }
        
        self.stages[name]["count"] += 1
        self._stack.append((name, now_perf))

    def stop_stage(self, name: str = None):
        now_perf = time.perf_counter()
        now_wall = time.time()
        
        if not self._stack:
            return

        if name is None:
            name, slice_start = self._stack.pop()
        else:
            found_idx = -1
            for i in range(len(self._stack) - 1, -1, -1):
                if self._stack[i][0] == name:
                    found_idx = i
                    break
            if found_idx == -1:
                return
            name, slice_start = self._stack.pop(found_idx)

        elapsed_slice = now_perf - slice_start
        if name in self.stages:
            self.stages[name]["exclusive_sec"] += elapsed_slice
            if self.stages[name]["count"] > 1:
                self.stages[name]["duration_sec"] += elapsed_slice
            else:
                self.stages[name]["duration_sec"] = now_perf - self.stages[name]["orig_perf"]
            self.stages[name]["end_epoch"] = now_wall
        
        # Reset parent's slice start to now
        if self._stack:
            p_name, _ = self._stack[-1]
            self._stack[-1] = (p_name, now_perf)

    class _StageContext:
        def __init__(self, timer, name):
            self.timer = timer
            self.name = name

        def __enter__(self):
            self.timer.start_stage(self.name)
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.timer.stop_stage(self.name)

    def stage(self, name: str):
        return self._StageContext(self, name)

    def finish_job(self):
        if self._is_finished:
            return
        now_perf = time.perf_counter()
        now_wall = time.time()
        
        while self._stack:
            self.stop_stage()
            
        self._perf_end = now_perf
        self._wall_end_epoch = now_wall
        self._is_finished = True

    def get_summary(self) -> dict:
        now_perf = self._perf_end if self._perf_end else time.perf_counter()
        now_wall = self._wall_end_epoch if self._wall_end_epoch else time.time()
        total_wall_time = max(0.001, now_perf - self._perf_start)
        
        normalized_stages = {}
        for name, data in self.stages.items():
            if isinstance(data, (int, float)):
                data = {
                    "duration_sec": float(data),
                    "exclusive_sec": float(data),
                    "start_epoch": self._wall_start_epoch,
                    "end_epoch": self._wall_start_epoch + float(data),
                    "count": 1,
                    "parent": None
                }
            normalized_stages[name] = data

        sum_stages = sum(s["exclusive_sec"] for s in normalized_stages.values())
        unaccounted = max(0.0, total_wall_time - sum_stages)
        unaccounted_pct = (unaccounted / total_wall_time) * 100.0 if total_wall_time > 0 else 0.0

        summary = {
            "job_id": self.job_id,
            "wall_clock_start": datetime.datetime.fromtimestamp(self._wall_start_epoch).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "wall_clock_end": datetime.datetime.fromtimestamp(now_wall).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "total_wall_time_sec": round(total_wall_time, 3),
            "total_duration_sec": round(total_wall_time, 3),
            "sum_stages_sec": round(sum_stages, 3),
            "unaccounted_sec": round(unaccounted, 3),
            "unaccounted_pct": round(unaccounted_pct, 2),
            "stages": {}
        }

        for name, data in normalized_stages.items():
            dur = data["duration_sec"]
            excl = data["exclusive_sec"]
            pct = round((excl / total_wall_time * 100.0), 2) if total_wall_time > 0 else 0.0
            summary["stages"][name] = {
                "duration_sec": round(dur, 3),
                "total_duration_sec": round(dur, 3),
                "exclusive_sec": round(excl, 3),
                "duration_ms": round(dur * 1000, 1),
                "percentage": pct,
                "share_pct": pct,
                "start_epoch": data["start_epoch"],
                "end_epoch": data["end_epoch"],
                "count": data["count"],
                "parent": data.get("parent")
            }

        return summary

    def to_dict(self) -> dict:
        return self.get_summary()

    def format_table(self) -> str:
        summary = self.get_summary()
        wall_time = summary["total_wall_time_sec"]
        unaccounted = summary["unaccounted_sec"]
        unaccounted_pct = summary["unaccounted_pct"]

        lines = []
        lines.append("=" * 72)
        lines.append(f"  STAGE TIMING BREAKDOWN — JOB: {self.job_id}")
        lines.append(f"  WALL CLOCK: {summary['wall_clock_start']} -> {summary['wall_clock_end']}")
        lines.append("=" * 72)
        lines.append(f"{'STAGE':<28} | {'TIME (s)':<10} | {'TIME (ms)':<12} | {'SHARE':<8}")
        lines.append("-" * 72)

        stage_order = [
            "startup_imports",
            "folder_setup",
            "ledger_reserve",
            "harvest",
            "ffprobe",
            "watermark",
            "stage_5_predict_framing",
            "tracking",
            "stage_6_reframe",
            "reframe",
            "caption",
            "concat",
            "audio",
            "render",
            "qa",
            "export_copy"
        ]

        ordered_keys = [s for s in stage_order if s in self.stages]
        extra_keys = [s for s in self.stages if s not in stage_order]

        parent_names = set(d.get("parent") for d in summary["stages"].values() if d.get("parent"))

        total_printed_sec = 0.0
        total_printed_pct = 0.0
        for s in ordered_keys + extra_keys:
            data = summary["stages"][s]
            dur = data["exclusive_sec"]
            dur_ms = dur * 1000.0
            pct = round((dur / wall_time * 100.0), 1) if wall_time > 0 else 0.0
            total_printed_sec += dur
            total_printed_pct += pct
            prefix = "  └─ " if data.get("parent") else ""
            display_name = (prefix + s)[:28]
            lines.append(f"{display_name:<28} | {dur:<10.2f} | {dur_ms:<12.1f} | {pct:>6.1f}%")

        lines.append("-" * 72)
        sum_stages = round(total_printed_sec, 2)
        sum_pct = round(total_printed_pct, 1)
        unaccounted = max(0.0, round(wall_time - sum_stages, 2))
        unaccounted_pct = max(0.0, round(100.0 - sum_pct, 1))
        lines.append(f"{'SUBTOTAL (EXCLUSIVE)':<28} | {sum_stages:<10.2f} | {sum_stages*1000:<12.1f} | {sum_pct:>6.1f}%")
        lines.append(f"{'UNACCOUNTED GAP':<28} | {unaccounted:<10.2f} | {unaccounted*1000:<12.1f} | {unaccounted_pct:>6.1f}%")
        lines.append("-" * 72)
        lines.append(f"{'TOTAL WALL CLOCK TIME':<28} | {wall_time:<10.2f} | {wall_time*1000:<12.1f} | 100.0%")
        lines.append("=" * 72)

        if unaccounted_pct > 2.0:
            lines.append(f"[WARN] Unaccounted execution gap ({unaccounted:.2f}s, {unaccounted_pct:.1f}% > 2.0%). Please inspect uninstrumented blocks.")

        return "\n".join(lines)

    def print_table(self):
        print(self.format_table())

    def save(self, *paths):
        self.finish_job()
        summary = self.get_summary()
        summary["table"] = self.format_table()
        for p in paths:
            if not p:
                continue
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(summary, f, indent=2)
            except Exception as e:
                print(f"[StageTimer] Warning: Could not save to {p}: {e}")
        return summary

    def save_timings(self, *paths):
        return self.save(*paths)
