const { chromium } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');
const path = require('path');

async function main() {
    const browser = await chromium.launch({ channel: 'chrome', headless: true });

    for (const theme of ['dark', 'light']) {
        const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
        await page.goto('http://localhost:8000');
        await page.waitForTimeout(1600);

        // Switch theme
        await page.evaluate((th) => {
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
        }, theme);

        // Navigate to Step 2 Sources
        await page.click('#step-btn-2');
        await page.waitForTimeout(500);

        // Click next twice to advance to Stage 3 (Configure)
        await page.click('#btn-wizard-next');
        await page.waitForTimeout(400);
        await page.click('#btn-wizard-next');
        await page.waitForTimeout(600);

        const outPath = path.join('ui_audit', theme, 'stage3_configure_1440.png');
        await page.screenshot({ path: outPath, fullPage: false });
        console.log(`Saved: ${outPath}`);

        // Also take full-page screenshot to see the whole configure panel
        const outFull = path.join('ui_audit', theme, 'stage3_configure_full.png');
        await page.screenshot({ path: outFull, fullPage: true });
        console.log(`Saved full: ${outFull}`);

        await page.close();
    }

    await browser.close();
}

main().catch(console.error);
