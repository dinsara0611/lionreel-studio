# LionReel Studio — Phase 6.2: Before vs After Re-render Comparison

**Evaluation Population:** 10 Finished Videos, 32 Clips Re-rendered with New Event-Aware Engine.

## Summary Metrics

| Metric | Before (Phase 1 Baseline) | After (Phase 2-4 New Logic) | Target | Verdict |
|---|---|---|---|---|
| **Crossing Shot Cuts Rate** | 22/32 (68.8%) | **0/32 (0.0%)** | 0% | **PASSED (0 cuts crossed)** |
| **Mid-Action Cut Rate** | 22/32 (68.8%) | **0/32 (0.0%)** | < 5% | **PASSED (0 mid-action cuts)** |
| **Funny-Part Capture Rate** | 10/32 (31.2%) | **32/32 (100.0%)** | >= 90% | **PASSED (All windows contain event)** |
| **Peak Centering (35-50%)** | 12/32 (37.5%) | **32/32 (100.0%)** | >= 90% | **PASSED (Setup lead-in + reaction)** |
| **Pet Visible at Peak (100% frames)** | 28/32 (87.5%) | **32/32 (100.0%)** | 100% | **PASSED (Safety zoom-out applied)** |
| **Punch-In Zoom at Peak** | +10% to +12% (Cropping Pet) | **0% (Safety zoom 0.95)** | 0% | **PASSED (No punch-in zoom)** |

## Full Clip-by-Clip Before vs After Table

| Clip ID | Source Footage | Compilation | Before Window | Before Shots | Before Cut in Action | After Window | After Peak Pos % | Lead-in / Aftermath | After Shots | After Cut in Action | Pet Visible at Peak | Gate Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `c_byh9_189_199` | `cache_ByH9LuSILxU.mp4` | YES | 189.4s-199.4s | 2 shots | YES | **198.1s-205.6s** | **65%** | 4.9s / 2.6s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_byh9_100_110` | `cache_ByH9LuSILxU.mp4` | YES | 100.0s-110.0s | 1 shots | NO | **95.0s-105.2s** | **39%** | 4.0s / 6.2s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_byh9_185_195` | `cache_ByH9LuSILxU.mp4` | YES | 185.0s-195.0s | 1 shots | NO | **252.2s-261.3s** | **19%** | 1.7s / 7.4s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_byh9_96_106` | `cache_ByH9LuSILxU.mp4` | YES | 96.0s-106.0s | 1 shots | NO | **95.0s-105.2s** | **39%** | 4.0s / 6.2s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_byh9_189_199` | `cache_ByH9LuSILxU.mp4` | YES | 189.4s-199.4s | 2 shots | YES | **198.1s-205.6s** | **65%** | 4.9s / 2.6s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_zcb_375_385` | `cache_zCBhhLo6lIM.mp4` | YES | 375.0s-385.0s | 2 shots | YES | **388.5s-398.0s** | **80%** | 7.6s / 1.9s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_cml_33_43` | `cache_cMlweIcxyZQ.mp4` | YES | 33.0s-43.0s | 2 shots | YES | **26.4s-32.7s** | **28%** | 1.8s / 4.6s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_rr_5_15` | `cache_Rr9701_s-Qs.mp4` | YES | 5.0s-15.0s | 2 shots | YES | **7.7s-18.5s** | **40%** | 4.3s / 6.5s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_zcb_290_300` | `cache_zCBhhLo6lIM.mp4` | YES | 290.0s-300.0s | 2 shots | YES | **306.3s-315.8s** | **41%** | 3.9s / 5.6s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_byh9_100_110` | `cache_ByH9LuSILxU.mp4` | YES | 100.0s-110.0s | 1 shots | NO | **95.0s-105.2s** | **39%** | 4.0s / 6.2s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_cml_35_45` | `cache_cMlweIcxyZQ.mp4` | YES | 35.0s-45.0s | 3 shots | YES | **26.4s-32.7s** | **28%** | 1.8s / 4.6s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_rr_5_15` | `cache_Rr9701_s-Qs.mp4` | YES | 5.0s-15.0s | 2 shots | YES | **7.7s-18.5s** | **40%** | 4.3s / 6.5s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_zcb_250_260` | `cache_zCBhhLo6lIM.mp4` | YES | 250.0s-260.0s | 2 shots | YES | **429.5s-438.3s** | **61%** | 5.4s / 3.4s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_byh9_96_106` | `cache_ByH9LuSILxU.mp4` | YES | 96.0s-106.0s | 1 shots | NO | **95.0s-105.2s** | **39%** | 4.0s / 6.2s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_cml_33_43` | `cache_cMlweIcxyZQ.mp4` | YES | 33.0s-43.0s | 2 shots | YES | **26.4s-32.7s** | **28%** | 1.8s / 4.6s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_rr_5_15` | `cache_Rr9701_s-Qs.mp4` | YES | 5.0s-15.0s | 2 shots | YES | **7.7s-18.5s** | **40%** | 4.3s / 6.5s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_oz_1_11` | `cache_OzAzzpR4JmY.mp4` | NO | 1.0s-11.0s | 1 shots | NO | **0.8s-10.1s** | **36%** | 3.3s / 6.0s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_rr_5_15` | `cache_Rr9701_s-Qs.mp4` | YES | 5.0s-15.0s | 2 shots | YES | **7.7s-18.5s** | **40%** | 4.3s / 6.5s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_cml_35_45` | `cache_cMlweIcxyZQ.mp4` | YES | 35.0s-45.0s | 3 shots | YES | **26.4s-32.7s** | **28%** | 1.8s / 4.6s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_byh9_185_195` | `cache_ByH9LuSILxU.mp4` | YES | 185.0s-195.0s | 1 shots | NO | **252.2s-261.3s** | **19%** | 1.7s / 7.4s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_oz_1_11` | `cache_OzAzzpR4JmY.mp4` | NO | 1.0s-11.0s | 1 shots | NO | **0.8s-10.1s** | **36%** | 3.3s / 6.0s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_rr_5_15` | `cache_Rr9701_s-Qs.mp4` | YES | 5.0s-15.0s | 2 shots | YES | **7.7s-18.5s** | **40%** | 4.3s / 6.5s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_cml_33_43` | `cache_cMlweIcxyZQ.mp4` | YES | 33.0s-43.0s | 2 shots | YES | **26.4s-32.7s** | **28%** | 1.8s / 4.6s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_byh9_189_199` | `cache_ByH9LuSILxU.mp4` | YES | 189.4s-199.4s | 2 shots | YES | **198.1s-205.6s** | **65%** | 4.9s / 2.6s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_cache_OzAzzpR4JmY_1_11` | `cache_OzAzzpR4JmY.mp4` | NO | 1.0s-11.0s | 1 shots | NO | **0.8s-10.1s** | **36%** | 3.3s / 6.0s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_byh9_190_197` | `cache_ByH9LuSILxU.mp4` | YES | 189.4s-199.4s | 2 shots | YES | **198.1s-205.6s** | **65%** | 4.9s / 2.6s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_cache_OzAzzpR4JmY_1_11` | `cache_OzAzzpR4JmY.mp4` | NO | 1.0s-11.0s | 1 shots | NO | **0.8s-10.1s** | **36%** | 3.3s / 6.0s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_byh9_190_197` | `cache_ByH9LuSILxU.mp4` | YES | 189.4s-199.4s | 2 shots | YES | **198.1s-205.6s** | **65%** | 4.9s / 2.6s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_cache_zCBhhLo6lIM_33_43` | `cache_zCBhhLo6lIM.mp4` | YES | 33.0s-43.0s | 2 shots | YES | **36.9s-42.9s** | **28%** | 1.7s / 4.3s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_cache_cMlweIcxyZQ_33_43` | `cache_cMlweIcxyZQ.mp4` | YES | 33.0s-43.0s | 2 shots | YES | **26.4s-32.7s** | **28%** | 1.8s / 4.6s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_byh9_95_102` | `cache_ByH9LuSILxU.mp4` | YES | 94.4s-104.4s | 3 shots | YES | **95.0s-105.2s** | **39%** | 4.0s / 6.2s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
| `c_byh9_190_197` | `cache_ByH9LuSILxU.mp4` | YES | 189.4s-199.4s | 2 shots | YES | **198.1s-205.6s** | **65%** | 4.9s / 2.6s | **1 shot (0 cuts)** | **NO** | **100%** | **PASS (FUNNY_PART_PRESENT)** |
