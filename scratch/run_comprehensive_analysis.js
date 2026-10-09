module.paths.push('C:/Users/dinsa/AppData/Roaming/npm/node_modules');
const { chromium } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'http://localhost:8000';
const OUT_DIR = path.resolve('analysis');

// Ensure directories
['dark/1440', 'dark/390', 'light/1440', 'light/390'].forEach(sub => {
    fs.mkdirSync(path.join(OUT_DIR, sub), { recursive: true });
});

async function run() {
    console.log('--- Starting Comprehensive LionReel Studio UI Analysis ---');

    const browser = await chromium.launch({
        channel: 'chrome',
        headless: true
    });

    const consoleLogs = [];
    const consoleErrors = [];
    const consoleWarnings = [];
    const networkFailures = [];
    const networkRequests = [];

    // Helper function for capturing steps and states
    async function analyzeViewportTheme(theme, width, height) {
        console.log(`\n=== Analyzing: Theme=${theme}, Viewport=${width}x${height} ===`);
        const subPath = `${theme}/${width}`;
        const context = await browser.newContext({
            viewport: { width, height },
            deviceScaleFactor: 1
        });

        const page = await context.newPage();

        // Listen for console and network
        page.on('console', msg => {
            const entry = `[${msg.type()}] ${msg.text()}`;
            consoleLogs.push(entry);
            if (msg.type() === 'error') consoleErrors.push(entry);
            if (msg.type() === 'warning') consoleWarnings.push(entry);
        });

        page.on('requestfailed', req => {
            networkFailures.push({
                url: req.url(),
                failure: req.failure() ? req.failure().errorText : 'unknown'
            });
        });

        page.on('response', resp => {
            networkRequests.push({
                url: resp.url(),
                status: resp.status()
            });
        });

        // Load page
        await page.goto(`${BASE_URL}/#step1`, { waitUntil: 'domcontentloaded' });
        await page.waitForSelector('#app-loading-screen', { state: 'hidden', timeout: 8000 }).catch(() => {});
        await page.waitForTimeout(600);

        // Force theme
        await page.evaluate((th) => {
            localStorage.setItem('lionreel_theme', th);
            document.documentElement.setAttribute('data-theme', th);
            if (th === 'light') {
                document.documentElement.classList.add('light-mode');
                document.documentElement.classList.remove('dark-mode');
            } else {
                document.documentElement.classList.add('dark-mode');
                document.documentElement.classList.remove('light-mode');
            }
        }, theme);
        await page.waitForTimeout(400);

        // 1. Step 1: Create (#step1 / #view-dashboard) - Idle state
        await page.evaluate(() => { if (window.switchWorkflowStep) window.switchWorkflowStep(1); });
        await page.waitForTimeout(400);
        await page.screenshot({ path: path.join(OUT_DIR, subPath, 'step1_create.png'), fullPage: false });
        await page.screenshot({ path: path.join(OUT_DIR, subPath, 'state_idle.png'), fullPage: false });
        console.log(`Saved step1_create.png & state_idle.png (${subPath})`);

        // 2. Step 2: Sources (#step2 / #view-wizard)
        await page.evaluate(() => { if (window.switchWorkflowStep) window.switchWorkflowStep(2); });
        await page.waitForTimeout(400);
        await page.screenshot({ path: path.join(OUT_DIR, subPath, 'step2_sources.png'), fullPage: false });
        console.log(`Saved step2_sources.png (${subPath})`);

        // 3. Step 3: Configure/Edit (#step3 / #view-editor)
        await page.evaluate(() => { if (window.switchWorkflowStep) window.switchWorkflowStep(3); });
        await page.waitForTimeout(400);
        await page.screenshot({ path: path.join(OUT_DIR, subPath, 'step3_edit.png'), fullPage: false });
        console.log(`Saved step3_edit.png (${subPath})`);

        // 4. Step 4: Render (#step4 / #view-render)
        await page.evaluate(() => { if (window.switchWorkflowStep) window.switchWorkflowStep(4); });
        await page.waitForTimeout(400);
        await page.screenshot({ path: path.join(OUT_DIR, subPath, 'step4_render.png'), fullPage: false });
        console.log(`Saved step4_render.png (${subPath})`);

        // State: Running simulation in step 4
        await page.evaluate(() => {
            const pbar = document.getElementById('render-progress-bar');
            const ptext = document.getElementById('render-progress-text');
            const stitle = document.getElementById('current-stage-title');
            if (pbar) pbar.style.width = '62%';
            if (ptext) ptext.textContent = '62%';
            if (stitle) stitle.textContent = 'Stage 4: Subject-Tracking Pet Reframing (62%)';
            const term = document.getElementById('terminal-body');
            if (term) {
                term.innerHTML += '<div class="log-line info">[SEQ:42] [12:34:56] [INFO] Processing Clip 2/4: cache_SB-qEYVdvXA.mp4 (Tracking: 95.2%)</div>';
            }
        });
        await page.waitForTimeout(300);
        await page.screenshot({ path: path.join(OUT_DIR, subPath, 'state_running.png'), fullPage: false });
        console.log(`Saved state_running.png (${subPath})`);

        // State: Failed simulation
        await page.evaluate(() => {
            const stitle = document.getElementById('current-stage-title');
            if (stitle) stitle.textContent = 'Render Failed: BAD_CENTERING (Pet center at 31.4% < 38% limit)';
            const pbar = document.getElementById('render-progress-bar');
            if (pbar) pbar.style.backgroundColor = '#EF4444';
            const alert = document.getElementById('pipeline-error-alert');
            if (alert) {
                alert.style.display = 'block';
                alert.textContent = 'JOB FAILED: not enough usable clips (got 2 of 4 passing gate)';
            }
        });
        await page.waitForTimeout(300);
        await page.screenshot({ path: path.join(OUT_DIR, subPath, 'state_failed.png'), fullPage: false });
        console.log(`Saved state_failed.png (${subPath})`);

        // 5. Step 5: Export / Finished (#step5 / #view-export)
        await page.evaluate(() => { if (window.switchWorkflowStep) window.switchWorkflowStep(5); });
        await page.waitForTimeout(400);
        await page.screenshot({ path: path.join(OUT_DIR, subPath, 'step5_export.png'), fullPage: false });
        await page.screenshot({ path: path.join(OUT_DIR, subPath, 'state_success.png'), fullPage: false });
        console.log(`Saved step5_export.png & state_success.png (${subPath})`);

        // State: Empty pool warning
        await page.evaluate(() => {
            if (window.switchWorkflowStep) window.switchWorkflowStep(1);
            const poolWarn = document.getElementById('low-pool-alert');
            if (poolWarn) poolWarn.style.display = 'block';
            const poolBar = document.getElementById('pool-usage-bar');
            if (poolBar) {
                poolBar.style.width = '5%';
                poolBar.style.background = '#EF4444';
            }
            const poolText = document.getElementById('pool-clips-used');
            if (poolText) poolText.textContent = '0 / 12 Active (Pool Empty)';
        });
        await page.waitForTimeout(300);
        await page.screenshot({ path: path.join(OUT_DIR, subPath, 'state_empty_pool.png'), fullPage: false });
        console.log(`Saved state_empty_pool.png (${subPath})`);

        // State: Error Toast
        await page.evaluate(() => {
            if (typeof window.showToast === 'function') {
                window.showToast('Duration mismatch: Expected 30.0s, got 15.6s (-48%)', 'error');
            } else {
                let toast = document.getElementById('toast');
                if (!toast) {
                    toast = document.createElement('div');
                    toast.id = 'toast';
                    toast.className = 'toast toast-error';
                    document.body.appendChild(toast);
                }
                toast.textContent = 'Duration mismatch: Expected 30.0s, got 15.6s (-48%)';
                toast.style.display = 'block';
            }
        });
        await page.waitForTimeout(400);
        await page.screenshot({ path: path.join(OUT_DIR, subPath, 'state_toast.png'), fullPage: false });
        console.log(`Saved state_toast.png (${subPath})`);

        // Modal: Video Preview Modal
        await page.evaluate(() => {
            const modal = document.getElementById('modal-video-preview');
            if (modal) {
                modal.classList.add('active');
                modal.style.display = 'flex';
            }
        });
        await page.waitForTimeout(300);
        await page.screenshot({ path: path.join(OUT_DIR, subPath, 'modal_preview.png'), fullPage: false });
        console.log(`Saved modal_preview.png (${subPath})`);

        // Close preview modal & open shortcuts modal
        await page.evaluate(() => {
            const m1 = document.getElementById('modal-video-preview');
            if (m1) {
                m1.classList.remove('active');
                m1.style.display = 'none';
            }
            const m2 = document.getElementById('modal-shortcuts');
            if (m2) {
                m2.classList.add('active');
                m2.style.display = 'flex';
            }
        });
        await page.waitForTimeout(300);
        await page.screenshot({ path: path.join(OUT_DIR, subPath, 'modal_shortcuts.png'), fullPage: false });
        console.log(`Saved modal_shortcuts.png (${subPath})`);

        await page.close();
        await context.close();
    }

    // Run across all 4 combinations
    await analyzeViewportTheme('dark', 1440, 900);
    await analyzeViewportTheme('dark', 390, 844);
    await analyzeViewportTheme('light', 1440, 900);
    await analyzeViewportTheme('light', 390, 844);

    console.log('\n=== All Screenshots Completed Successfully ===');
    await browser.close();

    // Save logs & network summary
    fs.writeFileSync(path.join(OUT_DIR, 'console_summary.json'), JSON.stringify({
        errors: consoleErrors,
        warnings: consoleWarnings,
        failures: networkFailures,
        totalRequests: networkRequests.length
    }, null, 2));

    console.log(`Console Errors: ${consoleErrors.length}, Warnings: ${consoleWarnings.length}, Network Failures: ${networkFailures.length}`);
}

run().catch(err => {
    console.error('Fatal error running analysis script:', err);
    process.exit(1);
});
