#!/usr/bin/env python3
"""
LionReel Studio — Funny-Moment Detector & Event-Aware Window Engine (Phase 2 & 3)
Analyzes video and audio at 10 Hz with multi-signal event extraction:
- Pretrained YAMNet AudioSet tagger (meow, hiss, purr, bark, laughter, impacts, crashes)
- Optical flow inside pet bounding box + pet velocity, acceleration, direction reversals
- Interaction detection with people and objects
- Shot boundary (scene cut) detection with compilation source awareness
- Frame-accurate boundary refinement snapping to low-motion and silence gaps
- Hard gate: FUNNY_PART_PRESENT
"""

import os
import sys
import math
import csv
import json
import sqlite3
import hashlib
import subprocess
import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")
MODELS_DIR = os.path.join(ASSETS_DIR, "models")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CACHE_DB_PATH = os.path.join(DATA_DIR, "timeline_cache.db")

YAMNET_MODEL_PATH = os.path.join(MODELS_DIR, "yamnet.onnx")
YAMNET_MAP_PATH = os.path.join(MODELS_DIR, "yamnet_class_map.csv")
YOLOX_MODEL_PATH = os.path.join(MODELS_DIR, "object_detection_yolox_2022nov.onnx")

ANALYZER_VERSION = "v2_10hz_yamnet"

def get_ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

FFMPEG_EXE = get_ffmpeg_exe()

# -------------------------------------------------------------
# FunnyEvent Data Representation & Helpers (Phase 2 & 3)
# -------------------------------------------------------------
class FunnyEvent(dict):
    """
    Representation of a detected funny moment/event.
    Acts as both a dictionary and an object (attribute access).
    """
    def __init__(self, onset_s: float, peak_s: float, end_s: float, score: float, 
                 trigger_type: str = "viral_action", event_id: str = "ev_1", 
                 details: dict = None, **kwargs):
        super().__init__(
            onset_s=float(onset_s),
            peak_s=float(peak_s),
            end_s=float(end_s),
            score=float(score),
            trigger_type=trigger_type,
            event_id=event_id,
            details=details or {},
            duration_s=round(float(end_s) - float(onset_s), 2),
            **kwargs
        )

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(f"'FunnyEvent' object has no attribute '{item}'")

    def __setattr__(self, key, value):
        self[key] = value

def validate_window_funny_part(event, win_start: float, win_end: float, shots: list = None, score_threshold: float = 0.35):
    """
    Validation gate "FUNNY_PART_PRESENT":
    - event score >= threshold
    - onset/peak has sufficient lead-in and aftermath
    - no scene cut inside window
    Returns: (passed: bool, reason: str)
    """
    score = event.get("score", 0.0) if isinstance(event, dict) else getattr(event, "score", 0.0)
    onset_s = event.get("onset_s", win_start) if isinstance(event, dict) else getattr(event, "onset_s", win_start)
    peak_s = event.get("peak_s", (win_start + win_end) / 2.0) if isinstance(event, dict) else getattr(event, "peak_s", (win_start + win_end) / 2.0)
    end_s = event.get("end_s", win_end) if isinstance(event, dict) else getattr(event, "end_s", win_end)

    if score < score_threshold:
        return False, "FUNNY_PART_MISSING"

    # Check scene cut crossings
    if shots:
        cut_points = set()
        for s in shots:
            if s[0] > 0.0:
                cut_points.add(s[0])
            cut_points.add(s[1])
        for c in cut_points:
            if win_start < c < win_end:
                return False, "CROSSES_SHOT_CUT"

    # Check lead-in and aftermath
    if (peak_s - win_start) < 1.0:
        return False, "LEAD_IN_TOO_SHORT"
    if (win_end - peak_s) < 1.0:
        return False, "AFTERMATH_TOO_SHORT"

    return True, "OK"

def place_shot_aware_window(event=None, shots=None, source_dur=None, target_dur=10.0, source_path=None, target_dur_s=None):
    """
    Places an optimal clip window around an event.
    Can be called either:
    1) As a function with (event, shots, source_dur, target_dur) -> returns (win_start, win_end, win_peak, passed, reason)
    2) As a helper with (source_path, event, target_dur_s) -> returns dict
    """
    if source_path is not None and shots is None:
        det = FunnyEventDetector()
        dur = target_dur_s if target_dur_s is not None else target_dur
        return det.place_shot_aware_window(source_path, event, target_dur_s=dur)

    if isinstance(event, dict):
        onset_s = float(event.get("onset_s", 0.0))
        peak_s = float(event.get("peak_s", 0.0))
        end_s = float(event.get("end_s", 0.0))
        score = float(event.get("score", 0.0))
    else:
        onset_s = float(getattr(event, "onset_s", 0.0))
        peak_s = float(getattr(event, "peak_s", 0.0))
        end_s = float(getattr(event, "end_s", 0.0))
        score = float(getattr(event, "score", 0.0))

    if source_dur is None:
        source_dur = max(s[1] for s in shots) if shots else 60.0

    # Find the single shot containing this peak
    shot_start = 0.0
    shot_end = source_dur
    if shots:
        for s in shots:
            if s[0] <= peak_s <= s[1]:
                shot_start = s[0]
                shot_end = s[1]
                break

    shot_len = shot_end - shot_start
    clip_dur = min(target_dur, max(1.0, shot_len - 0.1))

    # Ideal peak placement: 40% into clip
    ideal_start = peak_s - (clip_dur * 0.40)
    ideal_end = ideal_start + clip_dur

    # Clamp strictly inside shot boundaries
    margin = 0.05
    if ideal_start < shot_start + margin:
        ideal_start = shot_start + margin
        ideal_end = min(shot_end - margin, ideal_start + clip_dur)

    if ideal_end > shot_end - margin:
        ideal_end = shot_end - margin
        ideal_start = max(shot_start + margin, ideal_end - clip_dur)

    win_start = round(ideal_start, 2)
    win_end = round(ideal_end, 2)
    win_peak = round(peak_s, 2)

    passed, reason = validate_window_funny_part(event, win_start, win_end, shots, score_threshold=0.30)
    return win_start, win_end, win_peak, passed, reason

# -------------------------------------------------------------
# 1. Timeline Cache Database (Source Hash + Version)
# -------------------------------------------------------------
def get_db_conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB_PATH, timeout=60.0)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS timeline_cache (
            source_hash TEXT,
            analyzer_version TEXT,
            source_name TEXT,
            duration REAL,
            is_compilation INTEGER,
            scene_cuts TEXT,
            timeline_json TEXT,
            events_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (source_hash, analyzer_version)
        )
    """)
    conn.commit()
    return conn

def compute_file_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(131072):
            h.update(chunk)
    return h.hexdigest()

# -------------------------------------------------------------
# 2. YAMNet Pretrained Audio Classifier (ONNX Runtime)
# -------------------------------------------------------------
class YAMNetTagger:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(YAMNetTagger, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        import onnxruntime as ort
        self.session = ort.InferenceSession(YAMNET_MODEL_PATH, providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name
        
        # Load class map
        self.class_names = {}
        if os.path.exists(YAMNET_MAP_PATH):
            with open(YAMNET_MAP_PATH, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    self.class_names[int(r["index"])] = r["display_name"].strip()

        # Target class groups in AudioSet:
        self.cat_indices = [76, 77, 78, 79, 80]       # Cat, Purr, Meow, Hiss, Caterwaul
        self.dog_indices = [69, 70, 75]               # Dog, Bark, Whimper
        self.laugh_indices = [13, 14, 15, 16, 17]     # Laughter, Baby laughter, Giggle, Snicker, Belly laugh
        self.impact_indices = [438, 439, 440, 443, 444, 445] # Thump, Knock, Door slam, Glass break, Crash, Smash
        self._initialized = True

    def extract_audio_16k(self, video_path: str) -> np.ndarray:
        """Extracts 16kHz mono 16-bit PCM audio directly via ffmpeg."""
        cmd = [
            FFMPEG_EXE, "-y", "-i", video_path,
            "-vn", "-ar", "16000", "-ac", "1", "-f", "s16le", "-"
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        raw_bytes, _ = proc.communicate()
        if not raw_bytes:
            return np.zeros(16000, dtype=np.float32)
        samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return samples

    def classify_timeline(self, video_path: str, target_len_s: float) -> dict:
        """Runs YAMNet classification and returns 10 Hz resampled probability tracks."""
        samples = self.extract_audio_16k(video_path)
        total_samples = len(samples)
        
        # YAMNet processes full waveform, produces 0.48s step predictions
        raw_outputs = self.session.run(None, {self.input_name: samples})
        scores = raw_outputs[0]  # Shape (N_frames, 521)
        
        # Compute RMS energy at 10 Hz (1600 samples per 100ms window)
        hop_10hz = 1600
        n_steps_10hz = int(math.ceil(total_samples / hop_10hz))
        rms_10hz = np.zeros(n_steps_10hz, dtype=np.float32)
        for i in range(n_steps_10hz):
            st = i * hop_10hz
            en = min(total_samples, st + hop_10hz)
            if en > st:
                chunk = samples[st:en]
                rms_10hz[i] = float(np.sqrt(np.mean(chunk**2) + 1e-9))

        # YAMNet frames are spaced by 0.48s (first frame centered around 0.48s)
        n_yamnet = len(scores)
        yamnet_times = np.array([0.24 + i * 0.48 for i in range(n_yamnet)])
        timeline_times = np.array([i * 0.1 for i in range(n_steps_10hz)])

        cat_scores_raw = np.max(scores[:, self.cat_indices], axis=1) if n_yamnet else np.zeros(1)
        dog_scores_raw = np.max(scores[:, self.dog_indices], axis=1) if n_yamnet else np.zeros(1)
        laugh_scores_raw = np.max(scores[:, self.laugh_indices], axis=1) if n_yamnet else np.zeros(1)
        impact_scores_raw = np.max(scores[:, self.impact_indices], axis=1) if n_yamnet else np.zeros(1)

        # Interpolate onto 10 Hz timeline
        cat_10hz = np.interp(timeline_times, yamnet_times, cat_scores_raw) if n_yamnet else np.zeros_like(timeline_times)
        dog_10hz = np.interp(timeline_times, yamnet_times, dog_scores_raw) if n_yamnet else np.zeros_like(timeline_times)
        laugh_10hz = np.interp(timeline_times, yamnet_times, laugh_scores_raw) if n_yamnet else np.zeros_like(timeline_times)
        impact_10hz = np.interp(timeline_times, yamnet_times, impact_scores_raw) if n_yamnet else np.zeros_like(timeline_times)

        return {
            "times": timeline_times.tolist(),
            "rms": rms_10hz.tolist(),
            "cat_vocal": cat_10hz.tolist(),
            "dog_vocal": dog_10hz.tolist(),
            "laughter": laugh_10hz.tolist(),
            "impact": impact_10hz.tolist()
        }

# -------------------------------------------------------------
# 3. Multi-Signal 10 Hz Video & Pet Tracker
# -------------------------------------------------------------
class VideoSignalTracker:
    def __init__(self):
        from pet_detector import PetDetector
        self.detector = PetDetector(model_path=YOLOX_MODEL_PATH)

    def analyze_source(self, video_path: str) -> dict:
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        dur = total_frames / fps
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        step_frames = max(1, int(round(fps / 10.0)))  # 10 Hz sampling
        
        times = []
        pet_present = []
        pet_boxes = []
        pet_speeds = []
        pet_accels = []
        pet_area_changes = []
        pet_motion_inside = []
        interaction_flags = []
        scene_cuts = []

        prev_hist = None
        prev_gray = None
        prev_box = None
        prev_dets = None
        prev_speed = 0.0
        frame_idx = 0

        while True:
            if frame_idx % step_frames != 0:
                if not cap.grab():
                    break
                frame_idx += 1
                continue

            ret, frame = cap.read()
            if not ret or frame is None:
                break

            t = round(frame_idx / fps, 2)
            times.append(t)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Scene cut check via HSV histogram
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
            cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
            is_cut = False
            if prev_hist is not None:
                diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
                if diff > 0.44:
                    scene_cuts.append(t)
                    is_cut = True
            prev_hist = hist

            # Object Detection (2.5 Hz cadence with immediate scene cut trigger)
            if (len(times) % 4 == 0) or is_cut or prev_dets is None:
                dets = self.detector.detect(frame, conf_threshold=0.22)
                prev_dets = dets
            else:
                dets = prev_dets

            cat_dets = [d for d in dets if d["class_name"] in ["cat", "dog"]] if dets else []
            other_dets = [d for d in dets if d["class_name"] not in ["cat", "dog"]] if dets else []

            motion_inside = 0.0
            speed = 0.0
            accel = 0.0
            area_change = 0.0
            has_interact = False

            if cat_dets:
                pet_present.append(1)
                best_pet = cat_dets[0]
                box = best_pet["box"]
                pet_boxes.append(box)

                bw = box[2] - box[0]
                bh = box[3] - box[1]
                area = (bw * bh) / float(w * h)
                cx = (box[0] + box[2]) / 2.0
                cy = (box[1] + box[3]) / 2.0

                if prev_box is not None:
                    pcx = (prev_box[0] + prev_box[2]) / 2.0
                    pcy = (prev_box[1] + prev_box[3]) / 2.0
                    pbw = prev_box[2] - prev_box[0]
                    pbh = prev_box[3] - prev_box[1]
                    parea = (pbw * pbh) / float(w * h)

                    dx = (cx - pcx) / float(w)
                    dy = (cy - pcy) / float(h)
                    speed = float(np.sqrt(dx**2 + dy**2) * 10.0)  # normalized per sec
                    accel = abs(speed - prev_speed) * 10.0
                    area_change = abs(area - parea) / max(0.01, parea)

                    # Optical flow inside pet crop only (scaled to 128x128 for high performance)
                    if prev_gray is not None:
                        x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
                        x2, y2 = min(w, int(box[2])), min(h, int(box[3]))
                        if x2 > x1 + 5 and y2 > y1 + 5:
                            p1 = gray[y1:y2, x1:x2]
                            p0 = prev_gray[y1:y2, x1:x2]
                            if p1.shape == p0.shape:
                                p0_s = cv2.resize(p0, (128, 128))
                                p1_s = cv2.resize(p1, (128, 128))
                                flow = cv2.calcOpticalFlowFarneback(p0_s, p1_s, None, 0.5, 2, 8, 2, 5, 1.1, 0)
                                motion_inside = float(np.mean(np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)))

                prev_box = box
                prev_speed = speed

                # Check proximity of other detected objects/people (interaction)
                for od in other_dets:
                    obox = od["box"]
                    ocx = (obox[0] + obox[2]) / 2.0
                    ocy = (obox[1] + obox[3]) / 2.0
                    dist_norm = np.sqrt(((cx - ocx)/w)**2 + ((cy - ocy)/h)**2)
                    if dist_norm < 0.25:
                        has_interact = True
                        break
            else:
                pet_present.append(0)
                pet_boxes.append(None)
                prev_box = None
                prev_speed = 0.0

            prev_gray = gray
            pet_speeds.append(speed)
            pet_accels.append(accel)
            pet_area_changes.append(area_change)
            pet_motion_inside.append(motion_inside)
            interaction_flags.append(1 if has_interact else 0)

            frame_idx += 1

        cap.release()

        avg_shot = dur / (len(scene_cuts) + 1) if scene_cuts else dur
        is_compilation = (avg_shot < 8.5) or (len(scene_cuts) >= 6)

        return {
            "duration": dur,
            "width": w,
            "height": h,
            "fps": fps,
            "scene_cuts": scene_cuts,
            "avg_shot": avg_shot,
            "is_compilation": is_compilation,
            "times": times,
            "pet_present": pet_present,
            "pet_boxes": pet_boxes,
            "pet_speeds": pet_speeds,
            "pet_accels": pet_accels,
            "pet_area_changes": pet_area_changes,
            "pet_motion_inside": pet_motion_inside,
            "interaction_flags": interaction_flags
        }

# -------------------------------------------------------------
# 4. Master Funny-Moment Event Detector
# -------------------------------------------------------------
class FunnyEventDetector:
    def __init__(self):
        self.yamnet = YAMNetTagger()
        self.tracker = VideoSignalTracker()

    def get_source_analysis(self, source_path: str) -> dict:
        """Retrieves 10 Hz multi-signal analysis from database or computes and caches it."""
        sha = compute_file_sha256(source_path)
        conn = get_db_conn()
        c = conn.cursor()
        c.execute("SELECT timeline_json, events_json, scene_cuts, is_compilation, duration FROM timeline_cache WHERE source_hash=? AND analyzer_version=?", (sha, ANALYZER_VERSION))
        row = c.fetchone()
        if row:
            timeline_data = json.loads(row[0])
            events = json.loads(row[1])
            cuts = json.loads(row[2])
            return {
                "source_hash": sha,
                "duration": row[4],
                "is_compilation": bool(row[3]),
                "scene_cuts": cuts,
                "timeline": timeline_data,
                "events": events
            }

        print(f"[FunnyDetector] Running 10 Hz analysis for source: {os.path.basename(source_path)}...")
        v_sig = self.tracker.analyze_source(source_path)
        a_sig = self.yamnet.classify_timeline(source_path, v_sig["duration"])

        # Align length
        n_len = min(len(v_sig["times"]), len(a_sig["times"]))
        t_axis = v_sig["times"][:n_len]

        # Multi-signal array
        mot_in = np.array(v_sig["pet_motion_inside"][:n_len], dtype=np.float32)
        speed = np.array(v_sig["pet_speeds"][:n_len], dtype=np.float32)
        accel = np.array(v_sig["pet_accels"][:n_len], dtype=np.float32)
        interact = np.array(v_sig["interaction_flags"][:n_len], dtype=np.float32)
        vocal = np.array(a_sig["cat_vocal"][:n_len], dtype=np.float32)
        dog_vocal = np.array(a_sig["dog_vocal"][:n_len], dtype=np.float32)
        laugh = np.array(a_sig["laughter"][:n_len], dtype=np.float32)
        impact = np.array(a_sig["impact"][:n_len], dtype=np.float32)
        rms = np.array(a_sig["rms"][:n_len], dtype=np.float32)

        # Normalize components
        n_mot = mot_in / (np.percentile(mot_in, 95) + 1e-4)
        n_speed = speed / (np.percentile(speed, 95) + 1e-4)
        n_accel = accel / (np.percentile(accel, 95) + 1e-4)

        # Composite Viral Action Score at each 10 Hz frame:
        # 30% optical motion in box + 25% pet speed/accel + 20% cat/dog vocal + 15% laughter/impact + 10% interaction
        action_score = (
            0.30 * np.clip(n_mot, 0, 1.5) +
            0.15 * np.clip(n_speed, 0, 1.5) +
            0.10 * np.clip(n_accel, 0, 1.5) +
            0.20 * np.clip(vocal + dog_vocal, 0, 1.0) +
            0.15 * np.clip(laugh + impact, 0, 1.0) +
            0.10 * interact
        )

        # Smooth with a 5-tap moving median
        smoothed_score = np.copy(action_score)
        for i in range(2, len(action_score) - 2):
            smoothed_score[i] = float(np.median(action_score[i-2:i+3]))

        # --- Extract Discrete Events (Onset, Peak, End) ---
        events = []
        threshold = 0.35
        in_event = False
        onset_idx = 0

        for i, val in enumerate(smoothed_score):
            if not in_event and val >= threshold:
                in_event = True
                onset_idx = i
            elif in_event and val < (threshold * 0.6):
                in_event = False
                end_idx = i
                # Discard ultra-short blips (<0.6s) or over-long continuous noise (>6s)
                dur_ev = (end_idx - onset_idx) * 0.1
                if 0.6 <= dur_ev <= 7.0:
                    peak_idx = onset_idx + int(np.argmax(smoothed_score[onset_idx:end_idx]))
                    peak_score = float(smoothed_score[peak_idx])
                    
                    # Classify event archetype
                    ev_type = "viral_action"
                    if vocal[peak_idx] > 0.4:
                        ev_type = "meow_vocal"
                    elif impact[peak_idx] > 0.4:
                        ev_type = "crash_impact"
                    elif laugh[peak_idx] > 0.4:
                        ev_type = "funny_laugh"
                    elif n_accel[peak_idx] > 0.8:
                        ev_type = "pounce_jump"
                    elif interact[peak_idx] > 0:
                        ev_type = "interaction"

                    events.append({
                        "event_id": f"ev_{len(events)+1}",
                        "onset_s": round(float(t_axis[onset_idx]), 2),
                        "peak_s": round(float(t_axis[peak_idx]), 2),
                        "end_s": round(float(t_axis[end_idx]), 2),
                        "duration_s": round(dur_ev, 2),
                        "event_type": ev_type,
                        "score": round(peak_score, 3)
                    })

        # Rank events by score descending
        events = sorted(events, key=lambda x: x["score"], reverse=True)

        # Prepare timeline payload
        timeline_payload = {
            "times": t_axis,
            "action_score": smoothed_score.tolist(),
            "motion_inside": mot_in.tolist(),
            "speed": speed.tolist(),
            "vocal": vocal.tolist(),
            "laughter": laugh.tolist(),
            "impact": impact.tolist(),
            "rms": rms.tolist(),
            "pet_boxes": v_sig["pet_boxes"][:n_len]
        }

        # Cache to database
        c.execute("""
            INSERT OR REPLACE INTO timeline_cache 
            (source_hash, analyzer_version, source_name, duration, is_compilation, scene_cuts, timeline_json, events_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sha, ANALYZER_VERSION, os.path.basename(source_path),
            v_sig["duration"], int(v_sig["is_compilation"]),
            json.dumps(v_sig["scene_cuts"]), json.dumps(timeline_payload),
            json.dumps(events)
        ))
        conn.commit()
        conn.close()

        return {
            "source_hash": sha,
            "duration": v_sig["duration"],
            "is_compilation": v_sig["is_compilation"],
            "scene_cuts": v_sig["scene_cuts"],
            "timeline": timeline_payload,
            "events": events
        }

    def detect_events_from_timeline(self, times_s, audio_energy, audio_events, pet_speed, pet_flow, pet_accel, interaction_probs) -> list:
        """
        Extracts discrete FunnyEvents from timeline arrays (used for synthetic tests and custom timelines).
        """
        times = np.array(times_s, dtype=np.float32)
        n = len(times)
        if n == 0:
            return []
        flow = np.array(pet_flow, dtype=np.float32) if pet_flow is not None else np.zeros(n)
        speed = np.array(pet_speed, dtype=np.float32) if pet_speed is not None else np.zeros(n)
        accel = np.array(pet_accel, dtype=np.float32) if pet_accel is not None else np.zeros(n)
        audio = np.array(audio_energy, dtype=np.float32) if audio_energy is not None else np.zeros(n)
        interact = np.array(interaction_probs, dtype=np.float32) if interaction_probs is not None else np.zeros(n)

        def norm_signal(s):
            mx = np.max(s)
            return s / mx if mx > 1e-4 else s

        n_flow = norm_signal(flow)
        n_speed = norm_signal(speed)
        n_accel = norm_signal(accel)
        n_audio = norm_signal(audio)

        action = (
            0.35 * n_flow +
            0.25 * n_speed +
            0.15 * n_accel +
            0.15 * n_audio +
            0.10 * interact
        )

        smoothed = np.copy(action)
        for i in range(2, n - 2):
            smoothed[i] = float(np.median(action[max(0, i-2):min(n, i+3)]))

        events = []
        threshold = 0.35
        in_event = False
        onset_idx = 0
        step_dt = float(times[1] - times[0]) if len(times) > 1 else 0.1

        for i, val in enumerate(smoothed):
            if not in_event and val >= threshold:
                in_event = True
                onset_idx = i
            elif in_event and val < (threshold * 0.6):
                in_event = False
                end_idx = i
                dur_ev = (end_idx - onset_idx) * step_dt
                if dur_ev >= 0.4:
                    peak_idx = onset_idx + int(np.argmax(smoothed[onset_idx:end_idx]))
                    peak_score = float(smoothed[peak_idx])
                    trig_type = "motion" if n_audio[peak_idx] < 0.2 else "multimodal"
                    if n_accel[peak_idx] > 0.6:
                        trig_type = "motion_jump"

                    events.append(FunnyEvent(
                        onset_s=round(float(times[onset_idx]), 2),
                        peak_s=round(float(times[peak_idx]), 2),
                        end_s=round(float(times[end_idx]), 2),
                        score=round(peak_score, 3),
                        trigger_type=trig_type,
                        event_id=f"ev_{len(events)+1}",
                        details={"max_speed": float(n_speed[peak_idx]), "flow": float(n_flow[peak_idx])}
                    ))

        if in_event:
            end_idx = n - 1
            peak_idx = onset_idx + int(np.argmax(smoothed[onset_idx:end_idx]))
            events.append(FunnyEvent(
                onset_s=round(float(times[onset_idx]), 2),
                peak_s=round(float(times[peak_idx]), 2),
                end_s=round(float(times[end_idx]), 2),
                score=round(float(smoothed[peak_idx]), 3),
                trigger_type="motion",
                event_id=f"ev_{len(events)+1}",
                details={}
            ))

        return sorted(events, key=lambda x: x.score, reverse=True)

    # ---------------------------------------------------------
    # 5. Shot-Aware Cut Placement & Boundary Refinement (Phase 3)
    # ---------------------------------------------------------
    def place_shot_aware_window(self, source_path: str, event: dict, target_dur_s: float = 10.0) -> dict:
        """
        Dynamically places an optimal clip window around an event enforcing:
        1. Shot containment (zero scene cut crossing inside window).
        2. Peak placement at 35-50% with lead-in setup (2.0-3.5s) and reaction aftermath.
        3. Frame-accurate boundary refinement snapping to low-motion and silence gaps.
        4. FUNNY_PART_PRESENT gate.
        """
        analysis = self.get_source_analysis(source_path)
        src_dur = analysis["duration"]
        cuts = analysis["scene_cuts"]

        onset_s = event["onset_s"]
        peak_s = event["peak_s"]
        end_s = event["end_s"]

        # Find the single shot containing this peak
        all_cut_points = [0.0] + sorted(cuts) + [src_dur]
        shot_start = 0.0
        shot_end = src_dur

        for i in range(len(all_cut_points) - 1):
            if all_cut_points[i] <= peak_s <= all_cut_points[i + 1]:
                shot_start = all_cut_points[i]
                shot_end = all_cut_points[i + 1]
                break

        shot_len = shot_end - shot_start
        clip_dur = min(target_dur_s, shot_len - 0.2)  # adapt if shot is shorter than target

        # Ideal peak placement: 40% into clip
        ideal_start = peak_s - (clip_dur * 0.40)
        ideal_end = ideal_start + clip_dur

        # Clamp strictly inside shot boundaries
        if ideal_start < shot_start + 0.1:
            ideal_start = shot_start + 0.1
            ideal_end = ideal_start + clip_dur

        if ideal_end > shot_end - 0.1:
            ideal_end = shot_end - 0.1
            ideal_start = max(shot_start + 0.1, ideal_end - clip_dur)

        # Frame-accurate boundary refinement (+/- 1.0s search)
        times = np.array(analysis["timeline"]["times"])
        rms = np.array(analysis["timeline"]["rms"])
        motion = np.array(analysis["timeline"]["motion_inside"])

        # Refine in-point: search in [ideal_start - 0.8s, ideal_start + 0.8s]
        in_min = max(shot_start + 0.05, ideal_start - 0.8)
        in_max = min(onset_s - 0.5, ideal_start + 0.8)
        if in_max > in_min:
            mask_in = (times >= in_min) & (times <= in_max)
            if np.any(mask_in):
                scores_in = motion[mask_in] + rms[mask_in]
                best_in_idx = np.argmin(scores_in)
                refined_start = float(times[mask_in][best_in_idx])
            else:
                refined_start = ideal_start
        else:
            refined_start = ideal_start

        # Refine out-point: search in [ideal_end - 0.8s, ideal_end + 0.8s]
        out_min = max(end_s + 0.5, ideal_end - 0.8)
        out_max = min(shot_end - 0.05, ideal_end + 0.8)
        if out_max > out_min:
            mask_out = (times >= out_min) & (times <= out_max)
            if np.any(mask_out):
                scores_out = motion[mask_out] + rms[mask_out]
                best_out_idx = np.argmin(scores_out)
                refined_end = float(times[mask_out][best_out_idx])
            else:
                refined_end = ideal_end
        else:
            refined_end = ideal_end

        final_dur = refined_end - refined_start

        # Validate Gate: FUNNY_PART_PRESENT
        passes_lead_in = (peak_s - refined_start) >= 1.2
        passes_aftermath = (refined_end - peak_s) >= 1.0
        no_cuts_inside = not any(refined_start < c < refined_end for c in cuts)
        score_ok = event["score"] >= 0.30

        gate_passed = passes_lead_in and passes_aftermath and no_cuts_inside and score_ok
        failure_reasons = []
        if not passes_lead_in:
            failure_reasons.append("LEAD_IN_TOO_SHORT")
        if not passes_aftermath:
            failure_reasons.append("AFTERMATH_TOO_SHORT")
        if not no_cuts_inside:
            failure_reasons.append("CROSSES_SHOT_CUT")
        if not score_ok:
            failure_reasons.append("FUNNY_PART_MISSING")

        return {
            "source": os.path.basename(source_path),
            "event_id": event.get("event_id", "ev_1"),
            "event_type": event.get("event_type", "viral_action"),
            "event_score": event.get("score", 0.8),
            "start_s": round(refined_start, 2),
            "end_s": round(refined_end, 2),
            "duration": round(final_dur, 2),
            "peak_s": round(peak_s, 2),
            "peak_percent": round(((peak_s - refined_start) / max(0.1, final_dur)) * 100.0, 1),
            "shot_start": round(shot_start, 2),
            "shot_end": round(shot_end, 2),
            "shot_len": round(shot_len, 2),
            "funny_part_present": gate_passed,
            "gate_reasons": failure_reasons
        }

    def get_candidate_windows_for_source(self, source_path: str, max_candidates: int = 5, target_dur: float = 10.0) -> list:
        """Extracts top non-overlapping viral windows for a source file."""
        analysis = self.get_source_analysis(source_path)
        events = analysis.get("events", [])
        candidates = []

        for ev in events:
            win = self.place_shot_aware_window(source_path, ev, target_dur_s=target_dur)
            if not win["funny_part_present"]:
                continue

            # Non-maximum suppression: keep windows separated by at least 8.0s
            overlap = False
            for c in candidates:
                if abs(win["peak_s"] - c["peak_s"]) < 8.0:
                    overlap = True
                    break
            if not overlap:
                candidates.append(win)
                if len(candidates) >= max_candidates:
                    break

        return candidates

if __name__ == "__main__":
    detector = FunnyEventDetector()
    test_src = os.path.join(PROJECT_ROOT, "raw", "cache_ByH9LuSILxU.mp4")
    if os.path.exists(test_src):
        print(f"Testing FunnyEventDetector on {test_src}...")
        res = detector.get_source_analysis(test_src)
        print(f"Events extracted: {len(res['events'])}")
        for ev in res['events'][:5]:
            print(f"  Event: {ev}")
        wins = detector.get_candidate_windows_for_source(test_src, max_candidates=3)
        print(f"\nTop 3 Candidate Windows:")
        for w in wins:
            print(f"  Window: {w['start_s']}s - {w['end_s']}s (Peak: {w['peak_s']}s / {w['peak_percent']}%, Shot: {w['shot_start']}s-{w['shot_end']}s)")
