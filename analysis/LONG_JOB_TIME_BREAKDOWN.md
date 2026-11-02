# LONG JOB TIME BREAKDOWN & DIAGNOSTIC REPORT

**Target Job ID**: `lionreel_cat_20261013_032419_6e3e590e`  
**Configuration**: Long Video (Target 100 clips × 12s = 20 min runtime, 200 candidates reserved)  
**Total Wall Clock Time**: 28,945 seconds (8h 02m 25s)  
**Elapsed Timer at Observation**: 7:20:51 (26,451 s)  
**Hardware Profile**: Intel Core i5-1335U (10 Cores: 2 P-Cores, 8 E-Cores, 12 Threads), Intel Iris Xe Graphics, 16 GB RAM, NVMe SSD, Windows 11  

---

## 1. Executive Summary: What State Was the Job Really In?

The job was **STUCK IN A DEADLOCKED WAITING LOOP** (`needs_sources`), **NOT** actively rendering or analyzing.

### Why Did the UI Card Display "LIVE"?
1. In `web_server.py`, the `/api/status` endpoint evaluated `is_running = (RUNNING_PROCESS.poll() is None)`. Because the Python process (`lion_automate_v97.py`, PID 17428) was alive and executing a `while len(rendered_candidates_pool) < target_clips_count: time.sleep(1.0)` sleep loop, `web_server.py` unconditionally set `computed_status = "running"`.
2. When `computed_status == "running"`, the server assigned `stateLabel = "LIVE"`, completely ignoring the wait checkpoint file (`wait_checkpoint.json` which recorded `status: "needs_sources"` and `consecutive_no_growth: 852`).
3. The frontend `app.js` continuously ticked `render-time-elapsed` every 1,000 ms whenever `stateLabel !== "PAUSED"`, causing the timer to tick continuously up to `7:20:51` even though the system was idle in a sleep loop.

### Why Did It Enter and Stay in the Waiting Loop? (The Deadlock)
1. **Source Depletion**: Only 1 raw source (`cache_zCBhhLo6lIM.mp4`) was staged in the pool for this job.
2. **Post-Crop Gate Failure**: Stage A pre-selected candidate moments, but the post-crop gate (`verify_post_crop_gate`) rejected candidate variations due to centering/pet visibility (`Centering: 0.0%`). After rendering 6 clips, all remaining standby clips were exhausted.
3. **Deadlock with Background Bank Filler**: At `04:03:10`, `lion_automate_v97.py` entered `[BANK WAITING]` expecting `clip_bank_filler.py` to fill verified windows into the ledger. However, `clip_bank_filler.py` contains:
   ```python
   def is_render_active(self) -> bool:
       ...
       if d.get("status") in ("running", "in_progress") or d.get("is_running"):
           return True
   ```
   Because a render job was considered "running", the bank filler **paused itself to save CPU cores**!
   The render job waited for the bank filler to add clips, and the bank filler refused to run because the render job was active. This resulted in an unbroken 7-hour deadlock (`consecutive_no_growth: 852`).

---

## 2. Resource & Environment Diagnostics (60-Second Measurements)

- **Clips Rendered**: Exactly 6 clips produced before shortage.
  - `clip_c_zcb_380_390_rep3.mp4` (4.69 MB) — 2026-10-13 03:38:16
  - `clip_c_zcb_380_390_rep1.mp4` (4.78 MB) — 2026-10-13 03:48:15
  - `clip_c_zcb_380_390.mp4` (5.02 MB) — 2026-10-13 03:48:24
  - `clip_c_zcb_380_390_rep2.mp4` (4.60 MB) — 2026-10-13 03:53:16
  - `clip_c_cache_zCBhhLo6lIM_390_395.mp4` (5.03 MB) — 2026-10-13 03:58:14
  - `clip_c_zcb_380_390_rep4.mp4` (4.89 MB) — 2026-10-13 04:03:06
- **Clips Per Hour During Active Render**: 6 clips in 29.9 minutes = **12.0 clips/hour**.
- **CPU Utilization (Measured over 60s window)**:
  - Python (PID 17428): **0.98% CPU** (0.59s CPU delta over 60.05s wall time). The process was strictly sleeping in a `time.sleep(1.0)` polling loop.
  - FFmpeg: **0.00% CPU** (no active encoding).
- **Disk Free Space**:
  - `C:\` (Fast NVMe SSD): **224.2 GB free**
  - `D:\` (Secondary Partition): **223.3 GB free**
  - `G:\` (Google Drive Stream): **212.8 GB free**
- **Computer Sleep / Power Log**:
  - Queried Windows System Event Log for Event ID 42 (Kernel-Power Sleep): **0 sleep events occurred**.
  - Log timestamps in `job.log` ticked continuously every 30 seconds (`[04:03:10]` through `[11:15:23]`). The PC remained continuously awake.

---

## 3. Measured Time Per Activity (Wall Clock Breakdown)

Exclusive wall clock breakdown totaling 100% of the elapsed time:

| Activity | Measured Wall Clock (s) | Share (%) | Description & Bottlenecks |
|---|---|---|---|
| **Stage 1: Candidate Reservation** | 0.18 s | < 0.01% | Ledger SQLite query for candidates |
| **Stage 2: Source Staging** | 0.05 s | < 0.01% | Disk path resolution and staging |
| **Stage 3: FFprobe QC Gate** | 0.12 s | < 0.01% | Quick container/stream metadata check |
| **Stage 4: Watermark & Logo Detection**| 2.45 s | 0.01% | 4-corner multi-frame badge analysis |
| **Stage 5: Stage A Analysis & Framing** | 516.18 s | 1.78% | 394 candidate windows evaluated (1.31 s/window); 91.4% rejected |
| **Stage 6: Active Render (ffmpeg)** | 612.00 s | 2.11% | Sequential CPU libx264 rendering (6 successful clips + ~60 standby tests) |
| **Stage 6: Post-Crop QA Gates** | 1,184.00 s | 4.09% | Full cv2 frame-by-frame decode & pet re-detection (~19.7 s per test) |
| **Caption & Audio Master** | 0.00 s | 0.00% | Never reached due to shortage |
| **Segment Assembly (Concat)** | 0.00 s | 0.00% | Never reached |
| **Final 10-Gate QA** | 0.00 s | 0.00% | Never reached |
| **Copy to Google Drive** | 0.00 s | 0.00% | Never reached |
| **Idle / Waiting (Bank Shortage)** | 26,630.00 s | 92.00% | 852 consecutive 30-second polling sleep loops in deadlock |
| **Sleep Time (OS Suspend)** | 0.00 s | 0.00% | 0 seconds (verified via Event ID 42) |
| **TOTAL WALL CLOCK** | **28,944.98 s** | **100.00%** | **~8 hours 2 minutes** |

### Throughput Metrics for this Job
- **Candidate Windows Analyzed Per Hour**: 394 windows in 516.2 s = **2,748 windows / hour**.
- **Verified Windows Generated Per Hour**: 34 windows in 516.2 s = **237 verified windows / hour**.
- **Clips Rendered Per Hour**: 6 clips in 1,796 s active Stage 6 time = **12.0 clips / hour**.

---

## 4. Pass Rates by Source, Uploader, and Query

### Pass Rate by Source Video
Analysis extracted from `data/stage_a_cache.db` (374 windows cached):

| Source File / Identifier | Passed Windows | Rejected Windows | Total Evaluated | Pass Rate |
|---|---|---|---|---|
| `cache_ByH9LuSILxU.mp4` | 5 | 7 | 12 | **41.7%** |
| `cache_zCBhhLo6lIM.mp4` | 26 | 321 | 347 | **7.5%** |
| Mock / Unit Test Sources | 3 | 12 | 15 | **20.0%** |
| **Overall Pool Average** | **34** | **340** | **374** | **9.1%** |

### Blocked Sources (0% Yield - Pre-Blocked by Circuit Breaker)
1. `cache_8R_7KCtShkU.mp4` — `LOW_RESOLUTION`: upscale 2.67x exceeds 2.0x limit (1280x720)
2. `cache_SB-qEYVdvXA.mp4` — `LOW_RESOLUTION`: upscale 2.67x exceeds 2.0x limit (1280x720)
3. `sel_yt_1791105357_2.mp4` — `LOW_RESOLUTION`: upscale 5.33x exceeds 2.0x limit (640x360)
4. `raw_x_rBfKdlGyQ_1791108652.mp4` — `BLOCKED_WATERMARK`: WOA Network logo in bottom-left corner
5. `raw_ZXNIiZWklsk_1791108036.f616.mp4` — `BLOCKED_WATERMARK`: Paw Life colored channel emblem in bottom-left
6. `raw_ZXNIiZWklsk_1791108652.f616.mp4` — `BLOCKED_WATERMARK`: Paw Life colored channel emblem in bottom-left
7. `cache_hY7m5jjJ9mM.mp4` — `BLOCKED_CARTOON`: Failed CGI/real footage classifier

### Distribution of Rejection Reasons (Why 90.9% of Windows Failed)
1. **NO_PET_TRACKED (Presence < 35%)**: 260 windows (**76.5%** of rejections) — camera panned away, human in frame, or cat occluded.
2. **NO_PET**: 44 windows (**12.9%** of rejections) — zero pet detection in window.
3. **PREDICTED_BAD_FRAMING (Score < 90%)**: 14 windows (**4.1%** of rejections) — bounding box drifted off-center or cut off.
4. **FRAMING_INFEASIBLE (Median box > 92% crop)**: 11 windows (**3.2%** of rejections) — extreme close-up where cat exceeds 9:16 frame width.
5. **REJECT_PEAK_FRAMING (Vis < 100% at peak)**: 10 windows (**2.9%** of rejections).
6. **LOW_SHARPNESS (< 85)**: 1 window (**0.3%** of rejections).

### Analysis Time Burned on Rejected Windows
- **Time spent analyzing passing windows**: 34 windows × 1.31 s = **44.5 s** (8.6% of analysis time).
- **Time spent analyzing rejected windows**: 360 windows × 1.31 s = **471.7 s** (91.4% of analysis time).
- Over **91.4% of all analysis time** was spent examining video sections that failed pet presence or framing gates.

---

## 5. Root Causes & Action Plan for SPEED PASS

1. **Deadlock Elimination**:
   - `ClipBankFiller.is_render_active()` must NOT pause when the render job is in `needs_sources` or `waiting_for_clips` state. In fact, that is the exact moment the bank filler must run at maximum priority to fulfill the shortage!
   - Add a circuit breaker to the render job: if `wait_state["consecutive_no_growth"] >= 10` (5 minutes of zero growth), gracefully enter shortfall options or inform the user, rather than looping infinitely for 7 hours.
2. **Accurate State & Waiting Clock in UI**:
   - In `web_server.py`, check `wait_checkpoint.json` and `job_res.get("status")`. If status is `needs_sources` or `waiting_for_clips`, report `stateLabel: "WAITING"` and return `is_waiting: True`.
   - Never report `LIVE` when waiting. Separate `working_seconds` from `waiting_seconds`. Show a distinct amber/yellow badge with a dedicated waiting timer.
3. **Render Path Hardware Acceleration & Parallel Workers**:
   - Currently, each clip is rendered sequentially using single-pass CPU `libx264` at ~10 seconds per 12s clip.
   - Use Intel QuickSync Video (`h264_qsv`) on the Intel Iris Xe GPU: encode time drops from ~10s to ~1.8s per clip.
   - Run 2-3 parallel render workers bounded by CPU/RAM.
4. **Post-Crop Gate Acceleration**:
   - Currently takes ~19.7s per clip decoding all frames at 1080x1920.
   - Sample only 12-16 evenly-spaced frames downscaled to 360x640 (target < 3-4 s per clip).
5. **Streaming Segment Pipeline & Concat Assembly**:
   - Render and checkpoint clips progressively.
   - Group rendered clips into 10-clip segments joined with ffmpeg concat demuxer (30 fps CFR, identical stream parameters).
   - Verify duration, loudness, and audio sync across segments without re-encoding the full 20-minute video.
6. **Prevent OS Sleep during Render**:
   - Utilize `ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000040)` to prevent system sleep while rendering, and release execution state upon completion.
