"""
LionReel Studio — Edit Decision List (EDL) Manager
Manages per-job non-destructive video edits (in/out trims, reordering,
color enhancement presets, playback speed, and crop reframing).
"""

import os
import json
import time
from typing import Dict, Any, List, Optional
from clip_ledger import ClipLedger
from auto_reframe import AutoReframeEngine
from source_utils import probe_video_fast

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_work_dir() -> str:
    cfg_file = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                c = json.load(f)
                if c.get("LOCAL_WORK_DIR"):
                    return c["LOCAL_WORK_DIR"]
        except Exception:
            pass
    local_p = os.path.join("C:\\", "LionReel", "work")
    if os.path.exists(local_p):
        return local_p
    return os.path.join(BASE_DIR, "work")

WORK_DIR = get_work_dir()


class EDLManager:
    def __init__(self, ledger: Optional[ClipLedger] = None):
        self.ledger = ledger or ClipLedger()
        self.reframer = AutoReframeEngine()

    def get_edl_path(self, job_id: str) -> str:
        j_dir = os.path.join(WORK_DIR, job_id)
        os.makedirs(j_dir, exist_ok=True)
        return os.path.join(j_dir, "edl.json")

    def get_edl(self, job_id: str) -> Dict[str, Any]:
        """Loads existing EDL or initializes one from job stages / verified clip bank."""
        edl_path = self.get_edl_path(job_id)
        if os.path.exists(edl_path):
            try:
                with open(edl_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        # If not saved, construct initial default EDL from job artifacts
        j_dir = os.path.join(WORK_DIR, job_id)
        stages_dir = os.path.join(j_dir, "stages")

        clips = []
        global_settings = {
            "color_grading_enabled": False,
            "default_preset": "natural",
            "safe_zone": "tiktok"
        }

        # 1. Check clips_rendered.json (Stage 6 output)
        rendered_path = os.path.join(stages_dir, "clips_rendered.json")
        if os.path.exists(rendered_path):
            try:
                with open(rendered_path, "r", encoding="utf-8") as f:
                    rdata = json.load(f)
                mapping = rdata.get("clip_mapping_data", [])
                reports = {r["clip_id"]: r for r in rdata.get("candidate_reports", [])}
                for idx, m in enumerate(mapping):
                    cid = m.get("clip_id")
                    rep = reports.get(cid, {})
                    plan = rep.get("plan", {})
                    src = m.get("source_file") or rep.get("source", "")
                    full_src = src if os.path.isabs(src) else os.path.join(BASE_DIR, src)
                    probe = probe_video_fast(full_src) if os.path.exists(full_src) else {"duration": 30.0}

                    clips.append({
                        "clip_index": idx,
                        "clip_id": cid or f"clip_{idx+1}",
                        "source_file": src,
                        "source_abs_path": full_src,
                        "title": m.get("title") or f"Moment {idx+1} ({os.path.basename(src)})",
                        "author": m.get("credit", "Verified CC Archive"),
                        "license": m.get("license", "Creative Commons Attribution 4.0"),
                        "source_duration": round(probe.get("duration", 30.0), 2),
                        "trim_start": round(m.get("start_s", 0.0), 2),
                        "trim_end": round(m.get("end_s", 10.0), 2),
                        "duration": round(m.get("duration", 10.0), 2),
                        "speed": 1.0,
                        "color_preset": "natural",
                        "color_strength": 1.0,
                        "framing_score": round(rep.get("actual_score", rep.get("score", 0.95)), 3),
                        "crop_plan": plan
                    })
            except Exception:
                pass

        # 2. Check framing_predicted.json (Stage 5 output) if rendered not yet ready
        if not clips:
            pred_path = os.path.join(stages_dir, "framing_predicted.json")
            if os.path.exists(pred_path):
                try:
                    with open(pred_path, "r", encoding="utf-8") as f:
                        pdata = json.load(f)
                    passing = pdata.get("passing_candidates", [])
                    for idx, cand in enumerate(passing[:6]):
                        cinfo = cand.get("clip_info", {})
                        src = cand.get("source", "")
                        full_src = cinfo.get("source_url_or_path") or os.path.join(BASE_DIR, src)
                        probe = probe_video_fast(full_src) if os.path.exists(full_src) else {"duration": 30.0}
                        dur = round(cinfo.get("end_s", 10.0) - cinfo.get("start_s", 0.0), 2)
                        clips.append({
                            "clip_index": idx,
                            "clip_id": cand.get("clip_id") or f"cand_{idx+1}",
                            "source_file": src,
                            "source_abs_path": full_src,
                            "title": cinfo.get("title") or f"Moment {idx+1} ({os.path.basename(src)})",
                            "author": cinfo.get("uploader") or cinfo.get("channel") or "Verified CC Archive",
                            "license": cinfo.get("license", "Creative Commons Attribution 4.0"),
                            "source_duration": round(probe.get("duration", 30.0), 2),
                            "trim_start": round(cinfo.get("start_s", 0.0), 2),
                            "trim_end": round(cinfo.get("end_s", 10.0), 2),
                            "duration": dur,
                            "speed": 1.0,
                            "color_preset": "natural",
                            "color_strength": 1.0,
                            "framing_score": round(cand.get("score", 0.95), 3),
                            "crop_plan": cand.get("plan", {})
                        })
                except Exception:
                    pass

        # 3. Fallback: Seed initial EDL from verified clip bank
        if not clips:
            try:
                verified_clips = self.get_available_clip_bank(limit=4)
                for idx, vc in enumerate(verified_clips):
                    clips.append({
                        "clip_index": idx,
                        "clip_id": vc["clip_id"],
                        "source_file": vc["source_url_or_path"],
                        "source_abs_path": vc["source_url_or_path"],
                        "title": vc.get("title") or f"Clip {idx+1}",
                        "author": vc.get("uploader") or "Verified CC Archive",
                        "license": vc.get("license", "Creative Commons Attribution 4.0"),
                        "source_duration": round(vc.get("end_s", 10.0) + 10.0, 2),
                        "trim_start": round(vc["start_s"], 2),
                        "trim_end": round(vc["end_s"], 2),
                        "duration": round(vc["end_s"] - vc["start_s"], 2),
                        "speed": 1.0,
                        "color_preset": "natural",
                        "color_strength": 1.0,
                        "framing_score": round(vc.get("framing_score", 0.95), 3),
                        "crop_plan": vc.get("verified_plan") or {}
                    })
            except Exception:
                pass

        edl = {
            "job_id": job_id,
            "version": 1,
            "last_modified": time.time(),
            "global_settings": global_settings,
            "clips": clips
        }

        # Save generated default EDL
        try:
            with open(edl_path, "w", encoding="utf-8") as f:
                json.dump(edl, f, indent=2)
        except Exception:
            pass

        return edl

    def save_edl(self, job_id: str, new_edl: Dict[str, Any]) -> Dict[str, Any]:
        """Validates and saves updated EDL to disk."""
        edl_path = self.get_edl_path(job_id)
        raw_clips = new_edl.get("clips", [])
        sanitized_clips = []

        for idx, c in enumerate(raw_clips):
            t_start = max(0.0, float(c.get("trim_start", 0.0)))
            t_end = float(c.get("trim_end", t_start + 5.5))
            if t_end <= t_start + 1.0:
                t_end = t_start + 5.5

            speed = float(c.get("speed", 1.0))
            if speed not in (0.75, 1.0, 1.25, 1.5):
                speed = 1.0

            dur = round((t_end - t_start) / speed, 2)

            sanitized_clips.append({
                "clip_index": idx,
                "clip_id": c.get("clip_id") or f"clip_{idx+1}",
                "source_file": c.get("source_file", ""),
                "source_abs_path": c.get("source_abs_path", c.get("source_file", "")),
                "title": c.get("title", f"Clip {idx+1}"),
                "author": c.get("author", "Verified CC Archive"),
                "license": c.get("license", "Creative Commons Attribution 4.0"),
                "source_duration": float(c.get("source_duration", 30.0)),
                "trim_start": round(t_start, 2),
                "trim_end": round(t_end, 2),
                "duration": dur,
                "speed": speed,
                "color_preset": c.get("color_preset", "natural"),
                "color_strength": min(1.0, max(0.0, float(c.get("color_strength", 1.0)))),
                "framing_score": float(c.get("framing_score", 0.95)),
                "crop_plan": c.get("crop_plan", {})
            })

        curr_ver = new_edl.get("version", 1)
        edl_payload = {
            "job_id": job_id,
            "version": curr_ver + 1,
            "last_modified": time.time(),
            "global_settings": new_edl.get("global_settings", {
                "color_grading_enabled": False,
                "default_preset": "natural",
                "safe_zone": "tiktok"
            }),
            "clips": sanitized_clips
        }

        with open(edl_path, "w", encoding="utf-8") as f:
            json.dump(edl_payload, f, indent=2)

        return edl_payload

    def check_framing(self, source_file: str, start_sec: float, duration_sec: float) -> Dict[str, Any]:
        """Runs live debounced framing check on adjusted trim window."""
        full_path = source_file if os.path.isabs(source_file) else os.path.join(BASE_DIR, source_file)
        if not os.path.exists(full_path):
            return {"passed": False, "score": 0.0, "reason": "SOURCE_NOT_FOUND"}

        try:
            plan = self.reframer.plan_reframe(
                video_path=full_path,
                start_s=start_sec,
                dur_s=duration_sec,
                layout_mode="smart_crop",
                allow_slide=False
            )
            score = plan.get("framing_score", 0.0)
            passed = (score >= 0.90) and (plan.get("status") == "pass")
            return {
                "passed": passed,
                "score": round(score, 3),
                "centering_pct": round(score * 100.0, 1),
                "plan": plan,
                "reason": plan.get("reason", "PASS" if passed else "LOW_CENTERING")
            }
        except Exception as e:
            return {"passed": False, "score": 0.0, "reason": str(e)}

    def get_available_clip_bank(self, animal_type: str = "cat", limit: int = 50) -> List[Dict[str, Any]]:
        """Queries verified unused clips from the ledger bank for the Replace Clip modal."""
        with self.ledger._get_conn() as conn:
            cur = conn.execute("""
                SELECT clip_id, source_id, source_url_or_path, license, start_s, end_s,
                       quality_score, framing_score, orientation, uploader, title, verified_plan
                FROM clips 
                WHERE animal_type = ? AND is_verified = 1 AND times_used == 0
                ORDER BY framing_score DESC, quality_score DESC
                LIMIT ?
            """, (animal_type, limit))
            results = []
            for r in cur.fetchall():
                d = dict(r)
                if d.get("verified_plan") and isinstance(d["verified_plan"], str):
                    try:
                        d["verified_plan"] = json.loads(d["verified_plan"])
                    except:
                        pass
                results.append(d)
            return results

    def replace_clip_in_edl(self, job_id: str, clip_index: int, replacement_clip_id: str) -> Dict[str, Any]:
        """Swaps clip at clip_index with a verified clip from the bank."""
        edl = self.get_edl(job_id)
        clips = edl.get("clips", [])
        if clip_index < 0 or clip_index >= len(clips):
            raise ValueError(f"Invalid clip index {clip_index}")

        # Look up replacement clip
        with self.ledger._get_conn() as conn:
            cur = conn.execute("SELECT * FROM clips WHERE clip_id = ?", (replacement_clip_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Clip {replacement_clip_id} not found in ledger")
            rep_clip = dict(row)

        src_path = rep_clip["source_url_or_path"]
        probe = probe_video_fast(src_path) if os.path.exists(src_path) else {"duration": 30.0}

        plan = {}
        if rep_clip.get("verified_plan"):
            try:
                plan = json.loads(rep_clip["verified_plan"]) if isinstance(rep_clip["verified_plan"], str) else rep_clip["verified_plan"]
            except:
                pass

        clips[clip_index] = {
            "clip_index": clip_index,
            "clip_id": rep_clip["clip_id"],
            "source_file": src_path,
            "source_abs_path": src_path,
            "title": rep_clip.get("title") or os.path.basename(src_path),
            "author": rep_clip.get("uploader") or "Verified CC Contributor",
            "license": rep_clip.get("license", "Creative Commons Attribution 4.0"),
            "source_duration": round(probe.get("duration", 30.0), 2),
            "trim_start": round(rep_clip["start_s"], 2),
            "trim_end": round(rep_clip["end_s"], 2),
            "duration": round(rep_clip["end_s"] - rep_clip["start_s"], 2),
            "speed": 1.0,
            "color_preset": "natural",
            "color_strength": 1.0,
            "framing_score": round(rep_clip.get("framing_score", 0.95), 3),
            "crop_plan": plan
        }

        edl["clips"] = clips
        return self.save_edl(job_id, edl)
