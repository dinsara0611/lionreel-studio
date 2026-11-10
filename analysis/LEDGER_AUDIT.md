# LionReel Studio — Clip Ledger & Bank Audit Report

**Audit Timestamp:** 2026-10-12 00:48:00
**Database Audited:** `C:\LionReel\data\clip_ledger.db`

---

## 1. Executive Summary

- **Total Rows in `clips` Table:** 121
- **Total Rows Marked `is_verified = 1`:** 26
  - **Real Verified Clips with Evidence:** 9
  - **Synthetic Test Clips without Evidence:** 17
- **Rows with Stored Evidence (`verified_plan`):** 51
- **Rows with Synthetic/Constant Scores (`framing=0.95`):** 17
- **Pending Reservations:** 8 (all from job `lionreel_cat_20261012_001844_49a37061`)

## 2. Root Cause of Synthetic Data in Production Ledger

### How, When & Why Synthetic Rows Entered the Ledger
1. **Creation Script:** `scratch/create_10_sources.py` sliced 10 30-second clips (`src_vert_cat_01..05.mp4` and `src_horiz_cat_06..10.mp4`) from `cache_zCBhhLo6lIM.mp4` and `cache_ByH9LuSILxU.mp4` using `ffmpeg`.
2. **Ingestion Script:** `scratch/ingest_10_sources.py` directly instantiated `ClipLedger()` (which connects to the production database `C:\LionReel\data\clip_ledger.db` by default) and inserted 17 rows with hardcoded properties:
   - `start_s = 2.0, end_s = 14.0` (window 1: 10 clips)
   - `start_s = 16.0, end_s = 28.0` (window 2: 7 clips)
   - `is_verified = 1`
   - `framing_score = 0.95` (constant 95.0%)
   - `quality_score = 1.8` (constant)
   - `sharpness = 180.0` (constant)
   - `verified_plan = ''` (EMPTY: zero tracking evidence, zero bounding boxes, zero gate records)
3. **Credits Pollution:** `scratch/ingest_10_sources.py` also appended 10 fake attribution entries to `credits_registry.csv` with names like 'Cute Paws Shorts CC' and 'Bobbie & Fos CC'.
4. **Why it Contradicted Stage A:** When job `lionreel_cat_20261012_001844_49a37061` ran, Stage A evaluated the `2.0s - 14.0s` windows through real YOLO pet tracking and **REJECTED ALL OF THEM** (pet presence was 0.0% - 25.0% < 35%, sharpness was 18.5 - 119.7 < 150). However, because the ledger had marked the `16.0s - 28.0s` windows as `is_verified = 1`, Stage 5 degradation ladder step 3 queried `get_verified_clips()` and enlisted them blindly at 95.0% without re-validation.

## 3. Breakdown by Source File

| Source Path | Type | Clip Count | Disk Status | Size (Bytes) |
|---|---|---|---|---|
| `cache_ByH9LuSILxU.mp4` | Real Production (`cache_*`) | 26 | EXISTS | 72,116,760 |
| `cache_zCBhhLo6lIM.mp4` | Real Production (`cache_*`) | 26 | EXISTS | 94,035,712 |
| `cache_825Za_ZishQ.mp4` | Real Production (`cache_*`) | 13 | EXISTS | 8,412,745 |
| `cache_cMlweIcxyZQ.mp4` | Real Production (`cache_*`) | 10 | EXISTS | 5,808,311 |
| `cache_Rr9701_s-Qs.mp4` | Real Production (`cache_*`) | 9 | EXISTS | 6,493,313 |
| `cache_ByH9LuSILxU.mp4` | Real Production (`cache_*`) | 7 | EXISTS | 72,116,760 |
| `raw_x_rBfKdlGyQ_1791108652.mp4` | Real Production (`cache_*`) | 5 | EXISTS | 68,680,376 |
| `cache_OzAzzpR4JmY.mp4` | Real Production (`cache_*`) | 3 | EXISTS | 18,243,251 |
| `cache_8R_7KCtShkU.mp4` | Real Production (`cache_*`) | 2 | EXISTS | 2,837,486 |
| `cache_hY7m5jjJ9mM.mp4` | Real Production (`cache_*`) | 2 | EXISTS | 155,068,191 |
| `src_vert_cat_play_01.mp4` | Synthetic (`src_*`) | 2 | EXISTS | 13,723,676 |
| `src_vert_cat_jump_02.mp4` | Synthetic (`src_*`) | 2 | EXISTS | 14,635,130 |
| `src_vert_cat_nap_03.mp4` | Synthetic (`src_*`) | 2 | EXISTS | 13,200,634 |
| `src_vert_cat_curious_04.mp4` | Synthetic (`src_*`) | 2 | EXISTS | 13,808,796 |
| `src_vert_cat_stretch_05.mp4` | Synthetic (`src_*`) | 2 | EXISTS | 15,965,769 |
| `src_horiz_cat_garden_06.mp4` | Synthetic (`src_*`) | 2 | EXISTS | 12,704,180 |
| `src_horiz_cat_window_07.mp4` | Synthetic (`src_*`) | 2 | EXISTS | 10,900,916 |
| `src_horiz_cat_relax_10.mp4` | Synthetic (`src_*`) | 2 | EXISTS | 12,593,126 |
| `cache_wWiSkRQsXvE.mp4` | Real Production (`cache_*`) | 1 | EXISTS | 1,839,290 |
| `src_horiz_cat_chase_09.mp4` | Synthetic (`src_*`) | 1 | EXISTS | 10,869,582 |

## 4. Breakdown by Clip State

| State | Count | Description |
|---|---|---|
| `unverified` | 93 | Raw ingested clips not yet run through verification gates |
| `used` | 11 | Clips used in previously completed renders (times_used > 0) |
| `verified_idle` | 9 | Verified clips available for new renders (times_used = 0, no reservation) |
| `reserved` | 8 | Clips currently locked by an active job ID |

## 5. Stored Evidence & Constant Score Analysis

- **Total Rows:** 121
- **Rows with Non-Empty `verified_plan`:** 51
- **Rows with Empty/Null `verified_plan`:** 70
- **Rows with Hardcoded Score `0.95` (95.0%):** 17 (all 17 synthetic `src_*` clips)
- **Rows Starting at Exactly 2.0s:** 10 (10 synthetic clips)
- **Rows with Window `16.0s - 28.0s`:** 8 (8 synthetic clips)

## 6. Real Verified Clips (Genuine Baseline)

There are exactly 9 genuine verified clips in the production database. All 9 possess valid `verified_plan` JSON evidence and real measured sharpness:

| Clip ID | Real Source | Window | Framing | Sharpness | Times Used | Evidence? |
|---|---|---|---|---|---|---|
| `c_byh9_96_106` | `cache_ByH9LuSILxU.mp4` | 96.0s - 106.0s | 100.0% | 1399.7 | 2 | YES (`verified_plan`) |
| `c_byh9_100_110` | `cache_ByH9LuSILxU.mp4` | 100.0s - 110.0s | 100.0% | 1420.2 | 1 | YES (`verified_plan`) |
| `c_byh9_185_195` | `cache_ByH9LuSILxU.mp4` | 185.0s - 195.0s | 100.0% | 2142.3 | 2 | YES (`verified_plan`) |
| `c_rr_5_15` | `cache_Rr9701_s-Qs.mp4` | 5.0s - 15.0s | 100.0% | 626.5 | 4 | YES (`verified_plan`) |
| `c_cml_35_45` | `cache_cMlweIcxyZQ.mp4` | 35.0s - 45.0s | 100.0% | 361.1 | 2 | YES (`verified_plan`) |
| `c_zcb_250_260` | `cache_zCBhhLo6lIM.mp4` | 250.0s - 260.0s | 100.0% | 731.4 | 2 | YES (`verified_plan`) |
| `c_zcb_290_300` | `cache_zCBhhLo6lIM.mp4` | 290.0s - 300.0s | 100.0% | 565.7 | 2 | YES (`verified_plan`) |
| `c_zcb_375_385` | `cache_zCBhhLo6lIM.mp4` | 375.0s - 385.0s | 100.0% | 580.0 | 2 | YES (`verified_plan`) |
| `c_zcb_380_390` | `cache_zCBhhLo6lIM.mp4` | 380.0s - 390.0s | 100.0% | 559.7 | 1 | YES (`verified_plan`) |

## 7. Action Plan for Quarantine & Ledger Guard

1. **Quarantine Database Rows:** Move all 17 synthetic `src_*` rows out of `clips` table into a dedicated `quarantined_clips` table with quarantine metadata (timestamp, reason).
2. **Quarantine Source Files:** Move `raw/src_vert_cat_*.mp4` and `raw/src_horiz_cat_*.mp4` to `C:\LionReel_quarantine\synthetic_20261012\` alongside `quarantine_manifest.json` and a Python `restore_quarantine.py` script.
3. **Quarantine Credits:** Move the 10 entries in `credits_registry.csv` matching `src_*` to `credits_registry_quarantined.csv`.
4. **Implement `LEDGER_GUARD`:** Ensure the production engine fails immediately if any row in `clips` is synthetic, lacks evidence, or has a constant score.
5. **Strict Bank Enlisting:** Enlist bank candidates ONLY if they pass re-validation through real Stage A / post-crop gates or have an authenticated cache record.
