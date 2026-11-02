"""
Pet Detector Module using YOLOX ONNX for LionReel
Detects cats (class 15) and dogs (class 16) with robust bounding box regression.
"""

import os
import cv2
import numpy as np

YOLOX_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "models", "object_detection_yolox_2022nov.onnx")

COCO_CLASSES = {
    0: "person",
    15: "cat",
    16: "dog",
    32: "sports ball",
    39: "bottle",
    41: "cup",
    45: "bowl",
    63: "laptop",
    64: "mouse",
    67: "cell phone",
    73: "book",
    77: "teddy bear"
}
INTERACTION_CLASSES = {"person", "sports ball", "bottle", "cup", "bowl", "laptop", "mouse", "cell phone", "book", "teddy bear"}

import threading
_DETECTOR_LOCK = threading.Lock()

class PetDetector:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(PetDetector, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, model_path=YOLOX_MODEL_PATH):
        if self._initialized:
            return
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"YOLOX model not found at: {model_path}")
        
        # Cache to local SSD to prevent Google Drive virtual disk locks/latency
        load_path = model_path
        try:
            local_dir = r"C:\LionReel\models"
            os.makedirs(local_dir, exist_ok=True)
            local_cached = os.path.join(local_dir, os.path.basename(model_path))
            if not os.path.exists(local_cached) or os.path.getsize(local_cached) != os.path.getsize(model_path):
                import shutil
                shutil.copyfile(model_path, local_cached)
            if os.path.exists(local_cached):
                load_path = local_cached
        except Exception:
            pass

        self.model_path = load_path
        net = None
        for attempt in range(5):
            try:
                net = cv2.dnn.readNetFromONNX(load_path)
                if net is not None:
                    break
            except Exception as e_load:
                if attempt == 4:
                    if load_path != model_path:
                        try:
                            net = cv2.dnn.readNetFromONNX(model_path)
                            if net is not None:
                                break
                        except Exception:
                            pass
                    raise
                import time
                time.sleep(0.3 * (attempt + 1))
        self.net = net
        self.input_size = (416, 416)
        self._generate_grids()
        self._initialized = True

    def _generate_grids(self):
        """Precomputes decoding grids for 416x416 input across strides 8, 16, 32."""
        strides = [8, 16, 32]
        grids = []
        expanded_strides = []
        for s in strides:
            h_size = self.input_size[1] // s
            w_size = self.input_size[0] // s
            y_v, x_v = np.meshgrid(np.arange(h_size), np.arange(w_size), indexing='ij')
            grid = np.stack((x_v, y_v), 2).reshape((-1, 2)).astype(np.float32)
            grids.append(grid)
            shape = grid.shape[:1]
            expanded_strides.append(np.full((*shape, 1), s, dtype=np.float32))
        self.grids = np.concatenate(grids, axis=0)
        self.expanded_strides = np.concatenate(expanded_strides, axis=0)

    def _preprocess(self, frame):
        """Resize frame to 416x416 with letterbox padding."""
        h, w = frame.shape[:2]
        scale = min(self.input_size[0] / w, self.input_size[1] / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        padded = np.full((self.input_size[1], self.input_size[0], 3), 114, dtype=np.uint8)
        padded[:new_h, :new_w] = resized
        return padded, scale

    def detect(self, frame, conf_threshold=0.30, nms_threshold=0.45, include_objects=False):
        """
        Detects pets (cats, dogs) and optionally interacting objects/people in the given BGR frame.
        Returns list of dicts:
        [{'class_id': int, 'class_name': str, 'conf': float, 'box': [x1, y1, x2, y2], 'center': (cx, cy), 'area_frac': float}]
        """
        if frame is None or frame.size == 0:
            return []
        
        orig_h, orig_w = frame.shape[:2]
        padded, scale = self._preprocess(frame)
        
        blob = cv2.dnn.blobFromImage(padded, scalefactor=1.0, size=self.input_size, mean=(0, 0, 0), swapRB=False, crop=False)
        with _DETECTOR_LOCK:
            self.net.setInput(blob)
            output = self.net.forward()  # shape (1, 3549, 85)
        preds = output[0]

        # Decode output
        box_xy = (preds[:, :2] + self.grids) * self.expanded_strides
        box_wh = np.exp(preds[:, 2:4]) * self.expanded_strides
        obj_conf = preds[:, 4:5]
        class_scores = preds[:, 5:] * obj_conf

        target_cids = [15, 16]
        if include_objects:
            target_cids = list(COCO_CLASSES.keys())

        mask = np.zeros(preds.shape[0], dtype=bool)
        for cid in target_cids:
            if cid < class_scores.shape[1]:
                mask |= (class_scores[:, cid] > conf_threshold)

        if not np.any(mask):
            return []

        cand_xy = box_xy[mask]
        cand_wh = box_wh[mask]
        cand_scores = class_scores[mask]

        boxes = []
        confidences = []
        class_ids = []

        for i in range(len(cand_xy)):
            best_cid = None
            best_score = -1.0
            for cid in target_cids:
                if cid < cand_scores.shape[1]:
                    sc = cand_scores[i, cid]
                    if sc > best_score and sc >= conf_threshold:
                        best_score = float(sc)
                        best_cid = cid

            if best_cid is None:
                continue

            cx = cand_xy[i, 0] / scale
            cy = cand_xy[i, 1] / scale
            bw = cand_wh[i, 0] / scale
            bh = cand_wh[i, 1] / scale

            x1 = max(0, int(cx - bw / 2.0))
            y1 = max(0, int(cy - bh / 2.0))
            w_box = min(orig_w - x1, int(bw))
            h_box = min(orig_h - y1, int(bh))

            if w_box > 10 and h_box > 10:
                boxes.append([x1, y1, w_box, h_box])
                confidences.append(best_score)
                class_ids.append(best_cid)

        if not boxes:
            return []

        indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_threshold, nms_threshold)
        results = []
        frame_area = max(1, orig_w * orig_h)

        if len(indices) > 0:
            for idx in indices.flatten():
                x1, y1, bw, bh = boxes[idx]
                x2 = min(orig_w, x1 + bw)
                y2 = min(orig_h, y1 + bh)
                cid = class_ids[idx]
                cname = COCO_CLASSES[cid]
                score = confidences[idx]
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                area_frac = (bw * bh) / frame_area

                results.append({
                    "class_id": cid,
                    "class_name": cname,
                    "conf": round(score, 3),
                    "box": [x1, y1, x2, y2],
                    "center": (round(cx, 1), round(cy, 1)),
                    "area_frac": round(area_frac, 4),
                    "height_frac": round(bh / orig_h, 4)
                })

        # Sort by confidence * area descending
        results.sort(key=lambda d: d["conf"] * d["area_frac"], reverse=True)
        return results

    def is_centered(self, box, frame_w, frame_h):
        """
        Evaluates whether pet box center is within target safe center:
        x: 35% - 65% of frame width
        y: 30% - 65% of frame height
        """
        x1, y1, x2, y2 = box
        cx = ((x1 + x2) / 2.0) / frame_w
        cy = ((y1 + y2) / 2.0) / frame_h
        centered = (0.35 <= cx <= 0.65) and (0.30 <= cy <= 0.65)
        return centered, cx, cy

import sqlite3
import json
import time

STAGE_A_CACHE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage_a_cache.db")

class StageACache:
    def __init__(self, db_path=STAGE_A_CACHE_DB):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stage_a_cache (
                    source_hash TEXT,
                    start_s REAL,
                    end_s REAL,
                    analyzer_version TEXT,
                    thresholds_hash TEXT,
                    result_json TEXT,
                    created_at REAL,
                    PRIMARY KEY (source_hash, start_s, end_s, analyzer_version, thresholds_hash)
                )
            """)
            conn.commit()

    def get(self, source_hash: str, start_s: float, end_s: float, analyzer_version: str, thresholds_hash: str):
        st = round(float(start_s), 1)
        en = round(float(end_s), 1)
        try:
            with self._get_conn() as conn:
                cur = conn.execute("""
                    SELECT result_json FROM stage_a_cache
                    WHERE source_hash = ? AND round(start_s, 1) = ? AND round(end_s, 1) = ?
                      AND analyzer_version = ? AND thresholds_hash = ?
                """, (source_hash, st, en, analyzer_version, thresholds_hash))
                row = cur.fetchone()
                if row:
                    return json.loads(row["result_json"])
        except Exception:
            pass
        return None

    def _sanitize_for_json(self, obj):
        try:
            import numpy as np
            if isinstance(obj, dict):
                return {str(k): self._sanitize_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [self._sanitize_for_json(v) for v in obj]
            elif isinstance(obj, (np.floating, float)):
                return float(obj)
            elif isinstance(obj, (np.integer, int)):
                return int(obj)
            elif isinstance(obj, (np.bool_, bool)):
                return bool(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
        except ImportError:
            pass
        return obj

    def put(self, source_hash: str, start_s: float, end_s: float, analyzer_version: str, thresholds_hash: str, result_dict: dict):
        st = round(float(start_s), 1)
        en = round(float(end_s), 1)
        try:
            clean_dict = self._sanitize_for_json(result_dict)
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO stage_a_cache 
                    (source_hash, start_s, end_s, analyzer_version, thresholds_hash, result_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (source_hash, st, en, analyzer_version, thresholds_hash, json.dumps(clean_dict, default=str), time.time()))
                conn.commit()
        except Exception:
            pass

    def clear(self, source_hash: str, start_s: float, end_s: float):
        st = round(float(start_s), 1)
        en = round(float(end_s), 1)
        try:
            with self._get_conn() as conn:
                conn.execute("""
                    DELETE FROM stage_a_cache
                    WHERE source_hash = ? AND round(start_s, 1) = ? AND round(end_s, 1) = ?
                """, (source_hash, st, en))
                conn.commit()
        except Exception:
            pass

def fast_pet_presence_check(video_path: str, start_s: float, end_s: float, detector: PetDetector = None) -> tuple:
    """
    Fast path (<1s): Samples first 4 frames across early candidate window.
    Downscales frames to 480x270. If 0 pets detected across all 4 frames,
    returns (False, 0.0) immediately.
    """
    if detector is None:
        detector = PetDetector()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False, 0.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    
    window_len = max(0.5, end_s - start_s)
    step = min(0.5, window_len / 4.0)
    timestamps = [start_s + i * step for i in range(4)]
    
    any_pet = False
    max_conf = 0.0
    
    cur_frame = 0
    first = True
    for ts in timestamps:
        target_frame = int(ts * fps)
        if first:
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            cur_frame = target_frame
            first = False
        else:
            diff = target_frame - cur_frame
            if 0 < diff <= 60:
                for _ in range(diff - 1):
                    cap.grab()
                cur_frame = target_frame
            elif diff > 60 or diff < 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                cur_frame = target_frame
        ret, frame = cap.read()
        cur_frame += 1
        if not ret or frame is None:
            continue
        h, w = frame.shape[:2]
        if w > 480:
            scale = 480.0 / w
            frame_small = cv2.resize(frame, (480, int(h * scale)), interpolation=cv2.INTER_NEAREST)
        else:
            frame_small = frame
        dets = detector.detect(frame_small, conf_threshold=0.25)
        if dets:
            any_pet = True
            for d in dets:
                if d.get("conf", 0.0) > max_conf:
                    max_conf = d["conf"]
            break
            
    cap.release()
    return any_pet, max_conf

