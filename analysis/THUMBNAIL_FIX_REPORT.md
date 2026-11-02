# LionReel Studio — Thumbnail Maker Fix Engineering Report

**Task:** Fix YouTube Thumbnail Maker: Eliminate black edges/bars, guarantee true edge-to-edge full-bleed 16:9 images, enforce Long-videos-only scope, implement clean-by-default cat face framing with provenance tracking, export 3-variant test sets and mobile-safe assets, and provide an interactive Cutting Room UI studio.  
**Date:** 2026-10-18  
**Environment:** Windows (PowerShell), Python 3.11 (`C:\LionReel\venv\Scripts\python.exe`), OpenCV 4.10, Pillow, Playwright (Google Chrome `channel="chrome"`).  
**Backup Archive:** `C:\LionReel_backups\thumb_fix_backup_20261017` (outside Google Drive; 0 files deleted).  

---

## 1. Executive Summary & Proof of Resolution

The Thumbnail Maker in LionReel Studio has been overhauled and verified end-to-end. Previously, the thumbnail pipeline generated images with black edges/pillarbox bars from letterboxed sources, lacked subject-aware framing, offered thumbnails for YouTube Shorts (where custom thumbnails are not supported), lacked provenance metadata, and did not generate YouTube Test and Compare variant sets.

### Key Metrics & Test Proof
| Metric / Contract | Before Fix | After Fix | Verified Status |
| :--- | :--- | :--- | :--- |
| **Full-Bleed Gate (16:9, 0 Bars)** | Failed on letterboxed inputs (`thumb_bad_bars.png` exported with 60px black bars) | 100% full-bleed gate (`check_full_bleed` rejects mean luma $< 14$, 1% edge bands, and corner bars; `subject_aware_cover_crop` crops active area) | **PASSED** (14/14 unit tests pass) |
| **Shorts Scope Gating** | Thumbnails offered and generated for Shorts | Gated strictly by job mode & duration ($< 180$s). API returns HTTP 200 with `{"available": false, "skipped": true, "error": "not available for Shorts"}`; UI hides thumbnail buttons | **PASSED** (Verified on `lionreel_cat_20261017_223027_c54267b4`) |
| **Candidate Count & Diversity** | Inflexible extraction, occasional duplicate moments | Top 6 diverse candidates ($> 10$s temporal distance, different clips, luma variance $> 18.0$) | **PASSED** (6 candidates verified across 3 long videos) |
| **Provenance Metadata** | None | Full origin tracking attached to all candidates & JSONs (`video_file`, `timestamp_sec`, `clip_id`, `source_window`, `decoder`, `crop_box`) | **PASSED** (Embedded in all `.json` companion files) |
| **Default Style** | Text/hooks baked in | Clean picture by default. Optional "Add text" toggle adds high-contrast ($\ge 4.5:1$) hook outside bottom-right badge safe zone; clean master always exported | **PASSED** (Verified in Playwright & unit tests) |
| **Export Bundle** | Single unoptimized file | Master 1920x1080 JPG (Q90), Mobile-safe 1280x720 JPG ($\le 2$ MB binary search), Test & Compare variants A, B, C ($\ge 1280\times 720$), and JSONs | **PASSED** (All files present in `output/<job_id>/thumbnails/`) |
| **Playwright UI Verification** | Untested in Chrome | 100% pass across Desktop 1440px (dark & light), Mobile 390px, 3:00 long video, and 19:52 long video | **PASSED** (Chrome `channel="chrome"`, 0 errors) |

---

## 2. Root Cause Analysis (Path, Expected, Actual, Root Cause)

| Component / File | Expected Behavior | Actual Behavior Before Fix | Root Cause (File & Line) | Resolution Applied |
| :--- | :--- | :--- | :--- | :--- |
| **Full-Bleed Gate**<br>`thumbnail_maker.py` | Detect and reject black/dark letterbox or pillarbox bars ($\ge 1\%$ dimension, luma $< 14$) | Exported source frames directly without checking outer 6px borders or corner pixels | `thumbnail_maker.py:352`<br>No edge luma inspection or variance check existed in pipeline | Implemented `detect_source_bars` & `check_full_bleed` inspecting all 4 margins (top, bottom, left, right) and all 4 corners for luma $< 14$ and low variance |
| **Framing & Aspect Ratio**<br>`thumbnail_maker.py` | Full-frame cat face (50–95% height, eye line in upper half, mouth/eyes uncropped, min 1024x576 crop) | Fixed naive center-crop or distorted resize, occasionally cropping mouths or ears | `thumbnail_maker.py:580`<br>Naive bounding box expansion without aspect-ratio anchoring | Implemented `subject_aware_cover_crop` with 1.25x upscale floor (min crop $1024\times 576$), eye-line placement ($y_{\text{eye}} \in [0.28, 0.48]$), and multi-detection (`double_cats`) union box |
| **Shorts Scope Isolation**<br>`web_server.py`, `deliverables_manager.py` | Long videos only ($\ge 180$s or mode `long`/`both`). Shorts must return `available: false` and hide buttons | Shorts showed "16:9 Thumbnail" buttons and generated invalid vertical-derived thumbnails | `deliverables_manager.py:284`, `web_server.py:843`<br>Thumbnail existence was determined purely by file presence on disk rather than job mode | Implemented `is_thumbnail_supported_for_job(job_id)` inspecting job mode across planner decisions, specs, and aspect ratio. Stale short thumbnails purged automatically |
| **Text Detector False Positives**<br>`overlay_text_detector.py` | Detect burned-in subtitles and lower-third watermarks | Thin cat whiskers in close-up face shots triggered false text detections | `thumbnail_maker.py:790`<br>Text detector ran on raw high-frequency edge map without aspect filtering | Targeted `analyze_frame_text_and_borders` to cropped candidate area and tuned stroke aspect ratio to distinguish text characters from whisker gradients |
| **Candidate Preview UI**<br>`gui/index.html`, `gui/style.css` | Candidates rendered at true 16:9 without black letterbox framing inside preview card | Preview grid boxes had black background `#000` and letterboxed image rendering | `gui/style.css:4120`<br>`.thumb-candidate-item` had `background: #000` and `object-fit: contain` | Updated `.thumb-candidate-item` to use `background: var(--bg-card)` and `object-fit: cover` with `aspect-ratio: 16 / 9`, matching Cutting Room design tokens |
| **Export Packaging**<br>`thumbnail_maker.py` | Output master 1920x1080, mobile 1280x720 ($\le 2$ MB), and 3 distinct variants for YouTube A/B/C testing | Single `thumbnail.jpg` exported without size bounds or companion JSON metadata | `thumbnail_maker.py:1120`<br>Missing multi-variant export loop and binary size convergence | Added `export_thumbnail_sets` generating master (Q90), binary search for mobile $\le 2$ MB, variants A (crop zoom), B (warmth boost), C (rule of thirds offset), each with provenance JSON |

---

## 3. Provenance Architecture & Gate Verification

Every exported thumbnail candidate and final export file is strictly derived from the decoded final rendered video (or verified source window). Thumbnails downloaded via external yt-dlp posters are completely rejected.

### Metadata Schema (`thumbnail_master_1920x1080.json` Example)
```json
{
  "job_id": "lionreel_cat_3min_16_9",
  "export_type": "master_1920x1080",
  "dimensions": [1920, 1080],
  "aspect_ratio": "16:9",
  "file_size_bytes": 245742,
  "video_file": "output/lionreel_cat_3min_16_9/lionreel_cat_3min_16_9.mp4",
  "timestamp_sec": 29.83,
  "clip_id": "clip_03_cat_portrait",
  "source_window": [25.0, 35.0],
  "decoder": "ffmpeg/imageio_opencv",
  "crop_box": [128, 72, 1152, 648],
  "scores": {
    "sharpness": 88.5,
    "face_coverage": 72.4,
    "eye_contrast": 84.1,
    "composite": 82.9
  },
  "full_bleed_verified": true,
  "human_face_detected": false
}
```

---

## 4. YouTube Platform Limits & Compliance

Verified against official YouTube Help documentation and stored in `config/platform_limits.json` (`checked_on: "2026-10-17"`):

| Limit Specification | YouTube Platform Requirement | LionReel Studio Enforcement | Status |
| :--- | :--- | :--- | :--- |
| **Aspect Ratio** | Strictly 16:9 | Master 1920x1080, Mobile 1280x720, Variants 1280x720 | **COMPLIANT** |
| **Minimum Width** | Minimum 640 pixels | Smallest exported file is 1280x720 (2x the minimum) | **COMPLIANT** |
| **File Format** | JPG, PNG, GIF | High-quality baseline JPEG | **COMPLIANT** |
| **Max File Size** | 2 MB for YouTube uploads (50 MB desktop API limit) | Mobile thumbnail strictly verified $\le 2{,}097{,}152$ bytes via binary quality search | **COMPLIANT** |
| **Safe Zone** | Bottom-right duration badge clearance ($180 \times 70$ px at 720p) | Text hooks and facial bounding boxes restricted to top/center; bottom-right cleared | **COMPLIANT** |
| **WCAG Text Contrast** | Accessible readability at small sizes ($\ge 4.5:1$) | Tested with `calculate_wcag_contrast`; white text with dark outline yields $\ge 7.0:1$ | **COMPLIANT** |

---

## 5. Visual Artifacts & Contact Sheets

### Candidate Contact Sheets
Below are the 6 diverse candidates generated per video job, showing timestamps, full-bleed edge verification, and composite scores:

1. **3:00 16:9 Long Compilation (`lionreel_cat_3min_16_9`)**:  
   ![3min Contact Sheet](file:///C:/Users/dinsa/.gemini/antigravity-ide/brain/0a4dbbd5-c563-4ec7-a5e8-86e88588d94c/contact_sheet_lionreel_cat_3min_16_9.png)  
   *Output Directory:* `output/lionreel_cat_3min_16_9/thumbnails/` (Master 1920x1080: 245 KB, Mobile 1280x720: 185 KB, Variants A/B/C).

2. **19:52 16:9 Long Documentary (`lionreel_cat_20261015_190045_fc2355ef`)**:  
   ![19min Contact Sheet](file:///C:/Users/dinsa/.gemini/antigravity-ide/brain/0a4dbbd5-c563-4ec7-a5e8-86e88588d94c/contact_sheet_lionreel_cat_20261015_190045_fc2355ef.png)  
   *Output Directory:* `output/lionreel_cat_20261015_190045_fc2355ef/thumbnails/` (Top score: 90.30, Master: 196 KB, Mobile: 152 KB, Variants A/B/C).

3. **Vertical Long Video (`lionreel_cat_vertical_long`)**:  
   ![Vertical Long Contact Sheet](file:///C:/Users/dinsa/.gemini/antigravity-ide/brain/0a4dbbd5-c563-4ec7-a5e8-86e88588d94c/contact_sheet_lionreel_cat_vertical_long.png)  
   *Output Directory:* `output/lionreel_cat_vertical_long/thumbnails/` (Subject-aware cover crop derived full 16:9 landscape master without letterbox).

### Playwright Browser Test Screenshots
Verified in installed Google Chrome (`channel="chrome"`, headless):

- **Desktop Dark Theme (1440x900)**:  
  ![Desktop Dark Modal](file:///C:/Users/dinsa/.gemini/antigravity-ide/brain/0a4dbbd5-c563-4ec7-a5e8-86e88588d94c/thumb_modal_desktop_dark.png)  
  *Features:* 6-candidate grid, live full preview, real-size previews (Mobile 210x118, Compact 168x94), full-bleed badge checklist, and action buttons (`Use this`, `Fresh Candidates`, `Download`, `Copy path`, `Open YouTube Studio`).

- **Desktop Light Theme (1440x900)**:  
  ![Desktop Light Modal](file:///C:/Users/dinsa/.gemini/antigravity-ide/brain/0a4dbbd5-c563-4ec7-a5e8-86e88588d94c/thumb_modal_desktop_light.png)  
  *Features:* Cutting Room Warm Paper aesthetic (`#F4F1EA`), high contrast, zero glare.

- **Optional Text Hook Overlay**:  
  ![Text Hook Toggle](file:///C:/Users/dinsa/.gemini/antigravity-ide/brain/0a4dbbd5-c563-4ec7-a5e8-86e88588d94c/thumb_modal_with_text.png)  
  *Features:* Truthful 3–5 word hook with thick outline, avoiding the bottom-right timestamp badge safe zone.

- **Mobile Viewport (390x844)**:  
  ![Mobile Modal](file:///C:/Users/dinsa/.gemini/antigravity-ide/brain/0a4dbbd5-c563-4ec7-a5e8-86e88588d94c/thumb_modal_mobile_dark.png)  
  *Features:* Stacked responsive layout, zero horizontal overflow.

---

## 6. Unit & Contract Test Suite Results

### Contract Test Suite (`tests/test_thumbnail_contract_failing.py`)
```
Ran 5 tests in 0.712s
OK
- test_fixture_bad_bars_fails_gate: PASS (Detects 60px black bars, fails luma/variance check)
- test_fixture_good_full_passes_gate: PASS (Clean 16:9 full-frame cat face passes all gates)
- test_subject_aware_cover_crop_no_black_edges: PASS (Produces 0 black bars on 4:3 inputs)
- test_detect_burned_in_text_tolerates_whiskers: PASS (Zero false positives on cat whiskers)
- test_export_mobile_under_2mb: PASS (Verified 1280x720 export <= 2,097,152 bytes)
```

### Full Fix Suite (`tests/test_thumbnail_fix_suite.py`)
```
Ran 9 tests in 4.641s
OK
- test_01_full_bleed_gate_rejects_bars: PASS
- test_02_cropdetect_and_subject_aware_crop: PASS
- test_03_scope_long_videos_only: PASS
- test_04_provenance_metadata_attached: PASS
- test_05_clean_by_default_and_text_toggle: PASS
- test_06_platform_limits_compliance: PASS
- test_07_export_sets_and_variants: PASS
- test_08_no_downloaded_posters_used: PASS
- test_09_double_cats_framing_union_box: PASS
```

---

## 7. Honest Limits & Edge Cases

1. **Low-Resolution Source Footage**: If source video is below 720p (e.g. 640x360), upscaling to 1920x1080 master applies bicubic interpolation with unsharp mask sharpening, but cannot synthesize missing optical detail. A diagnostic warning (`"source resolution below recommended 1080p master"`) is recorded in `thumbnail_report.json`.
2. **Extreme Low-Light / High-Noise Scenes**: Scenes where cats are filmed in near-total darkness (mean frame luma $< 16$) may trigger low-luma threshold warnings. In such cases, the candidate extractor seeks brighter candidate frames across other clips before falling back to contrast enhancement.
3. **Multi-Animal Crowds ($> 2$ Cats)**: When more than two cats are present simultaneously, the framing algorithm prioritizes the two largest face bounding boxes to avoid excessive zooming out that would diminish thumbnail click-through impact.
4. **YouTube Shorts Upload Policy**: As verified in `config/platform_limits.json`, YouTube API does not permit setting custom thumbnail images on Shorts; YouTube automatically assigns a frame from the vertical video. LionReel Studio strictly respects this policy by omitting custom thumbnail creation for Shorts and providing clear informational responses.
