# LionReel — Antigravity Master Prompt V2 (Centering, Clip Ledger, One-to-One Dashboard, Export)

Copy everything below the line into Antigravity. Open the LionReel project folder first and make sure the dashboard is running at http://localhost:8000.

---

## ROLE

You are a senior Python / FFmpeg / computer-vision / frontend engineer and QA lead. You are fixing my **LionReel / LionReel Studio** project. Work in this order: **AUDIT → FIX → TEST (real browser + real renders) → REPORT**. Read the whole project first. Do not guess: open the running app, click every control, render real videos, and measure the results. Create a new clean version (`V96`, or `V97` if V96 exists) and keep older versions untouched.

## WHAT I MEASURED ON MY LATEST OUTPUT (`lion_master_cat_1791107091.mp4`)

These are real defects, found by analyzing the file. Reproduce every one of them first, then fix them.

| # | Defect | Evidence |
|---|---|---|
| 1 | **The pet is not centered, and in some clips it is not in the frame at all.** | Clip 1 (0–4.8 s): empty wall and blanket, the cat is only a sliver at the bottom edge. Clip 4 (9.3–11.9 s): the cat sits in the bottom-left corner under an empty ceiling. Clip 5 (12.9–16.4 s): the cat is cut off, the frame shows a man's head and a blurry body. The crop is not following the pet. |
| 2 | **The source footage already has other people's burned-in text and logos**, and the crop cuts it in half. | Clip 4 shows a chopped caption ("think they can't / and us ??") and the same text is partly hidden at the frame edge. |
| 3 | **My own captions land on the wrong place and overlap other text and the pet.** | "Mission failed successfully" sits in the middle of an empty blanket. "POV: You heard a food bag open" overlaps the burned-in text and the cat. The POV caption also runs across a cut (starts in one clip, ends in the next). |
| 4 | **Clips look soft and blurry even at 8 Mbps.** | Output bitrate is 8.1 Mbps, but the source is low-bitrate and the crop zooms in and upscales it. Bitrate cannot fix upscaled blur. Clip 5 is also heavy motion blur on a half-cropped subject. |
| 5 | **Audio is too hot.** | Integrated loudness -13.2 LUFS, true peak 0.0 dBFS (clipping risk). Target is -14 LUFS and at most -1.0 dBTP. |
| 6 | **The video is only 16.4 s with 5 clips** and the cuts are not placed at the end of the funny moments. | Scene cuts at 4.8 s, 8.8 s, 10.6 s, 12.9 s. |
| 7 | **Clips get reused.** When I make one short and then another, the same clip shows up again in the second short. | Reported by me. Find the code path that picks clips and confirm. |
| 8 | **The dashboard layout is off-center.** | Step 1 screen (animal selection): the three cards sit on the left (about x = 115–1015 of a 1396 px wide window), the right side is empty, and the page heading is cut off at the top. |

Already fine, keep as is: 1080x1920, 30 fps CFR, H.264 High yuv420p BT.709, AAC 48 kHz stereo, no black frames, no frozen frames.

## NON-NEGOTIABLE RULES (do not change or weaken)

1. **Legal sources only:** my own footage, CC-licensed YouTube (credit saved), Pexels, Pixabay. Keep the license/credit check and write `credits.json` next to every output.
2. **Reference-only files are never footage.** `C:\Users\dinsa\Videos\4K Video Downloader+\Funny Cats.mp4` is a quality benchmark for measuring pacing and sharpness only. Put it in `reference/` and create `config/blocked_sources.json` containing its filename and a perceptual fingerprint (phash of 10 evenly spaced frames + audio fingerprint). The downloader and the clip extractor must **refuse to ingest anything that matches the blocklist**, and also refuse any file placed in `reference/`. My latest output contains scenes from that benchmark (confirmed by feature matching: the sphynx clip and the "think they can't understand us" clip), which is exactly the bug. Find how it got into the source pool and close that path.
3. **No watermark/logo removal** from other people's content, no re-uploading of other creators' compilations.
4. **Upload stage: title only. No tags, no description.**

## FIX 1 — PET-CENTERED 9:16 REFRAMING (main problem)

Replace the current crop logic with a real subject-tracking reframer. A video must never be center-cropped blindly.

1. **Detect and track the pet** on every sampled frame (every 2nd or 3rd frame is enough, interpolate between): YOLO (`ultralytics`, `yolov8s` or newer, classes cat and dog; for the "Cats & Dogs Duo" mode track both and frame the group), plus a tracker (ByteTrack or the built-in tracker). If several pets are visible, follow the one with the largest box and most motion, and keep it consistent through the clip (no jumping between animals).
2. **Compute the crop window per frame**:
   - Target: the pet's box center at **x = 50%** of the frame and **y = 42–52%** (slightly above the middle, because the bottom UI covers the lower part).
   - Target pet size: box height **35–65%** of frame height. Zoom in only if the pet is smaller than 30%; zoom out toward the full frame if it is larger than 70%.
   - **Maximum zoom 1.35x.** If a source is already 9:16, start from the full frame (zoom 1.0) and only move/zoom as needed. Never upscale beyond 1.25x of the original pixels.
   - Smooth the path with a One-Euro filter or Kalman filter, then limit speed (max pan about 12% of frame width per second) so the camera movement looks natural. No jitter, no snapping.
   - If the pet is cut off at the source edge and the crop cannot keep it fully visible, use a **blurred-background fit** (scaled clip in the center over a blurred copy of itself) instead of cutting the pet.
3. **No pet = no clip.** If the pet is not detected in at least **85%** of the sampled frames of a clip, reject it (`NO_PET`). Remove the fallback that centers or guesses a crop. Also reject clips where the pet box is smaller than 10% of the frame height for most of the clip.
4. **Verify after cropping (second gate).** Run the detector again on 12 frames of the *cropped* clip. Pass only if in at least 90% of the frames the pet box center is inside x 35–65% and y 30–65%, and the box is fully inside the frame (or deliberately blur-fit). Otherwise re-crop once with a stricter setting, then reject (`BAD_CENTERING`) and log it.
5. **Handle burned-in text and logos in the source:** detect text overlays (OCR such as PaddleOCR or EasyOCR on 6 frames per clip, or an EAST text detector). Do not accept footage with large burned-in captions, platform watermarks, or channel logos (`BURNED_IN_TEXT`). Never try to blur or remove someone else's watermark. Pick clean sources instead.
6. Reject clips with letterbox/pillarbox bars (`cropdetect`), split-screen, and picture-in-picture.

## FIX 2 — CLIP LEDGER: NO REPEATED CLIPS BETWEEN SHORTS

Build a persistent **clip ledger** (SQLite file `data/clip_ledger.db`). Every candidate clip gets one row:

`clip_id, source_id, source_url_or_path, license, start_s, end_s, fingerprint (phash of 5 frames + audio fingerprint), quality_score, funny_score, times_used, last_used_short_id, pool_cycle`

Rules:
1. **Within one short:** no clip appears twice, and no two near-duplicates (phash Hamming distance below a configurable threshold, or CLIP embedding cosine above 0.92) appear in the same short.
2. **Between shorts:** a clip that was used in any earlier short is **locked** and cannot be chosen again while there are unused eligible clips in the pool. This applies across runs too (the ledger is persistent), and across different source videos (use the fingerprint, so the same footage downloaded twice is still caught).
3. **Repeat only after the pool is used up:** when 100% of the eligible clips have been used once, start `pool_cycle + 1`. In the new cycle use the least-used and highest-scoring clips first, and make the repeat look different: different order, a different trim window (at least 1.5 s offset when the clip is long enough), a new caption, and never the same pair of clips back to back as before. Log `REPEAT_CYCLE_STARTED` and show it in the dashboard.
4. The dashboard must show **pool usage as a percentage** ("Clip pool: 37 of 52 used, 71%") and warn me when the pool is below 15% unused so I can fetch more sources.
5. If a short is rejected by QA after it was assembled, **release** its clips back to the pool (so a failed render does not burn good clips). Only mark clips as used when the short passes QA and is saved.

## FIX 3 — LONG VIDEO ↔ SHORTS, ONE TO ONE

Support two modes and make both work end to end with a clear mapping file:

- **Compilation mode (long video):** 45–90 s, 9–14 clips, one long video from many clips.
- **Shorts mode:** from the same pool, produce N separate shorts of 15–35 s, each with 3–6 clips. Shorts never share clips (see Fix 2).
- When I give **one long source video** (own footage or CC), split it by scene/action detection into segments, score them, and make shorts from **non-overlapping segments**. Write `mapping.json` for every output: `output_file → [clip_id, source_id, start_s, end_s, caption_text, crop_summary]`. One output must map exactly to its clips, and one clip must map to exactly one output per cycle.
- Cut at the end of the funny moment (audio peak or motion burst plus 0.3–0.6 s), not in the middle of the action. First clip of every video must contain the strongest moment and have motion plus the pet's face or action in the first 2 seconds.

## FIX 4 — CAPTIONS

- A caption belongs to **one clip**: it starts after the cut, ends before the next cut, never spans a cut.
- Placement: compute a free-space map per clip (where the pet box, faces and any text are not), choose the best position inside the safe zone, which is at least 150 px from the left/right edges, nothing in the top 220 px and nothing below y = 1450 (platform UI). Default to the lower third *above* the pet, or above the pet if the pet is low. Never place text in the middle of the screen over empty background just because it is the center, and never over the pet's face.
- Max 8 words, 1–2 lines, bold white sans (Montserrat ExtraBold or Inter Black), dark outline 4–6 px + soft shadow, fade-in 0.1 s. Captions on about half of the clips, not all. Original jokes only.
- Sinhala mode: Noto Sans Sinhala Bold, same layout, render check on a test frame.

## FIX 5 — SHARPNESS AND EXPORT

- Reject sources with height below 1080 after crop, or that would need more than 1.25x upscaling. Prefer 1440p or higher sources and downscale from them (that is where real sharpness comes from).
- **Render the final video once** from the original source pixels (single crop + scale + caption pass). Intermediate files must be near-lossless (`libx264 -crf 12` or FFV1/ProRes), never re-encoded at CRF 20+ several times.
- Scaling: `scale=1080:1920:flags=lanczos`, then a mild `unsharp=5:5:0.35` after the downscale only. No heavy filters, grade only a small contrast curve and +5–10% saturation.
- Final encode: `libx264 -preset slow -profile:v high -level 4.2 -crf 17 -maxrate 14M -bufsize 28M -pix_fmt yuv420p -r 30 -g 60 -bf 2 -colorspace bt709 -color_primaries bt709 -color_trc bt709 -movflags +faststart`, AAC-LC 192 kbps, 48 kHz stereo.
- Audio: two-pass `loudnorm` to **I = -14 LUFS, TP = -1.0, LRA = 11**, then `alimiter`. Music must be royalty-free, ducked 12 dB under pet sounds, and it must never be louder than the pet sound at the funny moment.
- Motion blur and shake: reject clips whose sharpness (Laplacian variance on a 540x960 gray frame) is below 150, or where more than 20% of sampled frames are below 80, or with strong shake from optical flow.

## FIX 6 — DASHBOARD (http://localhost:8000): EVERY FUNCTION WORKS ONE TO ONE

First, **open http://localhost:8000 in a real browser** (Playwright, headed, 1440x900 and 390x844 mobile) and take screenshots of every step. Then:

1. **Layout:** center the whole app horizontally (`max-width` about 1100–1200 px, `margin-inline: auto`), the heading must not be cut off at the top (check `scrollIntoView`/padding/`overflow`), consistent spacing, and it must work at 390 px width. The three animal cards (Feline, Canine, Cats & Dogs Duo) and the "Continue to Sources" button must be centered and aligned on the same grid.
2. **Flow audit:** list every step and button (animal selection → sources → settings → generate → progress → review → export/upload) and build a table `UI_FUNCTION_MATRIX.md`: control, expected result, backend endpoint, actual result, pass/fail. Then fix every failure. Each button must do exactly one thing, show a loading state, disable itself while running (no double-click duplicates), and show a clear error if it fails.
3. **Animal mode is real, not decoration.** Feline mode must only accept cat clips, Canine only dogs, Duo requires both in the same short (or both types in the pool with a balanced mix). Verify with the detector, not with the title or search text. The selection from step 1 must reach the backend and be saved in the job config.
4. **Job queue and progress:** one job per short, run **sequentially**. Short N+1 starts only after short N reached **100% and passed QA**. Show per-short progress (download → analyze → select clips → crop → captions → audio → render → QA) and overall progress, both ending exactly at 100%, never stuck at 99% or jumping backwards, and show the live log. Support cancel and resume, and survive a page refresh (state comes from the backend, not from the browser).
5. **Review screen:** for each finished short show the video player, the contact sheet, the QA report, `mapping.json` and the clips used, with buttons: Approve, Regenerate (uses new clips from the ledger), Delete (releases the clips back to the pool), Export. "Export" must save the final MP4 to `output/` with a clean file name (`lionreel_<animal>_<YYYYMMDD>_<NN>.mp4`) and show the real file path and size.
6. **Repeat/pool panel:** show pool usage %, used/unused counts, current cycle number, and a button to add more sources.
7. No console errors, no failed network requests (check the browser console and the network tab in the tests).

## FIX 7 — AUTOMATED QA THAT BLOCKS BAD OUTPUT

`qa_check.py` runs on every finished video and blocks save/upload on any failure. It outputs `qa_report.json` and `contact_sheet.png` (12 frames in a grid, with the detected pet box drawn on each frame).

Checks:
1. `ffprobe`: 1080x1920, 30 fps CFR, H.264 High, yuv420p, AAC, duration inside the chosen mode's range, video bitrate at least 6 Mbps.
2. `blackdetect` + `freezedetect`: zero hits.
3. Loudness -15.5 to -12.5 LUFS and true peak at most -1.0 dBTP.
4. **Centering:** pet detected in at least 90% of 24 sampled frames; box center inside x 35–65%, y 30–65% in at least 90% of those frames; box not cut by the frame edge.
5. **Captions:** inside the safe zone, no overlap with the pet box or detected text, none crossing a cut.
6. **Burned-in text / watermark:** none detected in the final video except my own captions and my own small logo.
7. **Duplicates:** every clip in the video matches a unique ledger row, no near-duplicates inside the video, and no overlap with clips locked by earlier shorts (except in a declared repeat cycle).
8. **Sharpness:** each clip's median Laplacian variance at least 150.
9. **Source guard:** no clip fingerprint matches `blocked_sources.json`.

## HOW TO WORK AND WHAT TO DELIVER

1. **AUDIT:** write `AUDIT.md` with a pipeline diagram, the root cause of each of the 8 defects (point to file and line), and anything else you find (double re-encodes, crop fallbacks, caption timing bugs, progress-state bugs).
2. **FIX:** implement Fix 1–7 in the new version. All thresholds in `config/*.json`.
3. **TEST for real:**
   - Playwright end-to-end test of the dashboard at http://localhost:8000 through every step, with screenshots.
   - Render **at least 6 shorts in a row** in Feline mode from one pool, plus 1 compilation. Prove with the ledger that **no clip repeats** between the shorts, and then force the pool to run out to prove the repeat-cycle logic works (a repeated clip has a different trim, order and caption).
   - Render at least 1 Canine and 1 Duo video.
   - For every video, attach `qa_report.json` and `contact_sheet.png`.
4. **COMPARE:** analyze my old output `lion_master_cat_1791107091.mp4` and your new output with the same script, and print a before/after table: pet-centered frames %, caption collisions, burned-in text found, sharpness, loudness, true peak, bitrate, clip count, duplicate clips. The new output must be better on every row.
5. **REPORT:** `CHANGELOG.md` (what was wrong, what changed, how to run in one command) and the finished `UI_FUNCTION_MATRIX.md` with all rows passing.

Constraints: Windows 10/11 paths, Python 3.10+, FFmpeg in PATH, GPU optional (use `h264_nvenc -cq 17 -preset p7` only as an option, libx264 stays the default), graceful errors, resumable runs, one bad clip must never crash a batch (skip and log with a reason code).

---
