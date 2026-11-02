"""
LionReel Studio — Ordered Pipeline State Machine
================================================
Enforces strict sequential stage ordering, real data dependencies,
honest status reporting, artifact proof generation, and settings gating.
"""

import os
import sys
import time
import json
import shutil
import traceback

class StageOrderViolationError(RuntimeError):
    pass

class MissingInputError(RuntimeError):
    pass

class EmptyResultError(RuntimeError):
    pass

STAGE_DEFINITIONS = [
    {
        "id": 1,
        "key": "collect_candidates",
        "label": "Collect candidate moments from ledger",
        "prerequisites": [],
        "input_artifact": None,
        "output_artifact": "candidates_reserved.json",
        "toggle_key": None,
        "allow_parallel": False,
        "description": "Connects to clip ledger, cleans stale locks, and reserves candidate clips."
    },
    {
        "id": 2,
        "key": "prepare_sources",
        "label": "Prepare & verify raw source video files",
        "prerequisites": [1],
        "input_artifact": "candidates_reserved.json",
        "output_artifact": "sources_prepared.json",
        "toggle_key": None,
        "allow_parallel": False,
        "description": "Verifies local source files exist on disk, readable, and probes base stream info."
    },
    {
        "id": 3,
        "key": "check_quality_fps",
        "label": "Check source video resolution & frame rate",
        "prerequisites": [2],
        "input_artifact": "sources_prepared.json",
        "output_artifact": "quality_checked.json",
        "toggle_key": "ENFORCE_ASPECT_RATIO",
        "allow_parallel": False,
        "description": "Runs ffprobe fail-fast check to ensure resolution and CFR frame rate meet standards."
    },
    {
        "id": 4,
        "key": "detect_watermarks",
        "label": "Detect watermarks, logos & overlays",
        "prerequisites": [3],
        "input_artifact": "quality_checked.json",
        "output_artifact": "watermark_checked.json",
        "toggle_key": "CHECK_WATERMARK",
        "allow_parallel": False,
        "description": "Samples video corners across candidate windows to detect channel bugs and logos."
    },
    {
        "id": 5,
        "key": "predict_framing",
        "label": "Predict pet framing & select viral moments",
        "prerequisites": [4],
        "input_artifact": "watermark_checked.json",
        "output_artifact": "framing_predicted.json",
        "toggle_key": "CHECK_SHARPNESS",
        "allow_parallel": False,
        "description": "Executes Stage A pre-scoring with YOLOX pet detector, sharpness, and NMS diversity."
    },
    {
        "id": 6,
        "key": "reframe_render_clips",
        "label": "Reframe & render vertical clip cuts",
        "prerequisites": [5],
        "input_artifact": "framing_predicted.json",
        "output_artifact": "clips_rendered.json",
        "toggle_key": "APPLY_SMART_CROP",
        "allow_parallel": False,
        "description": "Executes Stage B crop & render with smoothed trajectories and post-crop centering gate."
    },
    {
        "id": 7,
        "key": "color_grading",
        "label": "Auto color grading & contrast optimization",
        "prerequisites": [6],
        "input_artifact": "clips_rendered.json",
        "output_artifact": "color_graded.json",
        "toggle_key": "APPLY_COLOR_GRADING",
        "allow_parallel": False,
        "description": "Applies CLAHE adaptive contrast normalization and color balance (optional filter)."
    },
    {
        "id": 8,
        "key": "captions_and_audio",
        "label": "Burn safe-zone captions & master audio ducking",
        "prerequisites": [7],
        "input_artifact": "color_graded.json",
        "output_artifact": "audio_mastered.json",
        "toggle_key": "ADD_BACKGROUND_MUSIC",
        "allow_parallel": False,
        "description": "Burns single-clip viral captions in safe zone and masters audio to EBU R128 (-14 LUFS)."
    },
    {
        "id": 9,
        "key": "final_render_qa",
        "label": "Final MP4 assembly & 10-gate QA validation",
        "prerequisites": [8],
        "input_artifact": "audio_mastered.json",
        "output_artifact": "qa_validated.json",
        "toggle_key": None,
        "allow_parallel": False,
        "description": "Concatenates master stream and executes 10 automated pre-upload quality gates."
    },
    {
        "id": 10,
        "key": "save_credits_export",
        "label": "Save master, register credits & export to Drive",
        "prerequisites": [9],
        "input_artifact": "qa_validated.json",
        "output_artifact": "export_complete.json",
        "toggle_key": None,
        "allow_parallel": False,
        "description": "Registers output in clip ledger with SHA256, writes credits/mapping, and saves to finished."
    }
]

class StageStateMachine:
    def __init__(self, job_id: str, work_dir: str, config: dict = None, heartbeat = None):
        self.job_id = job_id
        self.work_dir = work_dir
        self.config = config or {}
        self.heartbeat = heartbeat
        self.stages_dir = os.path.join(work_dir, "stages")
        os.makedirs(self.stages_dir, exist_ok=True)
        self.state_file = os.path.join(work_dir, "stages_state.json")
        
        # Initialize internal state structure
        self.stages = []
        for d in STAGE_DEFINITIONS:
            self.stages.append({
                "id": d["id"],
                "key": d["key"],
                "label": d["label"],
                "status": "PENDING", # PENDING, RUNNING, DONE, SKIPPED, CACHED, FAILED
                "duration_sec": 0.0,
                "evidence": "",
                "details": {},
                "reason": "",
                "start_time": None,
                "end_time": None,
                "input_artifact": d["input_artifact"],
                "output_artifact": d["output_artifact"],
                "toggle_key": d["toggle_key"],
                "allow_parallel": d["allow_parallel"]
            })
        self._save_state()

    def _get_stage(self, stage_id_or_key):
        for s in self.stages:
            if s["id"] == stage_id_or_key or s["key"] == stage_id_or_key:
                return s
        return None

    def _save_state(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump({
                    "job_id": self.job_id,
                    "updated_at": time.time(),
                    "stages": self.stages
                }, f, indent=2)
        except Exception:
            pass

    def get_stage_definitions(self):
        return STAGE_DEFINITIONS

    def get_all_stages(self):
        return self.stages

    def get_stages_summary(self):
        return self.stages

    def start_stage(self, stage_id_or_key):
        s = self._get_stage(stage_id_or_key)
        if not s:
            raise ValueError(f"Unknown stage: {stage_id_or_key}")

        stage_id = s["id"]
        stage_key = s["key"]
        definition = STAGE_DEFINITIONS[stage_id - 1]

        # 1. Enforce Prerequisites (Order Check)
        for prereq_id in definition["prerequisites"]:
            prereq_stage = self._get_stage(prereq_id)
            if not prereq_stage:
                continue
            if prereq_stage["status"] not in ("DONE", "SKIPPED", "CACHED"):
                err_msg = (
                    f"STAGE_ORDER_VIOLATION: Cannot start Stage {stage_id} ('{s['label']}') "
                    f"because prerequisite Stage {prereq_id} ('{prereq_stage['label']}') "
                    f"is in state '{prereq_stage['status']}' (expected DONE, SKIPPED, or CACHED)."
                )
                self.fail_stage(stage_id, err_msg, code="STAGE_ORDER_VIOLATION")
                raise StageOrderViolationError(err_msg)

        # 2. Check Data Dependency: Input Artifact Must Exist and Be Non-Empty
        input_art = definition["input_artifact"]
        if input_art:
            art_path = os.path.join(self.stages_dir, input_art)
            if not os.path.exists(art_path):
                err_msg = f"MISSING_INPUT: Stage {stage_id} requires artifact '{input_art}' which does not exist."
                self.fail_stage(stage_id, err_msg, code="MISSING_INPUT")
                raise MissingInputError(err_msg)
            try:
                with open(art_path, "r", encoding="utf-8") as f_art:
                    data = json.load(f_art)
                if not data or (isinstance(data, (list, dict)) and len(data) == 0):
                    err_msg = f"MISSING_INPUT: Stage {stage_id} artifact '{input_art}' is empty."
                    self.fail_stage(stage_id, err_msg, code="MISSING_INPUT")
                    raise MissingInputError(err_msg)
            except Exception as e_read:
                err_msg = f"MISSING_INPUT: Could not parse input artifact '{input_art}': {e_read}"
                self.fail_stage(stage_id, err_msg, code="MISSING_INPUT")
                raise MissingInputError(err_msg)

        s["status"] = "RUNNING"
        s["start_time"] = time.time()
        if hasattr(self, "heartbeat") and self.heartbeat:
            try:
                self.heartbeat.set_stage(stage_id, s["label"])
            except Exception:
                pass
        self._save_state()
        return s

    def complete_stage(self, stage_id_or_key, evidence: str, proof_data: dict = None, is_cached: bool = False, cache_meta: dict = None):
        s = self._get_stage(stage_id_or_key)
        if not s:
            raise ValueError(f"Unknown stage: {stage_id_or_key}")

        stage_id = s["id"]
        definition = STAGE_DEFINITIONS[stage_id - 1]
        now = time.time()
        s["end_time"] = now
        start_t = s["start_time"] or now
        dur = max(0.01, round(now - start_t, 2))
        s["duration_sec"] = dur

        # Truthful stage evidence: preserve real evidence without fake instant verification text
        if is_cached and "cached" not in evidence.lower():
            evidence = f"{evidence} (cached result reused)"

        # Detect compute device
        device_name = "CPU"
        try:
            import torch
            if torch.cuda.is_available():
                device_name = f"NVIDIA CUDA ({torch.cuda.get_device_name(0)})"
        except Exception:
            pass

        proof = proof_data or {}
        proof.setdefault("device", device_name)
        proof.update({
            "stage_id": stage_id,
            "stage_key": s["key"],
            "job_id": self.job_id,
            "duration_sec": dur,
            "timings": {
                "start_time": s["start_time"],
                "end_time": s["end_time"],
                "duration_sec": dur
            },
            "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "evidence": evidence
        })

        # 3. Check for Empty Result where items were expected
        items_count = proof.get("items_count") if "items_count" in proof else (
            proof.get("count") if "count" in proof else (
                proof.get("candidates_count") if "candidates_count" in proof else (
                    proof.get("clips_count") if "clips_count" in proof else None
                )
            )
        )
        if items_count == 0 and proof.get("allow_empty") is not True:
            err_msg = f"EMPTY_RESULT: Stage {stage_id} ('{s['label']}') produced 0 items where items were expected."
            self.fail_stage(stage_id, err_msg, code="EMPTY_RESULT")
            raise EmptyResultError(err_msg)

        # Write stage proof file: both n_key.json and n_n.json for compatibility
        proof_filename = f"{stage_id}_{s['key']}.json"
        proof_path = os.path.join(self.stages_dir, proof_filename)
        with open(proof_path, "w", encoding="utf-8") as f_pf:
            json.dump(proof, f_pf, indent=2)
        alt_proof_path = os.path.join(self.stages_dir, f"{stage_id}_{stage_id}.json")
        try:
            shutil.copy2(proof_path, alt_proof_path)
        except Exception:
            pass

        # Write designated output artifact if specified
        output_art = definition["output_artifact"]
        if output_art:
            art_path = os.path.join(self.stages_dir, output_art)
            with open(art_path, "w", encoding="utf-8") as f_art:
                json.dump(proof, f_art, indent=2)

        s["status"] = "CACHED" if is_cached else "DONE"
        s["evidence"] = evidence
        stage_details = dict(cache_meta or {})
        if items_count is not None:
            stage_details["units_done"] = items_count
        target_cnt = proof.get("target_clips") or proof.get("target_count") or proof.get("candidate_target")
        if target_cnt is not None:
            stage_details["units_total"] = target_cnt
        s["details"] = stage_details
        self._save_state()
        if hasattr(self, "heartbeat") and self.heartbeat:
            try:
                self.heartbeat.step_counter()
            except Exception:
                pass

        # Record stage completion in historical estimator database
        try:
            from stage_estimator import StageEstimator
            estimator = StageEstimator()
            target_clips = int(self.config.get("TARGET_CLIPS", 6))
            clip_time = float(self.config.get("SHORT_CLIP_SEC", 7.5))
            mode = str(self.config.get("VIDEO_TYPE", "short")).lower()
            layout = str(self.config.get("LAYOUT_MODE", "smart_crop")).lower()
            u_done = items_count if items_count is not None else 0
            u_tot = proof.get("target_count", target_clips)
            estimator.record_stage_execution(
                job_id=self.job_id,
                stage_id=stage_id,
                stage_key=s["key"],
                duration_sec=dur,
                units_done=u_done,
                units_total=u_tot,
                clips_count=target_clips,
                clip_time=clip_time,
                mode=mode,
                layout=layout,
                is_cached=1 if is_cached else 0
            )
        except Exception:
            pass

        return s

    def update_stage_progress(self, stage_id_or_key, units_done: int, units_total: int, unit_type: str = "", note: str = ""):
        """Updates intra-stage work units (candidates, clips, frames) for real-time progress & ETA calculation."""
        s = self._get_stage(stage_id_or_key)
        if not s:
            return
        if "details" not in s or not isinstance(s["details"], dict):
            s["details"] = {}
        s["details"]["units_done"] = int(units_done)
        s["details"]["units_total"] = int(units_total)
        s["details"]["unit_type"] = unit_type
        if note:
            s["details"]["note"] = note
        self._save_state()

    def skip_stage(self, stage_id_or_key, reason: str = "turned off in settings", proof_data: dict = None):
        s = self._get_stage(stage_id_or_key)
        if not s:
            raise ValueError(f"Unknown stage: {stage_id_or_key}")

        stage_id = s["id"]
        definition = STAGE_DEFINITIONS[stage_id - 1]

        # Enforce Prerequisites even on skip
        for prereq_id in definition["prerequisites"]:
            prereq_stage = self._get_stage(prereq_id)
            if not prereq_stage:
                continue
            if prereq_stage["status"] not in ("DONE", "SKIPPED", "CACHED"):
                err_msg = (
                    f"STAGE_ORDER_VIOLATION: Cannot skip Stage {stage_id} ('{s['label']}') "
                    f"because prerequisite Stage {prereq_id} ('{prereq_stage['label']}') "
                    f"is in state '{prereq_stage['status']}' (expected DONE, SKIPPED, or CACHED)."
                )
                self.fail_stage(stage_id, err_msg, code="STAGE_ORDER_VIOLATION")
                raise StageOrderViolationError(err_msg)

        now = time.time()
        s["end_time"] = now
        start_t = s["start_time"] or now
        s["duration_sec"] = max(0.01, round(now - start_t, 2))

        device_name = "CPU"
        proof = proof_data or {}
        proof.setdefault("device", device_name)
        proof.update({
            "stage_id": stage_id,
            "stage_key": s["key"],
            "job_id": self.job_id,
            "status": "SKIPPED",
            "reason": reason,
            "completed_at": time.strftime("%Y-%m-%d %H:%M:%S")
        })

        proof_filename = f"{stage_id}_{s['key']}.json"
        proof_path = os.path.join(self.stages_dir, proof_filename)
        with open(proof_path, "w", encoding="utf-8") as f_pf:
            json.dump(proof, f_pf, indent=2)
        try:
            shutil.copy2(proof_path, os.path.join(self.stages_dir, f"{stage_id}_{stage_id}.json"))
        except Exception:
            pass

        # If previous artifact exists, pass it forward so subsequent stages don't fail missing input
        output_art = definition["output_artifact"]
        input_art = definition["input_artifact"]
        if output_art:
            art_path = os.path.join(self.stages_dir, output_art)
            if input_art and os.path.exists(os.path.join(self.stages_dir, input_art)):
                shutil.copy2(os.path.join(self.stages_dir, input_art), art_path)
            else:
                with open(art_path, "w", encoding="utf-8") as f_art:
                    json.dump(proof, f_art, indent=2)

        s["status"] = "SKIPPED"
        s["reason"] = reason
        s["evidence"] = f"Skipped: {reason}"
        self._save_state()
        return s

    def fail_stage(self, stage_id_or_key, error_msg: str, code: str = None):
        s = self._get_stage(stage_id_or_key)
        if not s:
            return
        now = time.time()
        s["end_time"] = now
        start_t = s["start_time"] or now
        s["duration_sec"] = max(0.01, round(now - start_t, 2))
        s["status"] = "FAILED"
        s["reason"] = error_msg
        s["evidence"] = f"Failed: {error_msg}"
        s["details"] = {"error": error_msg, "code": code}

        proof_filename = f"{s['id']}_{s['key']}.json"
        proof_path = os.path.join(self.stages_dir, proof_filename)
        with open(proof_path, "w", encoding="utf-8") as f_pf:
            json.dump({
                "stage_id": s["id"],
                "stage_key": s["key"],
                "job_id": self.job_id,
                "status": "FAILED",
                "error": error_msg,
                "code": code,
                "failed_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }, f_pf, indent=2)

        self._save_state()
        return s
