"""
LionReel Watermark and Channel Logo Detection Module
Detects static corner logos, TV/channel bugs, and burned-in watermarks:
- WOA Network (red cube + "WOA" lettering in bottom-left)
- Paw Life / Tiger Funnyworks / common compilation bugs
- Generic static graphic badges and corner watermarks
Rejects clips with watermarks without attempting to mask or crop them out.
"""

import os
import cv2
import numpy as np

class WatermarkDetector:
    def __init__(self, corner_w_frac=0.22, corner_h_frac=0.20):
        self.corner_w_frac = corner_w_frac
        self.corner_h_frac = corner_h_frac
        self.assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "watermarks")
        self.woa_mask = None
        self._load_templates()

    def _load_templates(self):
        mask_path = os.path.join(self.assets_dir, "woa_mask.png")
        if os.path.exists(mask_path):
            self.woa_mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)

    def check_video_corners(self, video_path, start_s=0.0, dur_s=None, n_samples=10):
        """
        Samples frames across the specified segment and analyzes all four corners:
        - Top-Left (TL), Top-Right (TR), Bottom-Left (BL), Bottom-Right (BR)
        Returns:
            has_watermark (bool): True if static logo/watermark is present
            detected_corner (str): 'top_left', 'top_right', 'bottom_left', 'bottom_right', or None
            confidence (float): 0.0 - 1.0
            reason (str): Description of the finding
        """
        if not os.path.exists(video_path):
            return False, None, 0.0, "File not found"

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return False, None, 0.0, "Cannot read video"

        start_f = int(start_s * fps)
        clip_frames = int(dur_s * fps) if dur_s else (total_frames - start_f)
        clip_frames = max(1, min(clip_frames, total_frames - start_f))

        # Evenly spaced frame indices across segment
        sample_indices = [
            start_f + int(clip_frames * (i + 0.5) / n_samples)
            for i in range(n_samples)
        ]

        frames = []
        for f_idx in sample_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(f_idx, total_frames - 1))
            ret, frame = cap.read()
            if ret and frame is not None:
                frames.append(frame)

        cap.release()

        if len(frames) < 3:
            return False, None, 0.0, "Insufficient sample frames"

        h, w = frames[0].shape[:2]
        cw = int(w * self.corner_w_frac)
        ch = int(h * self.corner_h_frac)

        # 1. First check specific WOA logo pattern on bottom-left corner
        bl_crop = frames[0][h - ch:h, 0:cw]
        is_woa, woa_conf = self._detect_woa_logo(bl_crop)
        if is_woa:
            return True, "bottom_left", woa_conf, "WOA Network logo detected in bottom-left corner"

        # 2. Check for vibrant colored logo emblems (blue, green, red badges like Paw Life)
        for corner_name, ((x1, y1), (x2, y2)) in [
            ("bottom_left", [(0, h - ch), (cw, h)]),
            ("top_right", [(w - cw, 0), (w, ch)]),
            ("top_left", [(0, 0), (cw, ch)]),
            ("bottom_right", [(w - cw, h - ch), (w, h)])
        ]:
            cr_first = frames[0][y1:y2, x1:x2]
            b, g, r = cv2.split(cr_first.astype(float))
            # Vibrant blue/cyan badge (e.g. Paw Life)
            vibrant_blue = (b > 130) & (b > 1.35 * r) & (b > 1.1 * g)
            if np.sum(vibrant_blue) > 400:
                c_crops = [f[y1:y2, x1:x2] for f in frames]
                st = np.std(np.stack(c_crops, axis=0), axis=0).mean(axis=2)
                if np.mean(st[vibrant_blue]) < 3.5:
                    return True, corner_name, 0.96, f"Vibrant static colored channel emblem (Paw Life/bug) in {corner_name}"

        # Global motion check: calculate motion across center of frame
        center_crops = [f[int(h*0.25):int(h*0.75), int(w*0.25):int(w*0.75)] for f in frames]
        center_stack = np.stack(center_crops, axis=0).astype(np.float32)
        center_std = float(np.mean(np.std(center_stack, axis=0)))

        corners = {
            "top_left": [(0, 0), (cw, ch)],
            "top_right": [(w - cw, 0), (w, ch)],
            "bottom_left": [(0, h - ch), (cw, h)],
            "bottom_right": [(w - cw, h - ch), (w, h)]
        }

        # Analyze each corner for static logos/badges
        for corner_name, ((x1, y1), (x2, y2)) in corners.items():
            corner_crops = [f[y1:y2, x1:x2] for f in frames]
            stack = np.stack(corner_crops, axis=0).astype(np.float32)
            temp_std = np.std(stack, axis=0) # shape (ch, cw, 3)
            mean_temp_std = np.mean(temp_std, axis=2) # shape (ch, cw)

            # High spatial frequency edge detection on first frame
            gray_first = cv2.cvtColor(corner_crops[0], cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray_first, 60, 160)

            # Watermark pixels: static across time (std < 3.0) and coinciding with sharp edges
            static_mask = (mean_temp_std < 3.0)
            edge_and_static = (edges > 0) & static_mask
            
            # Connected components of static edge clusters
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            dilated_edges = cv2.dilate(edge_and_static.astype(np.uint8), kernel, iterations=2)
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(dilated_edges)

            for lbl in range(1, num_labels):
                area = stats[lbl, cv2.CC_STAT_AREA]
                comp_w = stats[lbl, cv2.CC_STAT_WIDTH]
                comp_h = stats[lbl, cv2.CC_STAT_HEIGHT]

                # Typical logo badge dimensions: 250 to 8000 px
                if 250 <= area <= (cw * ch * 0.45):
                    aspect = comp_w / max(1, comp_h)
                    if 0.3 <= aspect <= 4.0:
                        comp_mask = (labels == lbl)
                        comp_var = float(np.mean(mean_temp_std[comp_mask]))
                        if comp_var < 2.5 and (center_std > 8.0 or comp_var < center_std * 0.25):
                            return True, corner_name, 0.94, f"Static channel logo detected in {corner_name} (badge area {area}px, std {comp_var:.1f})"

        return False, None, 0.0, "Clean corners (no watermark detected)"

    def verify_source_watermark(self, video_path, n_windows=6, window_dur=6.0):
        """
        Requirement 4: When a logo is found on a clip, sample 6 other windows across
        the same source. If at least 2 show it, the source is confirmed to carry a
        persistent channel watermark.
        Returns:
            is_source_blocked (bool): True if >= 2 windows show watermark
            hit_count (int): count of positive windows
            details (dict): corner and reason details
        """
        if not os.path.exists(video_path):
            return False, 0, {}

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()

        if total_frames <= 0:
            return False, 0, {}

        total_dur = total_frames / fps
        hit_count = 0
        detected_details = {}

        # 6 evenly spaced window start times across the source
        start_times = [
            max(0.0, min(total_dur - window_dur - 1.0, total_dur * ((i + 1) / (n_windows + 1))))
            for i in range(n_windows)
        ]

        for st in start_times:
            has_wm, corner, conf, reason = self.check_video_corners(
                video_path, start_s=st, dur_s=window_dur, n_samples=6
            )
            if has_wm:
                hit_count += 1
                detected_details = {"corner": corner, "reason": reason, "conf": conf}
                if hit_count >= 2:
                    break

        return (hit_count >= 2), hit_count, detected_details

    def _detect_woa_logo(self, bl_crop):
        """
        Detects WOA logo in bottom-left corner:
        - Red isometric cube with white cutout lines
        - Red "WOA" lettering
        - Yellow "INTEREST YOUR MIND" subtitle
        """
        if bl_crop is None or bl_crop.size == 0:
            return False, 0.0

        # Check for vibrant red color cluster in bottom-left
        hsv = cv2.cvtColor(bl_crop, cv2.COLOR_BGR2HSV)
        r1 = cv2.inRange(hsv, np.array([0, 120, 100]), np.array([10, 255, 255]))
        r2 = cv2.inRange(hsv, np.array([170, 120, 100]), np.array([180, 255, 255]))
        red_mask = r1 | r2

        # Check for yellow subtitle text: Hue 20-35, Sat 100-255, Val 120-255
        yellow_mask = cv2.inRange(hsv, np.array([18, 90, 120]), np.array([35, 255, 255]))
        yellow_count = int(np.sum(yellow_mask > 0))

        # Connected component on red mask
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(red_mask)
        has_cube = False
        has_letters = False

        for lbl in range(1, num_labels):
            area = stats[lbl, cv2.CC_STAT_AREA]
            w = stats[lbl, cv2.CC_STAT_WIDTH]
            h = stats[lbl, cv2.CC_STAT_HEIGHT]
            aspect = w / max(1, h)

            # Red cube: roughly square aspect 0.7 - 1.3, area 300 - 6000 px
            if 300 <= area <= 6000 and 0.65 <= aspect <= 1.4:
                has_cube = True
            # WOA letters: wider aspect or lettering components
            if 200 <= area <= 8000 and (aspect >= 1.5 or (w > 30 and h > 15)):
                has_letters = True

        if (has_cube and has_letters) or (has_cube and yellow_count > 50):
            return True, 0.99

        # Template match if mask is loaded
        if self.woa_mask is not None:
            for sc in [0.7, 0.85, 1.0, 1.15, 1.3]:
                th = int(self.woa_mask.shape[0] * sc)
                tw = int(self.woa_mask.shape[1] * sc)
                if th < red_mask.shape[0] and tw < red_mask.shape[1]:
                    tpl = cv2.resize(self.woa_mask, (tw, th))
                    res = cv2.matchTemplate(red_mask, tpl, cv2.TM_CCOEFF_NORMED)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                    if max_val > 0.42:
                        return True, float(max_val)

        return False, 0.0
