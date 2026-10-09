const { chromium } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');
const fs = require('fs');
const path = require('path');

async function testRenderUI() {
    const outDir = path.join(__dirname, '..', 'ui_audit', 'render_fix');
    if (!fs.existsSync(outDir)) {
        fs.mkdirSync(outDir, { recursive: true });
    }

    const browser = await chromium.launch({
        channel: 'chrome',
        headless: true
    });

    const themes = ['dark', 'light'];
    const viewports = [
        { width: 1440, height: 900, name: 'desktop_1440' },
        { width: 390, height: 844, name: 'mobile_390' }
    ];

    for (const theme of themes) {
        for (const vp of viewports) {
            const context = await browser.newContext({
                viewport: { width: vp.width, height: vp.height }
            });
            const page = await context.newPage();

            await page.goto('http://localhost:8000');
            await page.waitForTimeout(1500);

            // Apply theme
            await page.evaluate((th) => {
                if (typeof window.applyTheme === 'function') {
                    window.applyTheme(th);
                } else {
                    document.documentElement.setAttribute('data-theme', th);
                    if (th === 'light') {
                        document.documentElement.classList.add('light-mode');
                        document.documentElement.classList.remove('dark-mode');
                        document.body.classList.add('light-mode');
                        document.body.classList.remove('dark-mode');
                    } else {
                        document.documentElement.classList.add('dark-mode');
                        document.documentElement.classList.remove('light-mode');
                        document.body.classList.add('dark-mode');
                        document.body.classList.remove('light-mode');
                    }
                }
            }, theme);

            await page.waitForTimeout(400);

            // Navigate to step 4 (Render Screen)
            await page.evaluate(() => {
                if (typeof window.navigateToStep === 'function') {
                    window.navigateToStep(4);
                }
                // Simulate active progress state matching user's scenario
                if (window.state) {
                    window.state.renderProgress = 5;
                    window.state.renderStageIndex = 1;
                    window.state.renderStartTime = Date.now() - 10000; // 10s elapsed
                    window.state.liveStatusMsg = "Initializing LionReel AI compilation pipeline...";
                    window.state.config = window.state.config || {};
                    window.state.config.VIDEO_TYPE = "short";
                    window.state.config.TARGET_CLIPS = 4;
                    window.state.config.SHORT_CLIP_SEC = 10.0;
                    window.state.config.SPEED_PROFILE = "fast";
                    window.state.config.MOMENT_CUT_MODE = "peak_viral";
                }
                if (typeof window.updateRenderHeroUI === 'function') {
                    window.updateRenderHeroUI(5);
                }
            });

            await page.waitForTimeout(600);

            // Hero card screenshot
            const heroCard = await page.$('#render-hero-card');
            if (heroCard) {
                const heroPath = path.join(outDir, `render_hero_${theme}_${vp.name}.png`);
                await heroCard.screenshot({ path: heroPath });
                console.log(`Saved hero card: ${heroPath}`);
            }

            // Full viewport screenshot
            const fullPath = path.join(outDir, `render_full_${theme}_${vp.name}.png`);
            await page.screenshot({ path: fullPath, fullPage: false });
            console.log(`Saved full view: ${fullPath}`);

            // Contrast and telemetry check
            const metrics = await page.evaluate(() => {
                const pctEl = document.getElementById('render-percentage-text');
                const elapsedEl = document.getElementById('render-time-elapsed');
                const remainEl = document.getElementById('render-time-remaining');
                const stageEl = document.getElementById('render-stage-name');
                const summaryEl = document.getElementById('render-job-config-summary');

                return {
                    pct: pctEl ? pctEl.innerText : null,
                    elapsed: elapsedEl ? elapsedEl.innerText : null,
                    remaining: remainEl ? remainEl.innerText : null,
                    stage: stageEl ? stageEl.innerText : null,
                    chipsCount: summaryEl ? summaryEl.querySelectorAll('.render-config-chip').length : 0,
                    summaryHTML: summaryEl ? summaryEl.innerHTML.trim() : null
                };
            });

            console.log(`[${theme} - ${vp.name}] Telemetry Verification:`, metrics);

            await page.close();
            await context.close();
        }
    }

    await browser.close();
    console.log("All Render Hero UI fix tests completed successfully!");
}

testRenderUI().catch(err => {
    console.error("Test failed:", err);
    process.exit(1);
});
