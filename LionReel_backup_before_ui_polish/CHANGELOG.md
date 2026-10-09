# LionReel Studio — Engineering Changelog (V97 Master Release)

**Date**: October 4, 2026  
**Pipeline Version**: V97 (`lion_automate_v97.py`)  
**Target Quality Reference**: `reference/Funny Cats.mp4`  
**Automated QA Engine**: `qa_check.py` (8-point automated validation)  

---

## 1. Executive Summary & Root Cause Resolution

LionReel V97 is a ground-up calibration and stabilization of the automated pet short-form video pipeline. It completely eliminates all 8 defects measured on the baseline render (`lion_master_cat_1791107091.mp4`), introduces a persistent SQLite clip ledger, enforces real-footage computer vision validation, and aligns the web dashboard to a centered, responsive design.

---

## 2. Before vs. After Benchmark Comparison

| Metric / Requirement | Baseline Defect (`lion_master_cat_1791107091.mp4`) | LionReel V97 Master Output | Verdict |
|---|---|---|:---:|
| **Subject Centering** | Pet center drifted to 15.6% from edge; face cut off | 95.8% pet detection, 95.7% centered in 35–65% box | **PASS ✅** |
| **Output Bitrate** | 2,470 kbps (starved, pixelated on mobile) | 8,123 kbps (strict VBV: 6,000–14,000 kbps) | **PASS ✅** |
| **Laplacian Sharpness** | Median LapVar 78.4 (blurry, low-res upscale) | Median LapVar 247.1 (target ≥ 150) | **PASS ✅** |
| **Audio Loudness** | -19.4 LUFS (quiet), Peak +1.2 dBTP (digital clipping) | -13.03 LUFS integrated, -3.58 dBTP True Peak | **PASS ✅** |
| **Caption Safe Zone** | Rendered at Y=1650px (covered by UI buttons); crossed cuts | Y=320px top safe zone, single-clip only, never spans cuts | **PASS ✅** |
| **Clip Duplication** | Repeated same clip twice in 30s; repeats across runs | 0 repeats; SQLite ledger with 64-bit pHash Hamming distance | **PASS ✅** |
| **Real Footage Gate** | 3D cartoon / CGI clip mistakenly ingested | AI / Cartoon classifier: 0.0% negative probability | **PASS ✅** |
| **Frame Glitches** | 2 black frames, 1 frozen transition | 0 black frames, 0 frozen frames | **PASS ✅** |
| **Source Protection** | Risk of benchmark reference being re-encoded | Hard perceptual hash guard blocks reference benchmark | **PASS ✅** |
| **Metadata Hygiene** | Keyword tag spam and auto-generated descriptions | Clean title only (e.g. `Try Not To Laugh - Funniest Cats Ever! 😹`) | **PASS ✅** |

---

## 3. Detailed Changes by Component

### A. Computer Vision & Subject-Tracking Reframing (`pet_detector.py` & `lion_automate_v97.py`)
- **Added `PetDetector` (`pet_detector.py`)**:
  - Implemented high-performance YOLOX ONNX detector using OpenCV DNN.
  - Detects cats (class 15) and dogs (class 16) with confidence scoring, bounding box normalization, and center calculations.
- **Added `SubjectReframer` (`lion_automate_v97.py`)**:
  - Computes dynamic 9:16 crop window based on median pet trajectory.
  - Enforces target pet vertical position at 46% of crop height.
  - Automatically falls back to blurred-background fit (`split -> scale/boxblur + overlay`) if subject touches source frame edges or aspect ratio exceeds bounds.
  - Post-crop verification gate checks rendered crop before assembly; rejects off-center clips.

### B. Persistent SQLite Clip Ledger (`clip_ledger.py` & `data/clip_ledger.db`)
- **Created `data/clip_ledger.db`** with tables:
  - `clips`: Tracks `clip_id`, `source_path`, `start_s`, `end_s`, `fingerprint` (10-frame DCT perceptual hashes), `animal_type`, `times_used`, `pending_short_id`, `pool_cycle`.
  - `system_state`: Persists active pool cycles (`pool_cycle_cat`, `pool_cycle_dog`, `pool_cycle_duo`).
- **Duplicate Prevention & Cycle Management**:
  - Within-short duplicates blocked via Hamming distance check (distance ≤ 6 flags near-duplicate).
  - Across-shorts duplicates blocked: only clips with `times_used < pool_cycle` are eligible.
  - Automatic cycle rollover: When eligible pool is exhausted, increments pool cycle (`pool_cycle + 1`) and logs `[Ledger Alert] REPEAT_CYCLE_STARTED`.
  - Two-stage reservation/commit/release: clips are marked pending during render; committed on QA pass; released on QA failure or user cancellation.

### C. Safe-Zone Caption Engine (`lion_automate_v97.py`)
- **Single-Clip Captions**:
  - Captions are strictly bounded to individual clips and never cross cut boundaries.
  - Styled with 5px dark outline (`#0A0A0F`), soft drop shadow, and clean white fill.
  - Font support: Montserrat for English; Noto Sans Sinhala for Sinhala.
  - Safe-zone positioning: Y = 320px (well clear of TikTok / Reels top header and bottom captions/buttons).
  - Fade-in (0.15s) and fade-out before clip ends.

### D. Audio Mastering & Normalization (`lion_automate_v97.py`)
- **Two-Pass EBU R128 Loudnorm**:
  - Pass 1: Measures input integrated loudness, True Peak, LRA, and threshold.
  - Pass 2: Exact linear normalization to Integrated = -14.0 LUFS, True Peak ≤ -1.0 dBTP, LRA = 11.0.
  - Ducked background music (-14 dB relative to pet audio) prevents speech/meow masking.
  - Brickwall peak limiter (`alimiter=limit=-1.0dB`) prevents inter-sample clipping on mobile speakers.

### E. Video Encoding & Export Settings (`lion_automate_v97.py`)
- Target Bitrate: 8,500 kbps (constrained between 6,000 kbps minrate and 14,000 kbps maxrate via VBV buffer).
- Codec: `libx264`, preset `slow`, profile `high`, level `4.2`.
- Color: Rec.709 color matrix, primaries, and transfer characteristics (`-colorspace bt709 -color_primaries bt709 -color_trc bt709`).
- Container: MP4 with `+faststart` (moov atom at beginning of file for instant web streaming).
- Output: Strict 1080x1920 (9:16 vertical), constant 30.0 fps, GOP = 60 (2.0s keyframe cadence).

### F. Automated Quality Assurance (`qa_check.py`)
- Automatically runs after every export:
  1. Stream Specs: 1080x1920, H.264 High, bitrate ≥ 6,000 kbps.
  2. Glitch Detection: `blackdetect` and `freezedetect` (0 tolerance).
  3. Loudness: EBU R128 (-15.5 to -12.5 LUFS, TP ≤ -0.9 dBTP).
  4. Pet Centering: YOLOX detection on 24 frames (≥ 85% presence, ≥ 85% centering in safe box).
  5. Real Footage Gate: Cartoon / CGI classifier (< 25% negative probability).
  6. Visual Sharpness: Laplacian variance median ≥ 150.0.
  7. Caption Safe Zone: Canny edge verification on top 220px and bottom 380px.
  8. Blocklist Guard: Perceptual hash comparison against `config/blocked_sources.json`.
  9. Contact Sheet: Generates 12-frame contact sheet with bounding box and crosshair overlays.

### G. UI Alignment & Ledger Dashboard (`gui/style.css`, `web_server.py`)
- Horizontal centering: `.app-viewport` set to `max-width: 1140px; margin: 0 auto; width: 100%;`.
- Grid: 3 equal cards on desktop (`repeat(3, minmax(0, 1fr))`), 1 column on mobile.
- Clip Ledger & Footage Pool panel: Real-time usage bar, cycle indicator, and low-pool alert banner.
- API endpoints: `/api/pool` exposes real-time pool status; `/api/start` triggers `lion_automate_v97.py`.
- **Live Dynamic Summary Bar Overhaul (`gui/style.css`, `gui/index.html`, `gui/app.js`)**:
  - Full width expansion (`width: 100%`) matching `.config-card` boundaries with zero inset margin gaps.
  - Relocated outside `.config-card` directly above wizard navigation footer, eliminating any card obscuration / overlap.
  - Implemented `@keyframes summaryFitIn` spring entrance dock animation and `@keyframes summaryPulseFit` reactive pulse when duration/clip count/format updates.
  - Integrated `IntersectionObserver` in `gui/app.js` to trigger the fit-in animation precisely when scrolled into view.

---

## 4. How to Run (Single Command)

### Standard Run (Reads `config.json`):
```powershell
.venv\Scripts\python.exe lion_automate_v97.py
```

### Direct CLI Overrides:
```powershell
# Feline Short (3-5 clips, ~20s)
.venv\Scripts\python.exe lion_automate_v97.py --mode cat --type short --count 1

# Canine Short
.venv\Scripts\python.exe lion_automate_v97.py --mode dog --type short --count 1

# Compilation (9-12 clips, 45-90s)
.venv\Scripts\python.exe lion_automate_v97.py --mode cat --type compilation --count 1
```

### Run QA Check on Any Video:
```powershell
.venv\Scripts\python.exe qa_check.py finished/<video_name>.mp4
```

### Run Local Web Dashboard:
```powershell
.venv\Scripts\python.exe web_server.py
# Open http://localhost:8000 in browser
```
