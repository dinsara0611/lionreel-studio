"""
Pet Detector Module using YOLOX ONNX for LionReel
Detects cats (class 15) and dogs (class 16) with robust bounding box regression.
"""

import os
import cv2
import numpy as np

YOLOX_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "models", "object_detection_yolox_2022nov.onnx")

COCO_CLASSES = {
    15: "cat",
    16: "dog"
}

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
        self.model_path = model_path
        self.net = cv2.dnn.readNetFromONNX(model_path)
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

    def detect(self, frame, conf_threshold=0.30, nms_threshold=0.45):
        """
        Detects cats and dogs in the given BGR frame.
        Returns list of dicts:
        [{'class_id': int, 'class_name': str, 'conf': float, 'box': [x1, y1, x2, y2], 'center': (cx, cy), 'area_frac': float}]
        """
        if frame is None or frame.size == 0:
            return []
        
        orig_h, orig_w = frame.shape[:2]
        padded, scale = self._preprocess(frame)
        
        blob = cv2.dnn.blobFromImage(padded, scalefactor=1.0, size=self.input_size, mean=(0, 0, 0), swapRB=False, crop=False)
        self.net.setInput(blob)
        output = self.net.forward()  # shape (1, 3549, 85)
        preds = output[0]

        # Decode output
        box_xy = (preds[:, :2] + self.grids) * self.expanded_strides
        box_wh = np.exp(preds[:, 2:4]) * self.expanded_strides
        obj_conf = preds[:, 4:5]
        class_scores = preds[:, 5:] * obj_conf

        # Classes 15 (cat) and 16 (dog)
        pet_mask = (class_scores[:, 15] > conf_threshold) | (class_scores[:, 16] > conf_threshold)
        if not np.any(pet_mask):
            return []

        cand_xy = box_xy[pet_mask]
        cand_wh = box_wh[pet_mask]
        cand_scores = class_scores[pet_mask]

        boxes = []
        confidences = []
        class_ids = []

        for i in range(len(cand_xy)):
            c15 = cand_scores[i, 15]
            c16 = cand_scores[i, 16]
            if c15 >= c16 and c15 >= conf_threshold:
                cid = 15
                score = float(c15)
            elif c16 > c15 and c16 >= conf_threshold:
                cid = 16
                score = float(c16)
            else:
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
                confidences.append(score)
                class_ids.append(cid)

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
