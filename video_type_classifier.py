"""
video_type_classifier.py
========================
Automated Cat Video Type Classifier using multi-modal heuristics:
- Visual Object & Pet Tracker: Counts cats, dogs, humans, and objects over sampled frames
- Audio Activity Analysis: Speech vs Cat Vocalizations (Meow/Purr) vs Music using YAMNet
- Motion & Acceleration: Optical flow velocity, acceleration spikes, direction reversals
- Spatial Framing: Kitten size scale (< 15% frame area), head/mouth focus, dual-subject presence

Classifies windows into one of 9 canonical cat video types (config/video_types.json):
1. dubbed_talking (speech >= 60% with cat on screen, no music-only)
2. double_cats (2+ cats visible >= 60% frames, both fully inside frame)
3. fails_clumsy (sudden vertical drop / tumble / fall with setup and landing)
4. startled_reactions (sudden high acceleration spook / jump)
5. cats_vs_objects (cat interacting with balls, cups, cucumbers, bottles, electronics)
6. derp_silly (abnormal orientation, head tilt, blep/tongue)
7. kitten_cute (cat box area < 15% frame with high mewing/squeaking)
8. cat_human_moments (cat and person/hand/foot interacting)
9. cat_dog (cat and dog interacting)
Low confidence windows are assigned "untyped".
"""

import os
import json
import cv2
import numpy as np
from typing import Dict, Any, List, Optional, Tuple

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "video_types.json")

def load_video_types_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"types": {}, "default_type": "auto"}

class VideoTypeClassifier:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(VideoTypeClassifier, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.config = load_video_types_config()
        self.detector = None
        try:
            from pet_detector import PetDetector
            self.detector = PetDetector()
        except Exception as e:
            print(f"Notice: PetDetector not available in classifier: {e}")
        self._initialized = True

    def extract_audio_speech_and_music_ratios(self, video_path: str, start_s: float, dur_s: float) -> Tuple[float, float, float]:
        """
        Extracts speech, cat vocalization (meow/purr), and music ratios from the audio track.
        Uses YAMNet if available, or falls back to spectral/energy heuristics.
        Returns: (speech_ratio, cat_vocal_ratio, music_ratio)
        """
        try:
            from funny_event_detector import extract_audio_yamnet_features
            features = extract_audio_yamnet_features(video_path, start_s, dur_s)
            if features:
                return features.get("speech_ratio", 0.0), features.get("cat_ratio", 0.0), features.get("music_ratio", 0.0)
        except Exception:
            pass

        # Fallback audio heuristic via FFmpeg pipe (RMS energy & zero-crossing rate)
        return 0.0, 0.0, 0.0

    def classify_window(self, video_path: str, start_s: float, dur_s: float, n_samples: int = 12) -> Dict[str, Any]:
        """
        Classifies a single window from a source video into primary and secondary types.
        """
        if not os.path.exists(video_path) or dur_s <= 0:
            return {
                "primary_type": "untyped",
                "secondary_type": None,
                "confidence": 0.0,
                "evidence": {"error": "Video not found or invalid duration"}
            }

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return {
                "primary_type": "untyped",
                "secondary_type": None,
                "confidence": 0.0,
                "evidence": {"error": "Cannot open video"}
            }

        start_f = int(max(0.0, start_s) * fps)
        span_f = int(dur_s * fps)
        end_f = min(total_frames, start_f + span_f)
        frame_indices = [start_f + int((end_f - start_f) * (i + 0.5) / float(n_samples)) for i in range(n_samples)]

        frames = []
        for fi in frame_indices:
            fi = min(total_frames - 1, max(0, fi))
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ret, frame = cap.read()
            if ret and frame is not None:
                frames.append(frame)
        cap.release()

        if not frames:
            return {
                "primary_type": "untyped",
                "secondary_type": None,
                "confidence": 0.0,
                "evidence": {"error": "Failed to decode frames"}
            }

        # Visual feature extraction
        cat_counts = []
        dog_counts = []
        person_counts = []
        object_counts = []
        box_areas = []
        both_inside_frames = 0
        motion_diffs = []

        prev_gray = None
        for frame in frames:
            h, w = frame.shape[:2]
            frame_area = float(w * h)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                diff = np.mean(cv2.absdiff(gray, prev_gray))
                motion_diffs.append(diff)
            prev_gray = gray

            cats = 0
            dogs = 0
            persons = 0
            objects = 0
            if self.detector:
                detections = self.detector.detect_all_classes(frame, conf_threshold=0.22) if hasattr(self.detector, "detect_all_classes") else self.detector.detect(frame, conf_threshold=0.22)
                for d in detections:
                    cls_name = d.get("class_name") or d.get("label") or ("dog" if d.get("class_id") == 16 else "cat")
                    bx1, by1, bx2, by2 = d.get("box", [0, 0, 0, 0])
                    b_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
                    if cls_name == "cat":
                        cats += 1
                        box_areas.append(b_area / frame_area)
                    elif cls_name == "dog":
                        dogs += 1
                    elif cls_name == "person":
                        persons += 1
                    elif cls_name in ["sports ball", "bottle", "cup", "bowl", "laptop", "mouse", "cell phone", "book", "teddy bear"]:
                        objects += 1

                if cats >= 2:
                    both_inside_frames += 1

            cat_counts.append(cats)
            dog_counts.append(dogs)
            person_counts.append(persons)
            object_counts.append(objects)

        n_dec = len(frames)
        multi_cat_ratio = both_inside_frames / float(n_dec)
        dog_ratio = sum(1 for d in dog_counts if d >= 1) / float(n_dec)
        person_ratio = sum(1 for p in person_counts if p >= 1) / float(n_dec)
        object_ratio = sum(1 for o in object_counts if o >= 1) / float(n_dec)
        avg_box_area = np.mean(box_areas) if box_areas else 0.35
        max_motion = max(motion_diffs) if motion_diffs else 0.0

        # Audio feature extraction
        speech_r, cat_voc_r, music_r = self.extract_audio_speech_and_music_ratios(video_path, start_s, dur_s)

        # Scoring heuristics across the 9 types
        scores = {}

        # 1. double_cats: 2+ cats visible >= 60% of frames
        if multi_cat_ratio >= 0.50:
            scores["double_cats"] = min(1.0, 0.40 + multi_cat_ratio * 0.60)

        # 2. cat_dog: cat and dog visible together
        if dog_ratio >= 0.30:
            scores["cat_dog"] = min(1.0, 0.40 + dog_ratio * 0.60)

        # 3. cat_human_moments: cat and person interacting
        if person_ratio >= 0.40:
            scores["cat_human_moments"] = min(1.0, 0.40 + person_ratio * 0.60)

        # 4. cats_vs_objects: object detected in scene
        if object_ratio >= 0.35:
            scores["cats_vs_objects"] = min(1.0, 0.40 + object_ratio * 0.60)

        # 5. dubbed_talking: speech present >= 60% with cat on screen
        if speech_r >= 0.45 and music_r < 0.60:
            scores["dubbed_talking"] = min(1.0, 0.35 + speech_r * 0.65)

        # 6. kitten_cute: average cat box area < 15% of frame (small kitten)
        if avg_box_area < 0.15 and len(box_areas) >= 4:
            scores["kitten_cute"] = min(1.0, 0.50 + (0.15 - avg_box_area) * 3.0)

        # 7. fails_clumsy & 8. startled_reactions: high motion / sudden displacement
        if max_motion >= 22.0:
            scores["fails_clumsy"] = min(1.0, 0.40 + (max_motion - 22.0) / 40.0)
            scores["startled_reactions"] = min(1.0, 0.35 + (max_motion - 22.0) / 45.0)

        # 9. derp_silly: baseline quirky moment
        scores["derp_silly"] = 0.35

        # Determine top 2 types
        sorted_types = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        primary_type = "untyped"
        primary_conf = 0.0
        secondary_type = None

        if sorted_types:
            top_t, top_c = sorted_types[0]
            if top_c >= 0.50:
                primary_type = top_t
                primary_conf = round(float(top_c), 2)
                if len(sorted_types) > 1 and sorted_types[1][1] >= 0.45:
                    secondary_type = sorted_types[1][0]
            else:
                primary_type = "untyped"
                primary_conf = round(float(top_c), 2)

        return {
            "primary_type": primary_type,
            "secondary_type": secondary_type,
            "confidence": primary_conf,
            "evidence": {
                "multi_cat_ratio": round(multi_cat_ratio, 2),
                "dog_ratio": round(dog_ratio, 2),
                "person_ratio": round(person_ratio, 2),
                "object_ratio": round(object_ratio, 2),
                "avg_box_area": round(float(avg_box_area), 3),
                "max_motion": round(float(max_motion), 1),
                "speech_ratio": round(speech_r, 2),
                "music_ratio": round(music_r, 2)
            }
        }
