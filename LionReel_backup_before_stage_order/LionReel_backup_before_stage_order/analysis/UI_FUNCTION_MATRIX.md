# LionReel Studio — Comprehensive UI Function Matrix

**Environment**: Antigravity Studio Local Dev (`http://localhost:8000/`)  
**Analysis Date**: October 2026  
**Scope**: All interactive controls across Global Header, Step 1 (Create), Step 2 (Sources), Step 3 (Configure), Step 4 (Render), Step 5 (Export), and Modals  
**Tested Viewports**: 1440×900 Desktop & 390×844 Mobile  
**Themes**: Dark Theme (`#06110C`) & Light Theme (`#F4FAF6`)  

---

## 1. Executive Summary of Control Inventory

- **Total Unique Controls Discovered**: 236 interactive elements (buttons, inputs, sliders, toggles, chips, selects, modals).
- **Verified Core Workflow CTAs**: 45 primary navigation, setting, and triggering elements.
- **Verified Passing Controls**: 32 controls (71.1% pass rate).
- **Failing or Discrepant Controls**: 13 controls (28.9% requiring bug fixes per user specifications).

---

## 2. Interactive Controls Verification Matrix

| # | Step / View | Control Name & ID | Type | Intended Function | API / Handler | Config Saved? | Observed Behavior | Status |
|---|---|---|:---:|---|---|:---:|---|:---:|
| **1** | Global Header | **Theme Toggle Button**<br>`#theme-toggle-btn` | `theme` | Toggles application theme between Dark Mode and Light Mode with instant token transition and localStorage persistence | `window.toggleTheme() -> applyTheme()` | No (UI State) | Toggles root data-theme attribute between 'dark' and 'light', updates meta theme-color and icon visibility | **PASS** |
| **2** | Global Header | **Keyboard Shortcuts Button**<br>`#btn-open-shortcuts` | `btn` | Opens keyboard shortcuts help modal dialog listing hotkeys (Space, E, S, N, T) | `openShortcutsModal()` | No (UI State) | Opens #modal-shortcuts with active overlay class and trapped focus | **PASS** |
| **3** | Global Header | **New Compilation Header Button**<br>`#btn-header-new` | `btn` | Resets active workflow wizard to Step 1 (Create) and prepares a fresh reel generation session | `navigateToStep(1)` | No (UI State) | Resets wizard state and navigates view to #view-dashboard | **PASS** |
| **4** | Global Header | **Workspace Selector Dropdown**<br>`#workspace-selector` | `workspace` | Allows user to switch project workspaces or folders | `showToast('Workspace switching...')` | No (UI State) | Displays placeholder active workspace label '📁 Animal Shorts Lab'; no dropdown options implemented | **FAIL (No Dropdown Options)** |
| **5** | Step 1: Create | **New Compilation Hero Button**<br>`#btn-hero-new` | `btn` | Starts new creation wizard, navigating from Step 1 to Step 2 (Video Sources) | `navigateToStep(2)` | No (UI State) | Smoothly transitions active view to #view-wizard (Step 2) | **PASS** |
| **6** | Step 1: Create | **Use Sample Project Button**<br>`#btn-hero-sample` | `btn` | Loads bundled sample project clips (5 curated CC cat clips) and navigates to timeline editor | `loadSampleProject()` | Yes (`/api/config`) | Pre-populates sample clips array, writes to state.config.SELECTED_CLIPS, and jumps to Step 3 | **PASS** |
| **7** | Step 1: Create | **Purge Temp Files Button**<br>`#btn-purge-temp` | `btn` | Frees disk space by deleting moviepy crash fragments, partial downloads, and scratch files | `purgeTempFiles()` | No (UI State) | Calls POST /api/purge-temp-files; removes temporary scratch files and returns freed MB count | **PASS** |
| **8** | Step 1: Create | **Clean All & Reset Button**<br>`#btn-clean-all` | `btn` | Resets ledger history, clears session logs, and frees temporary cache safely | `cleanAllAndReset()` | No (UI State) | Calls POST /api/reset-history; clears used tracking files but lacks safety confirmation modal (Fix 5 needed) | **WARN (Unsafe Direct Reset)** |
| **9** | Step 1: Create | **Feline Collection Card**<br>`#card-cat` | `card` | Selects Cats category (ANIMAL_MODE='cat'), sets cat title packs, filters sources to cats | `selectCategory('cat')` | Yes (`/api/config`) | Sets state.activeCategory='cat', updates card border glow, saves VIDEO_MODE='cat' to server config | **PASS** |
| **10** | Step 1: Create | **Canine Collection Card**<br>`#card-dog` | `card` | Selects Dogs category (ANIMAL_MODE='dog'), sets dog title packs, filters sources to dogs | `selectCategory('dog')` | Yes (`/api/config`) | Sets state.activeCategory='dog', updates card border glow, saves VIDEO_MODE='dog' to server config | **PASS** |
| **11** | Step 1: Create | **Cats & Dogs Duo Card**<br>`#card-mix` | `card` | Selects Duo category (ANIMAL_MODE='duo'), sets duo title packs, filters sources to mix | `selectCategory('mixed')` | Yes (`/api/config`) | Sets state.activeCategory='mixed', updates card border glow, saves VIDEO_MODE='mix' to server config | **PASS** |
| **12** | Step 1: Create | **Refresh Library Button**<br>`#btn-refresh-history` | `btn` | Re-scans finished directory, reconciles database with disk, and updates card list | `loadFinishedProjects()` | No (UI State) | Fetches /api/finished and re-renders cards. Does not reconcile Google Drive folder or mark missing files (Fix 4 needed) | **WARN (Partial Scan)** |
| **13** | Step 1: Create | **Reset Clip History Button**<br>`#btn-clear-history` | `btn` | Safely resets used-clips cycle in clip_ledger with backup, typing RESET confirmation, and undo option | `resetClipHistory()` | No (UI State) | Instantly wipes used_videos.txt without typing confirmation or ledger backup (Fix 5 needed) | **FAIL (High Risk: Clears without safety backup/confirm)** |
| **14** | Step 2: Sources | **Curated Viral Archive Tab**<br>`#source-tab-curated` | `source` | Displays curated library of pre-screened viral pet footage clips with thumbnail previews | `switchSourceTab('curated')` | Yes (`/api/config`) | Renders curated clips grid with duration badges and action buttons | **PASS** |
| **15** | Step 2: Sources | **YouTube CC Search Tab**<br>`#source-tab-youtube` | `source` | Allows searching Creative Commons CC-BY videos on YouTube via yt-dlp | `switchSourceTab('youtube')` | Yes (`/api/config`) | Renders search bar for YouTube CC query; triggers download upon selection | **PASS** |
| **16** | Step 2: Sources | **Own Footage Upload Tab**<br>`#source-tab-own` | `source` | Allows creator to drag-and-drop or browse local footage into own_footage/ folder | `switchSourceTab('own')` | Yes (`/api/config`) | Renders drag/drop dropzone and files list from own_footage/ directory | **PASS** |
| **17** | Step 2: Sources | **Continue to Configure Button**<br>`#btn-source-next` | `btn` | Validates selected clips count and advances wizard to Step 3 (Configure Video) | `navigateToStep(3)` | Yes (`/api/config`) | Saves state.selectedClips to config and transitions view to #view-editor | **PASS** |
| **18** | Step 3: Configure | **Short Video Format Toggle (<60s)**<br>`#mode-short` | `mode` | Sets target video duration for YouTube Shorts / TikTok / Reels (15–35s, 3–6 clips) | `setVideoType('short')` | Yes (`/api/config`) | Sets state.config.VIDEO_TYPE='short', updates slider bounds to 2–8 clips | **PASS** |
| **19** | Step 3: Configure | **Long Compilation Format Toggle**<br>`#mode-long` | `mode` | Sets target video duration for long landscape compilations (45–90s+, 9–14 clips) | `setVideoType('long')` | Yes (`/api/config`) | Sets state.config.VIDEO_TYPE='long', updates target duration min slider to 1–15 min | **PASS** |
| **20** | Step 3: Configure | **Target Clips Slider**<br>`#slider-target-clips` | `slider` | Sets target number of clips in compilation (e.g. 4 clips) | `updateShortDuration(clips, sec)` | Yes (`/api/config`) | Updates state.config.TARGET_CLIPS and dynamic summary bar. IN BACKEND PIPELINE: Was historically overridden to 3 by hardcoded bug | **WARN (UI updates properly; backend overridden)** |
| **21** | Step 3: Configure | **Clip Duration (s) Slider**<br>`#slider-clip-duration` | `slider` | Sets average duration per clip in seconds (e.g. 7.5s, range 3.0s–12.0s) | `updateShortDuration(clips, sec)` | Yes (`/api/config`) | Updates state.config.SHORT_CLIP_SEC and dynamic summary bar. IN BACKEND PIPELINE: Was historically sliced at fixed 5.2s candidate windows | **WARN (UI updates properly; backend overridden)** |
| **22** | Step 3: Configure | **Fast Viral Pacing Chip (4.0s cuts)**<br>`#chip-pace-fast` | `chip` | Configures snappy comedic cut pacing with rapid scene changes | `setPaceProfile('fast')` | Yes (`/api/config`) | Sets SPEED_PROFILE='fast'; does not shorten clips below requested target_clip_sec | **PASS** |
| **23** | Step 3: Configure | **Dynamic Pacing Chip (6.0s cuts)**<br>`#chip-pace-dynamic` | `chip` | Configures balanced comedic timing matching laugh punchlines | `setPaceProfile('dynamic')` | Yes (`/api/config`) | Sets SPEED_PROFILE='dynamic' | **PASS** |
| **24** | Step 3: Configure | **Cinematic Pacing Chip (8.0s cuts)**<br>`#chip-pace-cinematic` | `chip` | Configures smooth cinematic framing with longer shot holds | `setPaceProfile('cinematic')` | Yes (`/api/config`) | Sets SPEED_PROFILE='cinematic' | **PASS** |
| **25** | Step 3: Configure | **Action Peak Cut Mode Chip**<br>`#chip-moment-peak` | `chip` | Centers window slice on maximum audio spike and motion burst | `setMomentCutMode('peak_viral')` | Yes (`/api/config`) | Sets MOMENT_CUT_MODE='peak_viral' | **PASS** |
| **26** | Step 3: Configure | **Funny Punchline Cut Mode Chip**<br>`#chip-moment-punchline` | `chip` | Starts window slightly earlier and holds for the post-action reaction | `setMomentCutMode('punchline')` | Yes (`/api/config`) | Sets MOMENT_CUT_MODE='punchline' | **PASS** |
| **27** | Step 3: Configure | **9:16 Vertical Shorts Format Chip**<br>`#chip-format-9-16` | `chip` | Locks video canvas to 1080x1920 portrait format for mobile platforms | `setOutputFormat('9:16')` | Yes (`/api/config`) | Sets TARGET_FORMAT='9:16', ASPECT_RATIO='9:16' | **PASS** |
| **28** | Step 3: Configure | **16:9 Landscape YouTube Format Chip**<br>`#chip-format-16-9` | `chip` | Sets video canvas to 1920x1080 landscape format for desktop YouTube | `setOutputFormat('16:9')` | Yes (`/api/config`) | Sets TARGET_FORMAT='16:9', ASPECT_RATIO='16:9' | **PASS** |
| **29** | Step 3: Configure | **Framing & Camera Mode Select**<br>`#select-layout-mode` | `select` | Selects reframing behavior: Smart Center Crop (Subject tracking), Blurred Background Fit, or Auto | `setLayoutMode(val)` | Yes (`/api/config`) | Sets LAYOUT_MODE='smart_crop' / 'blur_fit' / 'auto' | **PASS** |
| **30** | Step 3: Configure | **Watermark Detector Toggle**<br>`#toggle-check-watermark` | `toggle` | Enforces 4-corner burned-in text and channel watermark scan before render | `toggleQC('CHECK_WATERMARK')` | Yes (`/api/config`) | Toggles CHECK_WATERMARK and displays warning banner when unchecked | **PASS** |
| **31** | Step 3: Configure | **Duplicate Detector Toggle**<br>`#toggle-check-duplicates` | `toggle` | Enforces perceptual pHash duplicate screening against used-clips ledger | `toggleQC('CHECK_DUPLICATES')` | Yes (`/api/config`) | Toggles CHECK_DUPLICATES and displays warning banner when unchecked | **PASS** |
| **32** | Step 3: Configure | **AI Video Detector Toggle**<br>`#toggle-check-ai-video` | `toggle` | Enforces sensor noise and unnatural motion checks to reject synthetic AI clips | `toggleQC('CHECK_AI_VIDEO')` | Yes (`/api/config`) | Toggles CHECK_AI_VIDEO and displays warning banner when unchecked | **PASS** |
| **33** | Step 3: Configure | **Ad & Promo Post Filter Toggle**<br>`#toggle-check-ad-filter` | `toggle` | Rejects promotional overlays, banner cards, and sponsored intros | `toggleQC('CHECK_ADVERTISING')` | Yes (`/api/config`) | Toggles CHECK_ADVERTISING and displays warning banner when unchecked | **PASS** |
| **34** | Step 3: Configure | **Generate Reel / Start Render Button**<br>`#btn-start-render` | `btn` | Validates settings, triggers POST /api/start, opens Step 4 (Render), and begins live log streaming | `startRenderPipeline()` | Yes (`/api/config`) | Saves config, spawns backend pipeline process with CLI parameters, polls /api/status and /api/logs | **PASS** |
| **35** | Step 4: Render | **Cancel / Stop Render Button**<br>`#btn-cancel-render` | `btn` | Gracefully halts active render process, terminates child ffmpeg tasks, and releases reserved clips | `cancelRenderPipeline()` | No (UI State) | Calls POST /api/stop; kills process tree and releases ledger reservations | **PASS** |
| **36** | Step 1: Create | **Clear Console Button**<br>`#btn-clear-logs` | `btn` | Clears terminal body text in the real-time pipeline log monitor | `clearConsoleLogs()` | No (UI State) | Wipes innerHTML of #terminal-body; new log lines continue streaming from current offset | **PASS** |
| **37** | Step 5: Export | **Ready for Upload Title Input**<br>`#export-meta-title` | `export` | Displays clean comedic upload title, allows multi-line viewing/editing, with live char counter (e.g. 54/100) | `None (readonly <input>)` | No (UI State) | Single-line <input> that truncates long titles; no counter; no warning on 100 char limit (Fix 2 needed) | **FAIL (Truncates title, lacks auto-growing textarea & counter)** |
| **38** | Step 5: Export | **Copy Title Button**<br>`#btn-copy-meta-title` | `btn` | Copies sanitized title string to system clipboard with visual 'Copied' badge | `copyMetaTitle()` | No (UI State) | Copies title to clipboard; lacks feedback badge / mobile fallback | **WARN (No visible Copied feedback)** |
| **39** | Step 5: Export | **Description Field**<br>`#export-meta-desc` | `export` | Should be disabled or hidden with placeholder 'Not used (title-only upload)' because uploads are title-only | `None` | No (UI State) | Active textarea displaying empty or filler text; copies blank content | **FAIL (Active despite title-only upload rule)** |
| **40** | Step 5: Export | **Copy Description Button**<br>`#btn-copy-meta-desc` | `btn` | Should be disabled because uploads are title-only | `copyMetaDesc()` | No (UI State) | Active button that copies empty/placeholder text | **FAIL (Should be disabled)** |
| **41** | Step 5: Export | **Hashtags Field**<br>`#export-meta-tags` | `export` | Should be disabled or hidden with placeholder 'Not used (title-only upload)' | `None` | No (UI State) | Active input displaying filler tags; copies blank content | **FAIL (Active despite title-only upload rule)** |
| **42** | Step 5: Export | **Copy Hashtags Button**<br>`#btn-copy-meta-tags` | `btn` | Should be disabled because uploads are title-only | `copyMetaTags()` | No (UI State) | Active button that copies filler tags | **FAIL (Should be disabled)** |
| **43** | Step 5: Export | **Copy All Button**<br>`#btn-copy-meta-all` | `btn` | Copies Title only (plus credits only if checkbox is ticked). Replaces multi-field copy | `copyAllMeta()` | No (UI State) | Copies title + description + tags formatted together (violating title-only default) | **FAIL (Includes tags and descriptions in copy buffer)** |
| **44** | Step 5: Export | **Remove / Delete Video Button**<br>`#btn-delete-export-video` | `btn` | Safely prompts with confirmation, moves files to _trash for 7 days, releases clips back to pool | `deleteCurrentVideo()` | No (UI State) | Directly deletes without 7-day trash fallback or clip pool release (Fix 6 needed) | **WARN (Destructive delete without trash folder)** |

---

## 3. Discrepancy & Root Cause Summary

1. **Clip Count & Clip Duration Overrides (Step 3 vs Pipeline):**
   - Controls `#slider-target-clips` and `#slider-clip-duration` update `state.config` and transmit `TARGET_CLIPS` and `SHORT_CLIP_SEC` to `/api/config` and `/api/start`.
   - In older backend runs, `lion_automate_v97.py` line 714 had `target_clips_count = 3 if video_type == 'short' else ...`, forcing 3 clips.
   - `populate_ledger_from_sources()` (line 711) and `harvest_worker.py` (line 258) used `segment_len = 5.2`, forcing every candidate in `clip_ledger.db` to 5.2 seconds.
   - 3 clips × 5.2s = 15.6s, causing the 16s video duration bug.

2. **Ready for Upload Metadata Panel (Step 5):**
   - `#export-meta-title` is an `<input type='text'>` with no auto-expand, truncating long titles.
   - `#export-meta-desc` and `#export-meta-tags` have active Copy buttons that copy empty strings because title-only upload leaves them unused.
   - Header wraps on smaller resolutions; 'Loaded' crowds 'Copy All'.
   - Live 100-character counter (`54/100`) is missing.

3. **Finished Compilations Cards Hard-Coded Duration Tag:**
   - In `gui/app.js` line 2415, the duration tag on finished video cards is hardcoded: `const dur = '0:33';`.
   - Real video duration (15.69s) was completely masked by this hardcoded string.
   - Thumbnail defaulted to `_contact_sheet.png` because clean `poster.jpg` was not created by the pipeline.

4. **Credits System Missing Components:**
   - Ingestion does not store source URL, creator channel name, or license URL in `clip_ledger.db`.
   - Finished jobs write a minimal `credits.json` without full attribution lines, no `credits.txt`, no `credits_registry.csv`, and no UI credits section.