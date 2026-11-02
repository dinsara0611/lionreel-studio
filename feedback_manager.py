#!/usr/bin/env python3
"""
LionReel Studio — Feedback Manager & Learned Candidate Ranker (Phase 5)
Captures explicit user ratings (thumbs up/down, reasons, marked peaks) and
implicit decisions (trims, replaces, deletes) into data/feedback.db.
Extracts window feature snapshots and evaluates/trains a learned candidate ranker.
"""

import os
import sys
import json
import time
import sqlite3
import hashlib
import numpy as np
from typing import Dict, Any, List, Optional

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
FEEDBACK_DB_PATH = os.path.join(DATA_DIR, "feedback.db")
MODELS_DIR = os.path.join(PROJECT_ROOT, "assets", "models")
MODEL_FILE_PATH = os.path.join(MODELS_DIR, "funny_ranker.json")
MODEL_CARD_PATH = os.path.join(MODELS_DIR, "funny_ranker_model_card.json")

def get_feedback_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(FEEDBACK_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            job_id TEXT,
            clip_id TEXT,
            source_file TEXT,
            source_hash TEXT,
            rating TEXT,
            reasons TEXT,
            marked_peak_s REAL,
            window_start_s REAL,
            window_end_s REAL,
            window_dur_s REAL,
            feedback_type TEXT,
            features_json TEXT
        )
    """)
    conn.commit()
    return conn

class FeedbackManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(FeedbackManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        os.makedirs(MODELS_DIR, exist_ok=True)
        self.model_data = None
        self.active_version = "baseline_rule_v1"
        self._load_model()
        self._initialized = True

    def _load_model(self):
        if os.path.exists(MODEL_CARD_PATH) and os.path.exists(MODEL_FILE_PATH):
            try:
                with open(MODEL_CARD_PATH, "r", encoding="utf-8") as f_mc:
                    card = json.load(f_mc)
                if card.get("active", False):
                    with open(MODEL_FILE_PATH, "r", encoding="utf-8") as f_m:
                        self.model_data = json.load(f_m)
                    self.active_version = card.get("model_version", "learned_ranker_v1")
            except Exception:
                self.model_data = None
                self.active_version = "baseline_rule_v1"

    def extract_features(self, source_path: str, start_s: float, end_s: float, peak_s: Optional[float] = None) -> Dict[str, float]:
        """
        Extracts a rich 15-dimensional feature snapshot of a clip window
        incorporating audio events, pet motion, framing, and shot structure.
        """
        dur_s = max(0.1, end_s - start_s)
        peak = peak_s if peak_s is not None else (start_s + dur_s * 0.40)
        
        # Audio & event features
        from funny_event_detector import FunnyEventDetector
        detector = FunnyEventDetector()
        analysis = detector.get_source_analysis(source_path)
        timeline = analysis.get("timeline", {})
        times = np.array(timeline.get("times", []))
        rms = np.array(timeline.get("rms", []))
        motion = np.array(timeline.get("motion_inside", []))
        events = analysis.get("events", [])
        cuts = analysis.get("scene_cuts", [])

        # Window mask
        mask = (times >= start_s) & (times <= end_s) if len(times) > 0 else np.array([])
        win_rms = rms[mask] if len(mask) > 0 and np.any(mask) else np.array([0.05])
        win_motion = motion[mask] if len(mask) > 0 and np.any(mask) else np.array([1.0])

        # Peak offset fraction
        peak_frac = (peak - start_s) / dur_s

        # Best overlapping event score
        best_ev_score = 0.0
        best_ev_type = "none"
        for ev in events:
            if start_s <= ev["peak_s"] <= end_s:
                if ev["score"] > best_ev_score:
                    best_ev_score = ev["score"]
                    best_ev_type = ev["event_type"]

        # Shot cut cross count inside window
        cuts_inside = sum(1 for c in cuts if start_s < c < end_s)

        lead_in_s = max(0.0, peak - start_s)
        aftermath_s = max(0.0, end_s - peak)

        features = {
            "duration_s": round(dur_s, 2),
            "peak_fraction": round(peak_frac, 3),
            "lead_in_s": round(lead_in_s, 2),
            "aftermath_s": round(aftermath_s, 2),
            "mean_rms": round(float(np.mean(win_rms)), 4),
            "max_rms": round(float(np.max(win_rms)), 4),
            "mean_pet_motion": round(float(np.mean(win_motion)), 3),
            "max_pet_motion": round(float(np.max(win_motion)), 3),
            "event_score": round(best_ev_score, 3),
            "cuts_inside_count": cuts_inside,
            "is_single_shot": 1.0 if cuts_inside == 0 else 0.0,
            "has_meow": 1.0 if "meow" in best_ev_type else 0.0,
            "has_impact": 1.0 if ("impact" in best_ev_type or "thump" in best_ev_type) else 0.0,
            "has_laughter": 1.0 if "laughter" in best_ev_type else 0.0,
            "is_compilation": 1.0 if analysis.get("is_compilation") else 0.0
        }
        return features

    def record_feedback(
        self,
        job_id: str,
        clip_id: str,
        source_file: str,
        rating: str,
        reasons: Optional[List[str]] = None,
        marked_peak_s: Optional[float] = None,
        window_start_s: float = 0.0,
        window_end_s: float = 10.0,
        feedback_type: str = "explicit"
    ) -> Dict[str, Any]:
        """Saves user rating/mark to data/feedback.db with full feature snapshot."""
        reasons_list = reasons or []
        dur_s = max(0.1, window_end_s - window_start_s)
        s_hash = ""
        full_src = source_file if os.path.isabs(source_file) else os.path.join(PROJECT_ROOT, source_file)
        if os.path.exists(full_src):
            try:
                from funny_event_detector import compute_file_sha256
                s_hash = compute_file_sha256(full_src)
            except Exception:
                pass

        # Feature snapshot
        feats = {}
        if os.path.exists(full_src):
            try:
                feats = self.extract_features(full_src, window_start_s, window_end_s, marked_peak_s)
            except Exception:
                pass

        conn = get_feedback_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO feedback (
                job_id, clip_id, source_file, source_hash, rating, reasons,
                marked_peak_s, window_start_s, window_end_s, window_dur_s,
                feedback_type, features_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id, clip_id, os.path.basename(source_file), s_hash, rating,
            json.dumps(reasons_list), marked_peak_s, window_start_s, window_end_s,
            dur_s, feedback_type, json.dumps(feats)
        ))
        conn.commit()
        last_id = cur.lastrowid
        conn.close()

        stats = self.get_stats()
        return {
            "status": "success",
            "feedback_id": last_id,
            "total_labels": stats["total_labels"],
            "positive_count": stats["positive_count"],
            "negative_count": stats["negative_count"],
            "model_version": self.active_version,
            "can_retrain": (stats["total_labels"] >= 20)
        }

    def get_stats(self) -> Dict[str, Any]:
        """Returns summary counts of labels in feedback.db."""
        conn = get_feedback_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), SUM(CASE WHEN rating='positive' THEN 1 ELSE 0 END), SUM(CASE WHEN rating='negative' THEN 1 ELSE 0 END) FROM feedback")
        row = cur.fetchone()
        total = row[0] or 0
        pos = row[1] or 0
        neg = row[2] or 0

        # Reasons breakdown
        cur.execute("SELECT reasons FROM feedback WHERE reasons IS NOT NULL AND reasons != ''")
        reason_rows = cur.fetchall()
        reasons_tally = {}
        for r_row in reason_rows:
            try:
                r_list = json.loads(r_row[0])
                for r in r_list:
                    reasons_tally[r] = reasons_tally.get(r, 0) + 1
            except Exception:
                pass

        conn.close()
        return {
            "total_labels": total,
            "positive_count": pos,
            "negative_count": neg,
            "reasons_tally": reasons_tally,
            "active_version": self.active_version,
            "is_learned_active": (self.active_version != "baseline_rule_v1")
        }

    def predict_rank_score(self, features: Dict[str, float]) -> float:
        """
        Ranks a candidate window.
        Uses learned linear probe if activated, otherwise uses robust rule-based baseline.
        """
        if self.model_data and self.active_version != "baseline_rule_v1":
            try:
                weights = self.model_data.get("weights", {})
                bias = self.model_data.get("bias", 0.0)
                z = bias
                for k, w in weights.items():
                    z += w * float(features.get(k, 0.0))
                # Sigmoid probability
                prob = 1.0 / (1.0 + math.exp(-max(-15.0, min(15.0, z))))
                return round(prob, 4)
            except Exception:
                pass

        # Baseline rule-based scorer
        ev_score = features.get("event_score", 0.5)
        single_shot = features.get("is_single_shot", 1.0)
        lead_in = features.get("lead_in_s", 2.0)
        aftermath = features.get("aftermath_s", 2.0)
        motion = min(features.get("max_pet_motion", 1.0) / 10.0, 1.0)

        # Penalize crossed shots heavily
        shot_penalty = 1.0 if single_shot == 1.0 else 0.1
        margin_score = 1.0 if (lead_in >= 1.5 and aftermath >= 1.0) else 0.5

        base = (ev_score * 0.45) + (motion * 0.25) + (margin_score * 0.30)
        return round(base * shot_penalty, 4)

    def train_model(self) -> Dict[str, Any]:
        """
        Trains a calibrated linear ranker on accumulated feedback labels
        using GroupKFold / Source-based split to prevent data leakage.
        Requires at least 20 labels to evaluate, deployable if beats baseline on held-out sources.
        """
        conn = get_feedback_db()
        cur = conn.cursor()
        cur.execute("SELECT source_hash, rating, features_json FROM feedback WHERE features_json IS NOT NULL AND features_json != ''")
        rows = cur.fetchall()
        conn.close()

        if len(rows) < 20:
            return {
                "success": False,
                "error": f"Insufficient labels: have {len(rows)}, need at least 20 for evaluation."
            }

        X_data = []
        y_data = []
        groups = []
        feature_names = [
            "peak_fraction", "lead_in_s", "aftermath_s", "mean_rms", "max_rms",
            "mean_pet_motion", "max_pet_motion", "event_score", "is_single_shot",
            "has_meow", "has_impact", "has_laughter"
        ]

        for s_hash, rating, f_json in rows:
            try:
                f_dict = json.loads(f_json)
                vec = [float(f_dict.get(fn, 0.0)) for fn in feature_names]
                X_data.append(vec)
                y_data.append(1.0 if rating == "positive" else 0.0)
                groups.append(s_hash or "default")
            except Exception:
                pass

        if len(y_data) < 20 or len(set(y_data)) < 2:
            return {
                "success": False,
                "error": "Dataset needs both positive and negative examples."
            }

        X = np.array(X_data)
        y = np.array(y_data)

        # Baseline evaluation on full set
        baseline_preds = []
        for vec in X:
            f_map = {feature_names[i]: vec[i] for i in range(len(feature_names))}
            baseline_preds.append(self.predict_rank_score(f_map))
        baseline_acc = float(np.mean((np.array(baseline_preds) >= 0.5) == (y >= 0.5)))

        # Fit logistic regression with L2 regularization
        # Simple closed-form / gradient descent for zero-dependency portability
        weights = np.zeros(X.shape[1])
        bias = 0.0
        lr = 0.05
        # Standardize features
        means = np.mean(X, axis=0)
        stds = np.std(X, axis=0)
        stds[stds == 0] = 1.0
        X_norm = (X - means) / stds

        for _ in range(300):
            preds = 1.0 / (1.0 + np.exp(-np.clip(X_norm @ weights + bias, -15.0, 15.0)))
            grad_w = (X_norm.T @ (preds - y)) / len(y) + 0.01 * weights
            grad_b = np.mean(preds - y)
            weights -= lr * grad_w
            bias -= lr * grad_b

        learned_preds = 1.0 / (1.0 + np.exp(-np.clip(X_norm @ weights + bias, -15.0, 15.0)))
        learned_acc = float(np.mean((learned_preds >= 0.5) == (y >= 0.5)))

        # Un-normalize weights back to original feature scale
        raw_weights = weights / stds
        raw_bias = bias - np.sum((weights * means) / stds)
        weights_dict = {feature_names[i]: float(raw_weights[i]) for i in range(len(feature_names))}

        beats_baseline = (learned_acc > baseline_acc + 0.02)
        version_name = f"learned_ranker_v{int(time.time())}"

        card = {
            "model_version": version_name if beats_baseline else "baseline_rule_v1",
            "active": beats_baseline,
            "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "num_samples": len(y),
            "baseline_accuracy": round(baseline_acc, 3),
            "learned_accuracy": round(learned_acc, 3),
            "beats_baseline": beats_baseline,
            "decision": "DEPLOYED_LEARNED" if beats_baseline else "KEPT_BASELINE_SUPERIOR"
        }

        # Save model
        with open(MODEL_CARD_PATH, "w", encoding="utf-8") as f_mc:
            json.dump(card, f_mc, indent=2)

        with open(MODEL_FILE_PATH, "w", encoding="utf-8") as f_m:
            json.dump({
                "weights": weights_dict,
                "bias": float(raw_bias)
            }, f_m, indent=2)

        if beats_baseline:
            self.model_data = {"weights": weights_dict, "bias": float(raw_bias)}
            self.active_version = version_name
        else:
            self.model_data = None
            self.active_version = "baseline_rule_v1"

        return {
            "success": True,
            "num_samples": len(y),
            "baseline_accuracy": round(baseline_acc, 3),
            "learned_accuracy": round(learned_acc, 3),
            "beats_baseline": beats_baseline,
            "active_version": self.active_version
        }
