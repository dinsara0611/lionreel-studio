module.paths.push('C:/Users/dinsa/AppData/Roaming/npm/node_modules');
const { chromium } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'http://localhost:8000';

async function run() {
    console.log('--- Running Deep State & Concurrency Checks ---');
    const browser = await chromium.launch({ channel: 'chrome', headless: true });

    const results = {};

    // Check 1: API Status endpoint when idle
    const page1 = await browser.newPage();
    await page1.goto(`${BASE_URL}/api/status`);
    const statusIdleText = await page1.textContent('body');
    const statusIdle = JSON.parse(statusIdleText);
    results.statusEndpointIdle = statusIdle;
    console.log('Status Idle:', statusIdle.status, 'Job ID:', statusIdle.job_id);

    // Check 2: Two tabs simultaneous sync
    const page2 = await browser.newPage();
    await page1.goto(`${BASE_URL}/#step1`);
    await page2.goto(`${BASE_URL}/#step1`);
    await page1.waitForTimeout(500);
    await page2.waitForTimeout(500);

    const themeTab1 = await page1.evaluate(() => document.documentElement.getAttribute('data-theme'));
    const themeTab2 = await page2.evaluate(() => document.documentElement.getAttribute('data-theme'));
    results.twoTabThemeSync = (themeTab1 === themeTab2);
    console.log(`Two tabs theme match: ${results.twoTabThemeSync} (${themeTab1} vs ${themeTab2})`);

    // Check 3: Process check
    const pageApi = await browser.newPage();
    await pageApi.goto(`${BASE_URL}/api/finished`);
    const finishedData = JSON.parse(await pageApi.textContent('body'));
    const files = finishedData.files || [];
    results.finishedFilesCount = files.length;
    console.log(`Finished files count from /api/finished: ${files.length}`);

    // Check 4: Inspect card values vs real files
    const cardAudit = [];
    for (const item of files.slice(0, 10)) {
        if (item.type === 'video') {
            cardAudit.push({
                filename: item.name,
                apiDuration: item.duration,
                apiExpectedDuration: item.expected_duration_s,
                apiClipCount: item.clip_count,
                apiSizeBytes: item.sizeBytes,
                apiSizeMB: (item.sizeBytes / (1024 * 1024)).toFixed(2) + ' MB',
                apiThumbnail: item.thumbnail,
                aspectRatio: item.aspectRatio
            });
        }
    }
    results.recentVideosAudit = cardAudit;

    fs.writeFileSync(path.resolve('analysis/state_checks_summary.json'), JSON.stringify(results, null, 2));
    console.log('Saved state_checks_summary.json with', cardAudit.length, 'video entries.');

    await browser.close();
    console.log('--- State Checks Complete ---');
}

run().catch(e => {
    console.error('State check failed:', e);
    process.exit(1);
});
