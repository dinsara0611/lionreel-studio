# LionReel Studio — UI Function Matrix & Test Verification

**Environment**: Antigravity Local Dev Server (`web_server.py`)  
**Dashboard URL**: `http://localhost:8000/`  
**Test Date**: October 4, 2026  
**Pipeline Engine**: `lion_automate_v97.py` (V97 Master Suite)  
**QA Engine**: `qa_check.py` with YOLOX Pet Tracking + EBU R128 + Laplacian Variance  

---

## 1. Comprehensive Function Verification Matrix

| # | Control / Action | Expected Result | Actual Result | Status | Verification Method & Notes |
|---|---|---|---|:---:|---|
| **1** | **Animal Mode Toggles**<br>*(Cats / Dogs / Duo)* | Selects active subject category, updates `config.json` (`ANIMAL_MODE` / `VIDEO_MODE`), switches title packs, and updates clip ledger filter. | Selecting "Cats", "Dogs", or "Duo" updates card highlight, writes payload to `/api/config`, and routes ledger reservation query to appropriate animal classifier. | **PASS** | Verified via UI card click, state inspection, and `/api/config` persistence. |
| **2** | **Video Type Selector**<br>*(Shorts vs. Compilation)* | Shorts sets target to 15–35s (3–6 clips). Compilation sets target to 45–90s (9–14 clips) with mapping/credits export. | Radio toggle updates wizard configuration, adjusts clip count slider range, and sets `VIDEO_TYPE` parameter in pipeline. | **PASS** | Tested in wizard step 1. Verified duration targets in `lion_automate_v97.py`. |
| **3** | **Language Toggle**<br>*(English / Sinhala)* | Toggles caption typography: Montserrat bold outline for English; Noto Sans Sinhala with unicode shaping for Sinhala. | Setting language to `si` loads `NotoSansSinhala.ttf` with Sinhala comedy captions; setting `en` loads `Montserrat.ttf`. | **PASS** | Both font paths verified in `assets/fonts/`. Unicode text rendering confirmed safe from cut boundaries. |
| **4** | **Clip Count / Duration Target** | Allows user to configure target clips (3–14) or target duration. | Step 1 and Step 3 sliders update numeric badges and persist values to config state. | **PASS** | Values properly received and mapped to `target_clips_count`. |
| **5** | **Start / Generate Button** | Initiates pipeline run (`/api/start`), updates system status to `RUNNING`, switches to Stepper 4 (Render), and streams live logs. | Button click posts config, spawns `lion_automate_v97.py` via virtualenv Python, clears error states, and polls `/api/logs` every 1.5s. | **PASS** | Verified live execution, process PID tracking, and log streaming in render terminal. |
| **6** | **Reset / Cancel Button** | Gracefully terminates active generation (`/api/stop`), releases reserved clips, and clears partial run artifacts. | Clicking Cancel triggers `taskkill /F /T` on child process, posts `/api/stop`, calls `ledger.release_reservation()`, and resets UI state to idle. | **PASS** | Process termination verified; clip reservations in ledger successfully rolled back. |
| **7** | **Finished Video Gallery** | Displays all exported videos with dynamic thumbnails, metadata, resolution badges (9:16 / 16:9), and QA status. | Gallery grid populates from `/api/finished`. Clicking any card opens embedded video player modal with full controls. | **PASS** | Tested across rendered library. Clean titles displayed with no tag spam. |
| **8** | **QA Details Modal / View** | Displays 8-point automated quality audit: pet centering %, EBU R128 LUFS/TP, Laplacian sharpness, defect count, and 12-frame contact sheet. | Clicking "QA Report" loads `{short_id}_qa_report.json` and embeds `{short_id}_contact_sheet.png` with green pass badges. | **PASS** | Verified with `lionreel_cat_20261004_4152` QA report (100% checks green). |
| **9** | **Clip Ledger & Pool Panel** | Displays real-time database health from `data/clip_ledger.db`: total clips, pool cycle, clips used in cycle, usage %, and low-pool alert. | Panel displays emerald progress bar, cycle badge ("CYCLE 1"), usage counters, and automated warning banner when pool < 15%. | **PASS** | Wired to `/api/pool?animal=cat`. Dynamic reload verified on short completion. |
| **10** | **Download / Export Action** | Downloads master .mp4 video file, JSON mapping (`mapping.json`), licensing credits (`credits.json`), and clean title metadata. | Download buttons trigger browser file download from `/finished/{filename}` with correct MIME headers (`video/mp4`, `application/json`). | **PASS** | Tested file download endpoints. Verified zero tags/descriptions in metadata. |
| **11** | **Settings / Config Persistence** | Saves user preferences into `config.json` and reloads them seamlessly upon page refresh or server restart. | Settings modal edits persist to `config.json` via `/api/config`. Values reload on page load without default overwrite. | **PASS** | Verified round-trip config save and reload in local storage / server. |
| **12** | **Responsive Layout**<br>*(1920x1080 & 390x844)* | Centered viewport (`--max-content-width: 1140px; margin-inline: auto;`), 3 equal cards on desktop, 1 card on mobile, centered header/footer. | Page centered with balanced margins on desktop. Grid stacks to 1 column on mobile (390px) without horizontal scrolling. | **PASS** | Verified via headless Chrome screenshots at 1440x900 and 390x844. Zero overflow. |

---

## 2. Key Architecture & Visual Verifications

1. **Horizontal Centering**:
   - `.app-viewport` set to `max-width: 1140px; margin: 0 auto; width: 100%;`
   - `.wizard-container` centered with equal left/right margins.
   - `.collection-cards-grid` uses `grid-template-columns: repeat(3, minmax(0, 1fr))` on desktop and `1fr` on mobile (`@media (max-width: 768px)`).
   - Wizard action bar (`.wizard-actions`) centered via `justify-content: center; margin: 0 auto;`.

2. **Clip Ledger Visual Feedback**:
   - Real-time usage bar with emerald gradient (`#059669` to `#10b981`).
   - Dynamic cycle indicator badge (`CYCLE 1`, `CYCLE 2`).
   - Threshold warning badge (`LOW POOL WARNING`) triggers when available clips dip below 15%.
