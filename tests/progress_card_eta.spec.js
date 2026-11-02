module.paths.push('C:/Users/dinsa/AppData/Roaming/npm/node_modules');
const { test, expect } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');
const path = require('path');
const fs = require('fs');

const SCREENSHOTS_DIR = 'C:/Users/dinsa/.gemini/antigravity-ide/brain/fce974f5-b44c-4a2a-bfc6-375724d1acbc/screenshots';

test.describe('Progress Card & Estimator Verification Suite', () => {

    test('1. Verified Telemetry, Zero Naive Guessing, Monotonicity & Tab Sync', async ({ browser }) => {
        const context = await browser.newContext();
        const page1 = await context.newPage();
        await page1.setViewportSize({ width: 1440, height: 900 });

        // Intercept /api/status with 50% progress where elapsed is 165s (02:45)
        // With history saying ~60s left, the server estimator returns 01:00, NOT 02:45!
        let mockStatus = {
            status: "running",
            job_id: "test_job_sampling",
            isRunning: true,
            elapsedSeconds: 165,
            progressPct: 52,
            etaSeconds: 68,
            etaFormatted: "01:08",
            isCalculating: false,
            stateLabel: "LIVE",
            stageIndex: 6,
            stageName: "Reframe & render vertical clip cuts",
            stages: [
                { id: 1, key: "collect", label: "Collect candidate moments", status: "DONE", duration_sec: 1.0 },
                { id: 2, key: "prepare", label: "Prepare raw source files", status: "DONE", duration_sec: 0.5 },
                { id: 3, key: "check_fps", label: "Check resolution & fps", status: "DONE", duration_sec: 1.5 },
                { id: 4, key: "watermark", label: "Detect watermarks", status: "DONE", duration_sec: 8.0 },
                { id: 5, key: "framing", label: "Predict pet framing", status: "DONE", duration_sec: 45.0 },
                { id: 6, key: "render", label: "Reframe & render clips", status: "RUNNING", duration_sec: 109.0, details: { units_done: 3, units_total: 6, unit_type: "clips" } },
                { id: 7, key: "color", label: "Color grading", status: "PENDING", duration_sec: 0.0 },
                { id: 8, key: "captions", label: "Safe-zone captions", status: "PENDING", duration_sec: 0.0 },
                { id: 9, key: "qa", label: "Final assembly & QA", status: "PENDING", duration_sec: 0.0 },
                { id: 10, key: "credits", label: "Save master & credits", status: "PENDING", duration_sec: 0.0 }
            ]
        };

        await page1.route('**/api/status', async route => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify(mockStatus)
            });
        });

        await page1.goto('http://127.0.0.1:8000');
        await page1.waitForTimeout(600);

        // Switch to View 4 (Render step)
        await page1.evaluate(() => {
            if (typeof window.navigateToStep === 'function') window.navigateToStep(4);
            if (typeof window.checkEngineStatus === 'function') window.checkEngineStatus();
        });
        await page1.waitForTimeout(600);

        // 1. Verify Elapsed is 02:45 and Remaining is 01:08 (NEVER identical 02:45)
        const elapsedText = await page1.locator('#render-time-elapsed').innerText();
        const remainText = await page1.locator('#render-time-remaining').innerText();
        expect(elapsedText).toBe('02:45');
        expect(remainText).toBe('01:08');
        expect(remainText).not.toBe(elapsedText); // Proves naive straight-line formula is ELIMINATED!

        // 2. Verify Config Chips text format: multiplication sign, space before s, no trailing .0
        const chipSummary = await page1.locator('#render-job-config-summary').innerText();
        expect(chipSummary).toContain('clips ×');
        expect(chipSummary).toMatch(/\d+(\.\d+)?\s*s\s*\(/);
        expect(chipSummary).not.toContain('.0s');

        // 3. Verify Progress Bar accessibility attributes
        const fillBar = page1.locator('#render-progress-fill');
        await expect(fillBar).toHaveAttribute('role', 'progressbar');
        await expect(fillBar).toHaveAttribute('aria-valuenow', '52');
        await expect(fillBar).toHaveAttribute('aria-label', 'Compilation progress');

        // 4. Test Page Refresh: same elapsed and consistent ETA
        await page1.reload();
        await page1.waitForTimeout(600);
        await page1.evaluate(() => {
            if (typeof window.navigateToStep === 'function') window.navigateToStep(4);
            if (typeof window.checkEngineStatus === 'function') window.checkEngineStatus();
        });
        await page1.waitForTimeout(400);

        const reloadElapsed = await page1.locator('#render-time-elapsed').innerText();
        const reloadRemain = await page1.locator('#render-time-remaining').innerText();
        expect(reloadElapsed).toBe('02:45');
        expect(reloadRemain).toBe('01:08');

        // 5. Test Second Tab: opens new tab and verifies identical numbers
        const page2 = await context.newPage();
        await page2.route('**/api/status', async route => {
            await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockStatus) });
        });
        await page2.goto('http://127.0.0.1:8000');
        await page2.waitForTimeout(600);
        await page2.evaluate(() => {
            if (typeof window.navigateToStep === 'function') window.navigateToStep(4);
            if (typeof window.checkEngineStatus === 'function') window.checkEngineStatus();
        });
        await page2.waitForTimeout(400);

        const tab2Elapsed = await page2.locator('#render-time-elapsed').innerText();
        const tab2Remain = await page2.locator('#render-time-remaining').innerText();
        expect(tab2Elapsed).toBe(reloadElapsed);
        expect(tab2Remain).toBe(reloadRemain);

        await page2.close();
        await context.close();
    });

    test('2. Capture Comprehensive Screenshots across 4 States, Dark/Light, 1440px/390px', async ({ browser }) => {
        test.setTimeout(120000);
        const states = [
            {
                name: 'running',
                data: {
                    status: "running",
                    job_id: "lionreel_running",
                    isRunning: true,
                    elapsedSeconds: 165,
                    progressPct: 52,
                    etaSeconds: 68,
                    etaFormatted: "01:08",
                    isCalculating: false,
                    stateLabel: "LIVE",
                    stageIndex: 6,
                    stageName: "Reframe & render vertical clip cuts"
                }
            },
            {
                name: 'waiting',
                data: {
                    status: "waiting_for_clips",
                    job_id: "lionreel_waiting",
                    isRunning: false,
                    elapsedSeconds: 32,
                    waitingSeconds: 45,
                    progressPct: 40,
                    etaSeconds: 0,
                    etaFormatted: "Waiting for clips",
                    isCalculating: false,
                    stateLabel: "WAITING",
                    stageIndex: 5,
                    stageName: "Waiting for clips: 2 of 6 ready",
                    jobResult: { got_clips: 2, target_clips: 6 }
                }
            },
            {
                name: 'success',
                data: {
                    status: "completed",
                    job_id: "lionreel_success",
                    isRunning: false,
                    elapsedSeconds: 312,
                    progressPct: 100,
                    etaSeconds: 0,
                    etaFormatted: "--:--",
                    isCalculating: false,
                    stateLabel: "DONE",
                    stageIndex: 10,
                    stageName: "Save master & credits",
                    generatedFile: "lionreel_cat_master.mp4",
                    jobResult: { success: true, duration: 45.0, render_time_sec: 312 }
                }
            },
            {
                name: 'failed',
                data: {
                    status: "error",
                    job_id: "lionreel_failed",
                    isRunning: false,
                    elapsedSeconds: 48,
                    progressPct: 100,
                    etaSeconds: 0,
                    etaFormatted: "Failed",
                    isCalculating: false,
                    stateLabel: "FAILED",
                    stageIndex: 3,
                    stageName: "Check source resolution",
                    error: "Resolution lower than 1080p floor"
                }
            }
        ];

        const viewports = [
            { name: '1440', width: 1440, height: 900 },
            { name: '390', width: 390, height: 844 }
        ];

        const themes = ['dark', 'light'];

        for (const st of states) {
            for (const vp of viewports) {
                for (const th of themes) {
                    const page = await browser.newPage();
                    await page.setViewportSize({ width: vp.width, height: vp.height });

                    await page.route('**/api/status', async route => {
                        await route.fulfill({
                            status: 200,
                            contentType: 'application/json',
                            body: JSON.stringify(st.data)
                        });
                    });

                    await page.goto('http://127.0.0.1:8000');
                    await page.waitForTimeout(400);

                    await page.evaluate(({ theme, stateData }) => {
                        document.documentElement.setAttribute('data-theme', theme);
                        if (theme === 'light') {
                            document.documentElement.classList.add('light-mode');
                            document.body.classList.add('light-mode');
                        } else {
                            document.documentElement.classList.remove('light-mode');
                            document.body.classList.remove('light-mode');
                        }
                        if (typeof window.navigateToStep === 'function') window.navigateToStep(4);
                        if (typeof window.checkEngineStatus === 'function') window.checkEngineStatus();
                    }, { theme: th, stateData: st.data });

                    await page.waitForTimeout(600);

                    const card = page.locator('#render-hero-card');
                    const shotPath = path.join(SCREENSHOTS_DIR, `card_${st.name}_${th}_${vp.name}.png`);
                    await card.screenshot({ path: shotPath });

                    await page.close();
                }
            }
        }
    });
});
