module.paths.push('C:/Users/dinsa/AppData/Roaming/npm/node_modules');
const { test, expect } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');
const path = require('path');
const fs = require('fs');

const ARTIFACTS_DIR = 'C:/Users/dinsa/.gemini/antigravity-ide/brain/d2de3fbc-7e22-4365-91d3-a9728126668a';

test.describe('10 Automated Pipeline Stages - Dynamic Order & Evidence UI', () => {
    test('renders mid-run and completed stages in dark and light modes', async ({ page }) => {
        await page.setViewportSize({ width: 1280, height: 950 });
        await page.goto('http://localhost:8100');
        await page.waitForTimeout(1000);

        // Navigate to Step 4 (Render step)
        await page.evaluate(() => {
            if (typeof window.navigateToStep === 'function') {
                window.navigateToStep(4);
            }
        });
        await page.waitForTimeout(500);

        // 1. MID-RUN STATE:
        // Stage 1-4 completed/skipped, Stage 5 RUNNING, Stage 6-10 PENDING
        const midRunStages = [
            {
                id: 1,
                key: "collect_candidates",
                label: "Collect candidate moments from ledger",
                status: "DONE",
                duration_sec: 0.85,
                evidence: "Reserved 4 fresh candidate clips (instant: pool ready, verified in-memory)",
                reason: ""
            },
            {
                id: 2,
                key: "prepare_sources",
                label: "Prepare & verify raw source video files",
                status: "DONE",
                duration_sec: 1.15,
                evidence: "Probed 4 source files, verified H.264 streams on disk",
                reason: ""
            },
            {
                id: 3,
                key: "check_quality_fps",
                label: "Check source video resolution & frame rate",
                status: "DONE",
                duration_sec: 0.92,
                evidence: "1080x1920 @ 30fps CFR compliant, no variable-fps jitter (instant: verified in-memory)",
                reason: ""
            },
            {
                id: 4,
                key: "detect_watermarks",
                label: "Detect watermarks, logos & overlays",
                status: "DONE",
                duration_sec: 2.45,
                evidence: "Scanned corner regions: 0 watermarks or platform overlays detected",
                reason: ""
            },
            {
                id: 5,
                key: "predict_framing",
                label: "Predict pet framing & select viral moments",
                status: "RUNNING",
                duration_sec: 0.0,
                evidence: "Executing Stage A pre-scoring: YOLOX pet detector & sharpness analysis...",
                reason: ""
            },
            {
                id: 6,
                key: "reframe_render_clips",
                label: "Reframe & render vertical clip cuts",
                status: "PENDING",
                duration_sec: 0.0,
                evidence: "Waiting for prerequisites…",
                reason: ""
            },
            {
                id: 7,
                key: "color_grading",
                label: "Auto color grading & contrast optimization",
                status: "PENDING",
                duration_sec: 0.0,
                evidence: "Waiting for prerequisites…",
                reason: ""
            },
            {
                id: 8,
                key: "captions_and_audio",
                label: "Burn safe-zone captions & master audio ducking",
                status: "PENDING",
                duration_sec: 0.0,
                evidence: "Waiting for prerequisites…",
                reason: ""
            },
            {
                id: 9,
                key: "final_render_qa",
                label: "Final MP4 assembly & 10-gate QA validation",
                status: "PENDING",
                duration_sec: 0.0,
                evidence: "Waiting for prerequisites…",
                reason: ""
            },
            {
                id: 10,
                key: "save_credits_export",
                label: "Save master, register credits & export to Drive",
                status: "PENDING",
                duration_sec: 0.0,
                evidence: "Waiting for prerequisites…",
                reason: ""
            }
        ];

        await page.evaluate((stages) => {
            window.updateRenderStagesUI(stages);
            const heroEl = document.getElementById("render-stage-name");
            if (heroEl) heroEl.innerText = "Predict pet framing & select viral moments";
            const fracEl = document.getElementById("render-stage-fraction");
            if (fracEl) fracEl.innerText = "Stage 5 of 10";
        }, midRunStages);
        await page.waitForTimeout(500);

        // Ensure Dark mode
        await page.evaluate(() => {
            if (typeof window.applyTheme === 'function') window.applyTheme('dark');
            else {
                document.documentElement.setAttribute('data-theme', 'dark');
                document.body.classList.add('dark-mode');
                document.body.classList.remove('light-mode');
            }
        });
        await page.waitForTimeout(300);

        const cardLocator = page.locator('.render-stages-card');
        await expect(cardLocator).toBeVisible();

        // Capture Mid-Run Dark Mode
        const midDarkPath = path.join(ARTIFACTS_DIR, 'stage_list_midrun_dark.png');
        await cardLocator.screenshot({ path: midDarkPath });
        console.log('Saved:', midDarkPath);

        // Switch to Light mode
        await page.evaluate(() => {
            if (typeof window.applyTheme === 'function') window.applyTheme('light');
            else {
                document.documentElement.setAttribute('data-theme', 'light');
                document.body.classList.add('light-mode');
                document.body.classList.remove('dark-mode');
            }
        });
        await page.waitForTimeout(300);

        // Capture Mid-Run Light Mode
        const midLightPath = path.join(ARTIFACTS_DIR, 'stage_list_midrun_light.png');
        await cardLocator.screenshot({ path: midLightPath });
        console.log('Saved:', midLightPath);

        // 2. COMPLETED STATE:
        // All 10 stages completed/skipped (with real duration badges, honest evidence, and skipped CLAHE)
        const completedStages = [
            {
                id: 1,
                key: "collect_candidates",
                label: "Collect candidate moments from ledger",
                status: "DONE",
                duration_sec: 0.85,
                evidence: "Reserved 4 fresh candidate clips (instant: pool ready, verified in-memory)",
                reason: ""
            },
            {
                id: 2,
                key: "prepare_sources",
                label: "Prepare & verify raw source video files",
                status: "DONE",
                duration_sec: 1.15,
                evidence: "Probed 4 source files, verified H.264 streams on disk",
                reason: ""
            },
            {
                id: 3,
                key: "check_quality_fps",
                label: "Check source video resolution & frame rate",
                status: "DONE",
                duration_sec: 0.92,
                evidence: "1080x1920 @ 30fps CFR compliant (instant: verified in-memory)",
                reason: ""
            },
            {
                id: 4,
                key: "detect_watermarks",
                label: "Detect watermarks, logos & overlays",
                status: "DONE",
                duration_sec: 2.45,
                evidence: "Scanned corner regions: 0 watermarks or platform overlays detected",
                reason: ""
            },
            {
                id: 5,
                key: "predict_framing",
                label: "Predict pet framing & select viral moments",
                status: "DONE",
                duration_sec: 18.32,
                evidence: "Stage A YOLOX pre-scored 4 clips: avg sharpness 124.5, diversity NMS applied",
                reason: ""
            },
            {
                id: 6,
                key: "reframe_render_clips",
                label: "Reframe & render vertical clip cuts",
                status: "DONE",
                duration_sec: 42.10,
                evidence: "Stage B Smart-Crop rendered 4 vertical 9:16 cuts (post-crop centered)",
                reason: ""
            },
            {
                id: 7,
                key: "color_grading",
                label: "Auto color grading & contrast optimization",
                status: "SKIPPED",
                duration_sec: 0.05,
                evidence: "Skipped: turned off in settings (instant: pool ready, verified in-memory)",
                reason: "turned off in settings"
            },
            {
                id: 8,
                key: "captions_and_audio",
                label: "Burn safe-zone captions & master audio ducking",
                status: "DONE",
                duration_sec: 8.75,
                evidence: "Burned single-clip safe-zone captions, ducked BGM to -14.0 LUFS",
                reason: ""
            },
            {
                id: 9,
                key: "final_render_qa",
                label: "Final MP4 assembly & 10-gate QA validation",
                status: "DONE",
                duration_sec: 14.28,
                evidence: "Final MP4 assembled with FFmpeg, passed 10 QA gates (100% pass)",
                reason: ""
            },
            {
                id: 10,
                key: "save_credits_export",
                label: "Save master, register credits & export to Drive",
                status: "DONE",
                duration_sec: 0.42,
                evidence: "Master saved (SHA256: 3a28c4…), credits registered in ledger (instant: verified in-memory)",
                reason: ""
            }
        ];

        // Switch back to Dark mode for Completed Dark
        await page.evaluate(() => {
            if (typeof window.applyTheme === 'function') window.applyTheme('dark');
            else {
                document.documentElement.setAttribute('data-theme', 'dark');
                document.body.classList.add('dark-mode');
                document.body.classList.remove('light-mode');
            }
        });
        await page.waitForTimeout(200);

        await page.evaluate((stages) => {
            window.updateRenderStagesUI(stages);
            const heroEl = document.getElementById("render-stage-name");
            if (heroEl) heroEl.innerText = "All Pipeline Stages Complete";
            const fracEl = document.getElementById("render-stage-fraction");
            if (fracEl) fracEl.innerText = "10 of 10 Complete";
        }, completedStages);
        await page.waitForTimeout(500);

        // Capture Completed Dark Mode
        const compDarkPath = path.join(ARTIFACTS_DIR, 'stage_list_completed_dark.png');
        await cardLocator.screenshot({ path: compDarkPath });
        console.log('Saved:', compDarkPath);

        // Switch to Light mode for Completed Light
        await page.evaluate(() => {
            if (typeof window.applyTheme === 'function') window.applyTheme('light');
            else {
                document.documentElement.setAttribute('data-theme', 'light');
                document.body.classList.add('light-mode');
                document.body.classList.remove('dark-mode');
            }
        });
        await page.waitForTimeout(300);

        // Capture Completed Light Mode
        const compLightPath = path.join(ARTIFACTS_DIR, 'stage_list_completed_light.png');
        await cardLocator.screenshot({ path: compLightPath });
        console.log('Saved:', compLightPath);

        // Switch back to Dark mode as default
        await page.evaluate(() => {
            if (typeof window.applyTheme === 'function') window.applyTheme('dark');
        });
    });
});
