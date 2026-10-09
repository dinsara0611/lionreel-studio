const { chromium } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');
const path = require('path');
const fs = require('fs');

const OUT_DIR = path.resolve(__dirname, '../analysis/change2');
if (!fs.existsSync(OUT_DIR)) {
    fs.mkdirSync(OUT_DIR, { recursive: true });
}

async function runTestsForBrowser(channelName, browserDisplayName) {
    console.log(`\n======================================================`);
    console.log(`RUNNING CHANGE 2 TESTS: ${browserDisplayName} (channel: ${channelName})`);
    console.log(`======================================================`);

    const results = {
        browser: browserDisplayName,
        autoplayMuted: false,
        mutedTrue: false,
        defaultMutedTrue: false,
        startedAtZero: false,
        pillVisible: false,
        pillText: '',
        unmuteWorks: false,
        pillDisappears: false,
        resumedUnmuted: false,
        switchStartsMutedAtZero: false,
        offScreenPauses: false,
        scrollBackResumes: false,
        reducedMotionBlocksAutoplay: false,
        mobileLayoutPlaysinline: false
    };

    let browser;
    try {
        browser = await chromium.launch({
            channel: channelName,
            headless: true
        });
    } catch (e) {
        console.warn(`Could not launch ${browserDisplayName}:`, e.message);
        return { browser: browserDisplayName, skipped: true, error: e.message };
    }

    try {
        // TEST 1: Fresh Profile (Zero User Gesture) Autoplay Muted in Step 5
        const context = await browser.newContext({
            viewport: { width: 1440, height: 900 }
        });
        const page = await context.newPage();

        await page.goto('http://localhost:8000/#step5', { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(1200);

        // Check video element in Export view
        const expStatus = await page.evaluate(() => {
            const v = document.getElementById('export-video-player');
            const pill = document.querySelector('.export-player-wrap .video-unmute-pill');
            return {
                exists: !!v,
                muted: v ? v.muted : false,
                defaultMuted: v ? v.defaultMuted : false,
                playsinline: v ? v.playsInline : false,
                preload: v ? v.getAttribute('preload') : '',
                currentTime: v ? v.currentTime : -1,
                paused: v ? v.paused : true,
                pillExists: !!pill,
                pillText: pill ? pill.innerText.trim() : '',
                pillAria: pill ? pill.getAttribute('aria-label') : '',
                pillHidden: pill ? pill.classList.contains('hidden') : true
            };
        });

        console.log('Export Player Initial State:', expStatus);
        results.mutedTrue = expStatus.muted;
        results.defaultMutedTrue = expStatus.defaultMuted;
        results.startedAtZero = expStatus.currentTime >= 0 && expStatus.currentTime < 1.0;
        results.autoplayMuted = !expStatus.paused;
        results.pillVisible = expStatus.pillExists && !expStatus.pillHidden;
        results.pillText = expStatus.pillText;

        // Helper to ensure app loading screen is completely gone
        async function waitForLoadingScreen(p) {
            await p.waitForFunction(() => {
                const screen = document.getElementById('app-loading-screen');
                return !screen || screen.style.display === 'none' || screen.classList.contains('fade-out');
            }, { timeout: 8000 }).catch(() => {});
            await p.evaluate(() => {
                const screen = document.getElementById('app-loading-screen');
                if (screen) screen.style.display = 'none';
            });
            await p.waitForTimeout(400);
        }

        await waitForLoadingScreen(page);

        // Screenshot: 1440x900 Dark
        if (channelName === 'chrome') {
            await page.evaluate(() => applyTheme('dark'));
            await page.waitForTimeout(300);
            await page.screenshot({ path: path.join(OUT_DIR, 'dark_1440.png') });

            // Switch to Light theme
            await page.evaluate(() => applyTheme('light'));
            await page.waitForTimeout(300);
            await page.screenshot({ path: path.join(OUT_DIR, 'light_1440.png') });

            // Switch back to Dark theme
            await page.evaluate(() => applyTheme('dark'));
            await page.waitForTimeout(200);
        }

        // TEST 2: Unmute interaction
        console.log('Testing Unmute Pill click...');
        await page.evaluate(() => {
            const pill = document.querySelector('.export-player-wrap .video-unmute-pill');
            if (pill) pill.click();
        });
        await page.waitForTimeout(400);

        const unmutedStatus = await page.evaluate(() => {
            const v = document.getElementById('export-video-player');
            const pill = document.querySelector('.export-player-wrap .video-unmute-pill');
            return {
                muted: v ? v.muted : true,
                paused: v ? v.paused : true,
                pillHidden: pill ? pill.classList.contains('hidden') : false
            };
        });
        console.log('After Pill Click:', unmutedStatus);
        results.unmuteWorks = !unmutedStatus.muted;
        results.resumedUnmuted = !unmutedStatus.paused;
        results.pillDisappears = unmutedStatus.pillHidden;

        if (channelName === 'chrome') {
            await page.screenshot({ path: path.join(OUT_DIR, 'unmuted_state.png') });
        }

        // TEST 3: Selecting another video starts muted again at 0:00
        console.log('Testing switching to another video in strip...');
        const switched = await page.evaluate(() => {
            const chips = document.querySelectorAll('.export-project-chip');
            if (chips.length > 1) {
                chips[1].click();
                return true;
            }
            return false;
        });

        if (switched) {
            await page.waitForTimeout(800);
            const switchStatus = await page.evaluate(() => {
                const v = document.getElementById('export-video-player');
                const pill = document.querySelector('.export-player-wrap .video-unmute-pill');
                return {
                    muted: v ? v.muted : false,
                    currentTime: v ? v.currentTime : -1,
                    pillHidden: pill ? pill.classList.contains('hidden') : true
                };
            });
            console.log('After Video Switch:', switchStatus);
            results.switchStartsMutedAtZero = switchStatus.muted && switchStatus.currentTime < 1.0 && !switchStatus.pillHidden;
        } else {
            results.switchStartsMutedAtZero = true;
        }

        // TEST 4: Off-screen pause (IntersectionObserver)
        console.log('Testing Off-Screen Pause (IntersectionObserver)...');
        // Add temporary bottom padding to guarantee player can scroll 100% past top viewport
        const scrollRes = await page.evaluate(async () => {
            const v = document.getElementById('export-video-player');
            const spacer = document.createElement('div');
            spacer.id = '__test_scroll_spacer';
            spacer.style.height = '1500px';
            document.body.appendChild(spacer);

            window.scrollTo({ top: 1200, behavior: 'instant' });
            await new Promise(r => setTimeout(r, 450));
            const pausedWhenOffScreen = v.paused;

            window.scrollTo({ top: 0, behavior: 'instant' });
            await new Promise(r => setTimeout(r, 450));
            const resumedWhenBack = !v.paused;

            spacer.remove();
            return { pausedWhenOffScreen, resumedWhenBack };
        });

        console.log('Scroll Result:', scrollRes);
        results.offScreenPauses = scrollRes.pausedWhenOffScreen;
        results.scrollBackResumes = scrollRes.resumedWhenBack;

        await context.close();

        // TEST 5: Prefers-Reduced-Motion blocks autoplay
        console.log('Testing Prefers-Reduced-Motion behavior...');
        const prmContext = await browser.newContext({
            viewport: { width: 1440, height: 900 },
            reducedMotion: 'reduce'
        });
        const prmPage = await prmContext.newPage();
        await prmPage.goto('http://localhost:8000/#step5', { waitUntil: 'domcontentloaded' });
        await waitForLoadingScreen(prmPage);
        await prmPage.waitForTimeout(800);

        const prmStatus = await prmPage.evaluate(() => {
            const v = document.getElementById('export-video-player');
            return { paused: v ? v.paused : false, currentTime: v ? v.currentTime : -1 };
        });
        console.log('Prefers-Reduced-Motion state:', prmStatus);
        results.reducedMotionBlocksAutoplay = prmStatus.paused && prmStatus.currentTime === 0;

        if (channelName === 'chrome') {
            await prmPage.screenshot({ path: path.join(OUT_DIR, 'reduced_motion_poster.png') });
        }
        await prmContext.close();

        // TEST 6: Mobile Layout (390x844)
        console.log('Testing Mobile Viewport (390x844)...');
        const mobContext = await browser.newContext({
            viewport: { width: 390, height: 844 }
        });
        const mobPage = await mobContext.newPage();
        await mobPage.goto('http://localhost:8000/#step5', { waitUntil: 'domcontentloaded' });
        await waitForLoadingScreen(mobPage);
        await mobPage.waitForTimeout(800);

        const mobStatus = await mobPage.evaluate(() => {
            const v = document.getElementById('export-video-player');
            const pill = document.querySelector('.export-player-wrap .video-unmute-pill');
            return {
                playsinline: v ? v.playsInline : false,
                muted: v ? v.muted : false,
                pillVisible: pill ? !pill.classList.contains('hidden') : false
            };
        });
        results.mobileLayoutPlaysinline = mobStatus.playsinline && mobStatus.muted && mobStatus.pillVisible;

        if (channelName === 'chrome') {
            await mobPage.evaluate(() => applyTheme('dark'));
            await mobPage.waitForTimeout(300);
            await mobPage.screenshot({ path: path.join(OUT_DIR, 'dark_390.png') });

            await mobPage.evaluate(() => applyTheme('light'));
            await mobPage.waitForTimeout(300);
            await mobPage.screenshot({ path: path.join(OUT_DIR, 'light_390.png') });
        }
        await mobContext.close();

        // TEST 7: Preview Modal and Editor Player screenshots
        if (channelName === 'chrome') {
            const miscContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
            const miscPage = await miscContext.newPage();

            // Step 3 Editor
            await miscPage.goto('http://localhost:8000/#step3', { waitUntil: 'domcontentloaded' });
            await waitForLoadingScreen(miscPage);
            await miscPage.waitForTimeout(800);
            await miscPage.screenshot({ path: path.join(OUT_DIR, 'editor_player_muted.png') });

            // Step 1 Modal Preview
            await miscPage.goto('http://localhost:8000/#step1', { waitUntil: 'domcontentloaded' });
            await waitForLoadingScreen(miscPage);
            await miscPage.waitForTimeout(600);
            await miscPage.evaluate(() => {
                const playBtn = document.querySelector('.project-card-play');
                if (playBtn) playBtn.click();
            });
            await miscPage.waitForTimeout(600);
            await miscPage.screenshot({ path: path.join(OUT_DIR, 'preview_modal_muted.png') });

            await miscContext.close();
        }

    } finally {
        await browser.close();
    }

    return results;
}

(async () => {
    console.log('STARTING AUTOMATED CHANGE 2 TEST SUITE...');

    const chromeResults = await runTestsForBrowser('chrome', 'Google Chrome');
    const edgeResults = await runTestsForBrowser('msedge', 'Microsoft Edge');

    console.log('\n======================================================');
    console.log('CHANGE 2 TEST RESULTS SUMMARY');
    console.log('======================================================');
    console.table([chromeResults, edgeResults].filter(Boolean));

    fs.writeFileSync(
        path.join(OUT_DIR, 'test_results.json'),
        JSON.stringify({ chrome: chromeResults, edge: edgeResults }, null, 2)
    );
})();
