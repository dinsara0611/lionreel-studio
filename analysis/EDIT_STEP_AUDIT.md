# LionReel Studio — Step 3 (Edit) Exhaustive Control Audit
**Audit Date:** 2026-10-09  
**Scope:** Step 3 ("Edit") frontend (`gui/index.html`, `gui/app.js`, `gui/style.css`), backend API (`web_server.py`, `edl_manager.py`), rendering pipeline (`lion_automate_v97.py`), and storage (`clip_ledger.py`, `work/<job_id>/edl.json`).

---

## 1. Executive Summary: The "Demo Facade"

The Edit step (Step 3) in LionReel Studio was functioning as an interactive mock/demo facade rather than an authentic production editor. While users could manipulate trim sliders, click color preset chips, choose speed multipliers, and toggle safe-zone overlays, **none of these adjustments were wired to the final render pipeline (`lion_automate_v97.py`)**.

### Primary Findings:
1. **Disconnected Render Engine:** `lion_automate_v97.py` does not reference or read `edl.json`. When rendering a job, it independently samples and evaluates clips from raw cache files, rendering its own unedited choices regardless of what the user trimmed or selected on Step 3.
2. **CSS-Only Visual Handlers:** Color enhancement presets merely applied CSS `filter` strings (`contrast(...) saturate(...)`) directly to the HTML5 video element. Speed buttons changed HTML5 `playbackRate`. Neither modified nor persisted to the job EDL.
3. **Dual Separate Rails Bug:** The In/Out trim controls were two separate `<input type="range">` elements lacking unified dual-slider CSS. They rendered on two separate vertical rails, allowing the End thumb to physically sit to the left of the Start thumb with an absurd 1.0s window.
4. **Preview Player Shows Blurry Floor:** The preview player loaded raw 16:9 source video with CSS `object-fit: cover`. Because `object-fit: cover` naively centers horizontal video symmetrically into 9:16, the subject cat (which was framed off-center by the smart-crop algorithm) was cropped out, displaying empty background/wooden floor.
5. **Hardcoded Mock Fallbacks:** In `app.js`, `state.sources` contained static mock JSON with hardcoded strings (`"Cats Will Make You Laugh Your Head Off (Pure Chaos)"`, `"TigerPaws"`, `"97% SCORE"`).

---

## 2. Comprehensive Control & Value Audit Table

| # | Control / Value Name | What It Should Do | Where Value Originates | What Happens on Click / Interaction | Reaches Backend? | Used in Final Render? | Verdict | Source File & Line |
|:---:|:---|:---|:---|:---|:---:|:---:|:---:|:---|
| **1** | **Clip Title** | Displays real title of active clip from source metadata/ledger | Hardcoded in `app.js` (`cat_03.title`) | None (static text) | No | No | **DEMO** | `gui/app.js`: L183, L1688; `gui/index.html`: L1343 |
| **2** | **Uploader / Channel** | Displays real creator name and attribution from CC registry | Hardcoded in `app.js` (`cat_03.channel = "TigerPaws"`) | None (static text) | No | No | **DEMO** | `gui/app.js`: L184, L1692; `gui/index.html`: L1344 |
| **3** | **Resolution** | Displays real video stream resolution from `ffprobe` (e.g. 1080x1920) | Hardcoded in `app.js` (`"1080p"`) | None (static text) | No | No | **DEMO** | `gui/app.js`: L186, L1692; `gui/index.html`: L1344 |
| **4** | **Quality Score Badge** | Displays measured composite score (framing, sharpness, funny) with tooltip | Hardcoded initial HTML (`97% SCORE`) & `app.js` (`qualityScore: 97`) | None (static badge) | No | No | **DEMO** | `gui/index.html`: L1346; `gui/app.js`: L188, L1693 |
| **5** | **Trim Start Slider** | Adjusts in-point of clip; keeps Start < End (min 1.0s); seeks preview live | Initialized to `0.0s` or `clip.trimStart`; bounds 0 to 30 | Changes input value; updates `#val-trim-start`; seeks video player to start time; calls debounced framing check | Partially (fires `/check_framing`, but does NOT autosave EDL) | No (`lion_automate_v97.py` ignores user trim) | **PARTLY** | `gui/index.html`: L1365; `gui/app.js`: L1510-1557 |
| **6** | **Trim End Slider** | Adjusts out-point of clip; keeps End > Start (min 1.0s); seeks preview live | Initialized to `5.5s` or `clip.trimEnd`; bounds 0 to 30 | Changes input value; updates `#val-trim-end`; seeks video player to end time; calls debounced framing check | Partially (fires `/check_framing`, but does NOT autosave EDL) | No (`lion_automate_v97.py` ignores user trim) | **PARTLY** | `gui/index.html`: L1366; `gui/app.js`: L1510-1557 |
| **7** | **Trim Start / End Labels** | Displays numerical values with 0.1s precision (`0.0s`, `5.5s`) | Synchronized from slider input values | None (read-only labels) | No | No | **WORKING (UI only)** | `gui/index.html`: L1356, L1358; `gui/app.js`: L1539, L1540 |
| **8** | **Nudge Buttons (-0.1s, +0.1s)** | Increments / decrements trim by 0.1s step | Increments current slider value by $\pm 0.1$ | Shifts slider value by 0.1s; calls `updateTrimWindow` | Partially (fires framing check, no EDL autosave) | No | **PARTLY** | `gui/index.html`: L1373-1380; `gui/app.js`: L4815-4847 |
| **9** | **Live Framing Status Badge** | Re-evaluates centering gate on adjusted trim window | Returned by `POST /api/jobs/<job_id>/edits/check_framing` | Shows "Framing: Checking...", updates to "Framing: XX% OK" or "Framing: XX% Low" | Yes (hits endpoint) | No (result not enforced on render) | **PARTLY** | `gui/index.html`: L1353; `gui/app.js`: L1464-1508; `web_server.py`: L1175-1195 |
| **10** | **Color Enhancement Master Toggle** | Turns color enhancement on/off for clip; disables presets when off | Checkbox state in HTML (`switch-color-grading-editor`) | Toggles `state.config.APPLY_COLOR_GRADING`; updates toast; does not disable presets in UI | Partially (POSTs to `/api/config`, but NOT per-clip EDL) | No (applies global CLAHE if toggle on, but ignores preset/strength) | **DEMO** | `gui/index.html`: L1392; `gui/app.js`: L4781-4809 |
| **11** | **Color Presets Palette** | Activates one color grade preset: Natural, Vivid Pop, Cinema, Warm Glow, Cool Mint, CLAHE Max | Active chip attribute `data-filter` in HTML | Adds `.active` class to chip; calls `applyColorFilter()`; applies CSS `filter` style to `<video>` | No (never calls API or saves to EDL) | No (`lion_automate_v97.py` does not apply preset) | **DEMO** | `gui/index.html`: L1396-1403; `gui/app.js`: L1856-1886 |
| **12** | **"Auto Color Grading (CLAHE) OFF" Line** | Redundant legacy duplicate of the master color grading toggle | Text label `#label-color-grading-status` | Text toggles "ACTIVE" / "OFF" | No | No | **DEMO** | `gui/index.html` (legacy L1246); `gui/app.js`: L4788-4791 |
| **13** | **Preset Strength Slider** | Sets intensity 0-100% (default 60%); interpolates between natural and preset | Range input `#slider-color-strength` (10-100%) | Updates `#val-color-strength`; updates CSS filter weights | No | No | **DEMO** | `gui/index.html`: L1408; `gui/app.js`: L1858-1885 |
| **14** | **Speed Multiplier Buttons** | Sets playback speed (0.75x, 1.0x, 1.25x, 1.5x) per clip | Attribute `data-speed` on buttons | Sets `player.playbackRate`; updates button text; sets `clip.speed` in memory | No (no EDL save) | No (`lion_automate_v97.py` does not run `setpts` / `atempo`) | **DEMO** | `gui/index.html`: L1415-1419; `gui/app.js`: L1618-1633, L1820-1827 |
| **15** | **Platform Safe-Zone Guide Toggle** | Renders 1080x1920 caption & UI safe area overlays for chosen platform | Checkbox `#switch-safezone` | Sets `#safe-zone-overlay` `display: block / none` | No | Not burned in (correct) | **PARTLY** | `gui/index.html`: L1430; `gui/app.js`: L1653-1660 |
| **16** | **Safe-Zone Platform Tabs** | Switches overlay guide geometry between TikTok, YouTube Shorts, Reels | Attribute `data-platform` on tab buttons | Switches CSS margin of overlay box (`60px 18px 90px 18px`) | No | No | **DEMO** | `gui/index.html`: L1434-1438; `gui/app.js`: L1635-1651 |
| **17** | **Preview Video Player** | Plays muted planned smart-crop proxy; loops in trim window; seeks live | HTML5 `<video id="editor-video-player">` | Play/pause on click; updates scrubber; loops to `trimStart` when reaching `trimEnd` | No | No | **DEMO** | `gui/index.html`: L1272; `gui/app.js`: L1286-1446, L1723-1767 |
| **18** | **Live Enhancement Tag** | Quick toggle comparing raw source vs enhanced preview | Clickable div `#btn-toggle-enhancement` | Toggles `player.style.filter` between CSS grade and `"none"` | No | No | **WORKING (preview only)** | `gui/index.html`: L1266; `gui/app.js`: L1830-1846 |
| **19** | **Timeline Clip Strip** | Strip of thumbnails showing all clips; reorder, select, remove, undo | Rendered dynamically into `#timeline-clips-track` | Click selects clip; click trash removes clip from `state.selectedClips` | Partially (undo history in JS, but changes not autosaved) | No | **PARTLY** | `gui/index.html`: L1332; `gui/app.js`: L1127-1184 |
| **20** | **Swap from Bank Modal** | Replaces active clip with next best verified clip from ledger | Hits `GET /api/clip-bank` | Opens modal; selects replacement; calls `POST /api/jobs/<job_id>/edits/replace_clip` | Yes (calls backend) | No (`lion_automate_v97.py` ignores replacement) | **PARTLY** | `gui/index.html`: L1444; `gui/app.js`: L1186-1276; `web_server.py`: L1197-1216 |
| **21** | **Save Edits Button** | Saves all edit decisions to `work/<job_id>/edl.json` | Button `#btn-editor-save-edl` | Calls `saveEdlToBackend()` (`PUT /api/jobs/<job_id>/edits`) | Yes | No (`lion_automate_v97.py` does not load EDL on render) | **PARTLY** | `gui/index.html`: L1448; `gui/app.js`: L1100-1118; `web_server.py`: L1156-1173 |
| **22** | **Step Navigation Buttons** | Navigates between Wizard Steps (1 -> 2 -> 3 -> 4 -> 5) | Header stepper `#workflow-stepper` & footer buttons | Switches active view; pauses video players; triggers `syncEditorFromState()` | No | No | **WORKING (Nav only)** | `gui/index.html`: L245-274, L1232-1248; `gui/app.js`: L490-550 |

---

## 3. Inventory of Fakes, Hardcoded Constants & Mock States

### A. Hardcoded Values & Identifiers
1. **Mock Candidate Item 3 (`cat_03`):**
   - File: `gui/app.js`, Lines 182–192:
   ```javascript
   {
       id: "cat_03",
       title: "Cats Will Make You Laugh Your Head Off (Pure Chaos)",
       channel: "TigerPaws",
       duration: 42,
       resolution: "1080p",
       views: "30.1M",
       qualityScore: 97,
       thumbnail: "https://images.unsplash.com/photo-1543852786-1cf6624b9987?w=640&q=80",
       videoUrl: "https://www.youtube.com/watch?v=hY7m5jjJ9mM",
       category: "cat"
   }
   ```
   - **Flaw:** When Step 3 is entered, if no backend EDL is loaded, `state.selectedClips` defaults to `state.sources.slice(0, 4)`. Selecting the 3rd clip displays "Cats Will Make You Laugh Your Head Off (Pure Chaos)", "TigerPaws", "1080p", and "97% SCORE".
2. **Hardcoded HTML Badges & Inputs:**
   - `gui/index.html`, Line 1346: `<span class="badge badge-emerald" id="inspector-quality-score">97% SCORE</span>`
   - `gui/index.html`, Line 1365: `<input type="range" id="slider-trim-start" ... value="0">`
   - `gui/index.html`, Line 1366: `<input type="range" id="slider-trim-end" ... value="5.5">`
   - `gui/index.html`, Line 1272: `<video ... src="https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4">`
3. **Hardcoded Fallback Durations:**
   - In multiple locations across `gui/app.js` (L1137, L1211, L1481, L1569, L1711), clip durations fall back to `5.5s` when undefined, producing hardcoded 5.5s/11.0s/16.5s calculations.
4. **Hardcoded Unsplash Image URLs:**
   - Fallback thumbnail `https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=640&q=80` is used across timeline cards and video posters instead of actual extracted poster frames from the source video.

### B. Handlers That Only Manipulate CSS / DOM
1. **`applyColorFilter()` (`gui/app.js`, Lines 1856–1886):**
   - Applies `player.style.filter = "contrast(...) saturate(...) brightness(...)"`.
   - Never communicates with FFmpeg or saves color presets to `edl.json`.
2. **Speed Multiplier Click Handler (`gui/app.js`, Lines 1819–1828):**
   - Only updates `player.playbackRate = newSpeed;`.
   - Never saves to backend or affects FFmpeg audio/video filters.
3. **Safe Zone Overlay (`gui/app.js`, Lines 1635–1660):**
   - Modifies CSS `margin` on a dashed `div`. Not tied to actual video dimensions.

### C. Disconnection from Final Render Pipeline
- **Root Cause:** In `lion_automate_v97.py`, `render_one_video()` executes Stage 1 (`collect_candidates`) and Stage 5 (`predict_framing`) entirely from scratch, reading `config.json` and raw cache files. It completely ignores `work/<job_id>/edl.json`.
- **Consequence:** Even if the user clicks "Save Edits", the final render builds an entirely different video ignoring user trims, speeds, colors, and clip selections.

### D. State Lost on Page Refresh
- When the user refreshes the browser on Step 3:
  1. `state.selectedClips` is reset to `[]`.
  2. `state.currentJobId` is lost (resets to null or default).
  3. `loadEdlForEditor()` queries `/api/jobs/active_draft/edits`, fails or finds an unassociated EDL, and reverts back to the static `state.sources` mock array with `TigerPaws`.

---

## 4. Deep-Dive: Preview Player Issues & Floor Framing

### Why Does the Frame Show a Blurry Wooden Floor?
1. **Raw Source Sizing vs. Crop Plan:**
   - In `gui/index.html` (L1264) and `gui/style.css` (L2413):
   ```css
   .vertical-video-stage video {
       width: 100%;
       height: 100%;
       object-fit: cover;
   }
   ```
   - The video element plays the raw horizontal ($1920 \times 1080$) source video.
   - CSS `object-fit: cover` within a $9:16$ aspect container naively scales the video to fill height ($1920\text{px}$) and centers it horizontally, clipping 41.7% off the left and 41.7% off the right symmetrically.
2. **Subject Off-Center in Source Footage:**
   - In source footage (e.g. `cache_ByH9LuSILxU.mp4`), cats rarely sit at the exact horizontal center ($X = 960\text{px}$). They are walking on the carpet, stalking toys on the left, or near the bottom corner.
   - The backend's `AutoReframeEngine` calculates a crop box offset (e.g. $X = 350\text{px}$ to $957\text{px}$).
   - Because the frontend preview player ignores the crop plan and uses naive symmetrical CSS centering, the cat is cropped out, and the viewer sees only the center of the frame: **the blurry wooden floor**.
3. **Empty Margin & Black Container:**
   - The `.video-player-container` (L2389) has `display: flex; align-items: center; justify-content: center; background: var(--media-surface);`.
   - The inner `.vertical-video-stage` has `height: 94%; aspect-ratio: 9/16;`.
   - This creates an outer black/dark container with letterboxed side margins around the video stage.
   - The safe zone overlay was positioned inside the container rather than matching the video's actual rendered pixels.

---

## 5. Layout & UI Defects Deep-Dive

### A. The Dual Separate Slider Rails Bug
- **Symptoms:** Trim Start is at 4.5s on Rail 1; Trim End is at 5.5s on Rail 2. The End thumb can be placed to the left of the Start thumb.
- **Root Cause:**
  - `gui/index.html` (L1362-1367) contains two standard `<input type="range">` elements inside a wrapper `.dual-range-slider-wrap`.
  - In `gui/style.css`, there are **zero CSS rules** for `.dual-range-slider-wrap`, `.dual-range-track`, or `.dual-range-highlight`.
  - The browser renders them as two regular block-level range inputs stacked vertically. They are physically two separate slider rails.
  - Because each slider operates on its own track, the thumbs do not collide or constrain one another.

### B. Empty Area at the Bottom of the Inspector Panel
- **Symptoms:** A vast empty area appears below the safe zone toggle.
- **Root Cause:**
  - `gui/style.css` L2374: `.editor-layout { height: calc(100vh - var(--header-height) - 48px); }`.
  - The inspector panel is forced to fill the entire height of the screen (typically 900–1080px).
  - The controls only occupy ~480px.
  - In `gui/index.html` L1442, the action button container has `margin-top: auto`, pushing the buttons down and leaving a massive empty void in the middle/bottom of the card.

### C. "New Compilation" Button Cutoff at 860px and 390px
- **Symptoms:** The primary CTA `#btn-header-new` ("+ New Compilation") is clipped off at the right edge of the screen.
- **Root Cause:**
  - In `.app-header` (L881), `.header-left` (logo + title + subtitle + workspace selector = ~450px), `.workflow-stepper` (5 steps with full text labels = ~460px), and `.header-right` (theme toggle + shortcut icon + status badge + New Compilation button = ~320px) require at least $1230\text{px}$ of horizontal width.
  - At viewports $\le 1200\text{px}$, there are no media queries to hide `.brand-subtitle`, collapse `.workspace-selector`, or condense `.workflow-stepper` labels to numbers/icons.
  - The header overflows horizontally, pushing `.header-right` and `#btn-header-new` past the right edge of the viewport.

---

## 6. Implementation Action Plan (Phases 2 – 10)

1. **Phase 2 (Data Model):** Implement strict versioned EDL endpoints (`GET /api/jobs/<job_id>/edits` and `PUT /api/jobs/<job_id>/edits`), linking directly to `work/<job_id>/edl.json`.
2. **Phase 3 (Clip Strip & Preview):** Render real poster frames, output lengths, and smart-crop proxies that follow the planned crop trajectory. Fix panel height and header responsive collapse.
3. **Phase 4 (Unified Trim Slider):** Build a true dual-thumb single-rail slider with selected highlight, 0.1s numeric steppers, waveform background, and debounced framing gate checks.
4. **Phase 5 (Color Enhancement):** Create `config/color_presets.json` with real FFmpeg filter chains (Natural, Vivid Pop, Cinema, Warm Glow, Cool Mint, Auto contrast CLAHE). Connect strength slider and preview proxies.
5. **Phase 6 (Speed Multiplier):** Implement segmented speed control (0.75x, 1.0x, 1.25x, 1.5x) with active state; wire to FFmpeg `setpts` and `atempo`.
6. **Phase 7 (Safe-Zone Overlay):** Load accurate 1080x1920 safe zones from `config/safe_zones.json` scaled to the video element.
7. **Phase 8 (Clip Score & Attribution):** Replace "97% SCORE" with real analysis scores and show verified CC creator attributions.
8. **Phase 9 (Final Render Pipeline):** Modify `lion_automate_v97.py` to read the job EDL and render all user trims, speeds, and color grades in a single pass.
9. **Phase 10 (Playwright & FFmpeg Verification):** Execute end-to-end Playwright tests with `channel="chrome"` and verify rendered outputs with `ffprobe`.
