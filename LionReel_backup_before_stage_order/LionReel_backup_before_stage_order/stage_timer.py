"""
LionReel Pipeline Stage Timer
Logs the exact execution duration of each pipeline stage to the console and timings.json.
"""

import time
import json
import os

class StageTimer:
    def __init__(self, job_id: str = "default_job"):
        self.job_id = job_id
        self.stages = {}
        self._active_stage = None
        self._active_start = None
        self.total_start = time.perf_counter()

    def start_stage(self, name: str):
        if self._active_stage and self._active_start is not None:
            self.stop_stage(self._active_stage)
        self._active_stage = name
        self._active_start = time.perf_counter()

    def stop_stage(self, name: str = None):
        if name is None:
            name = self._active_stage
        if not name or self._active_start is None:
            return
        elapsed = time.perf_counter() - self._active_start
        self.stages[name] = self.stages.get(name, 0.0) + elapsed
        self._active_stage = None
        self._active_start = None

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

    def get_summary(self) -> dict:
        total_time = sum(self.stages.values())
        summary = {
            "job_id": self.job_id,
            "total_duration_sec": round(total_time, 2),
            "stages": {}
        }
        for name, dur in self.stages.items():
            pct = round((dur / total_time * 100.0), 1) if total_time > 0 else 0.0
            summary["stages"][name] = {
                "duration_sec": round(dur, 2),
                "duration_ms": round(dur * 1000, 1),
                "percentage": pct
            }
        return summary

    def to_dict(self) -> dict:
        return self.get_summary()

    def format_table(self) -> str:
        total_time = sum(self.stages.values())
        lines = []
        lines.append("=" * 68)
        lines.append(f"  STAGE TIMING BREAKDOWN — JOB: {self.job_id}")
        lines.append("=" * 68)
        lines.append(f"{'STAGE':<26} | {'TIME (s)':<10} | {'TIME (ms)':<12} | {'SHARE':<8}")
        lines.append("-" * 68)
        
        # Consistent ordering of pipeline stages
        stage_order = [
            "startup_imports",
            "folder_setup",
            "ledger_reserve",
            "harvest",
            "ffprobe",
            "watermark",
            "tracking",
            "reframe",
            "caption",
            "concat",
            "audio",
            "render",
            "qa",
            "export_copy"
        ]
        
        # Display ordered stages first, then any extra stages
        ordered_keys = [s for s in stage_order if s in self.stages]
        extra_keys = [s for s in self.stages if s not in stage_order]

        for s in ordered_keys + extra_keys:
            dur = self.stages[s]
            dur_ms = dur * 1000
            pct = (dur / total_time * 100.0) if total_time > 0 else 0.0
            lines.append(f"{s:<26} | {dur:<10.2f} | {dur_ms:<12.1f} | {pct:>5.1f}%")

        lines.append("-" * 68)
        lines.append(f"{'TOTAL PIPELINE TIME':<26} | {total_time:<10.2f} | {total_time*1000:<12.1f} | 100.0%")
        lines.append("=" * 68)
        return "\n".join(lines)

    def print_table(self):
        print(self.format_table())

    def save(self, *paths):
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

