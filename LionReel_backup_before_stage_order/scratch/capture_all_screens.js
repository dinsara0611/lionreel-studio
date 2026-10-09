const { chromium } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');
const fs = require('fs');
const path = require('path');

const SCREENS = [
    { name: 'create_step1', step: 1 },
    { name: 'sources_step2', step: 2, wizardStage: 1 },
    { name: 'sources_step2_discovery', step: 2, wizardStage: 2 },
    { name: 'sources_step2_config', step: 2, wizardStage: 3 },
    { name: 'edit_step3', step: 3 },
    { name: 'render_step4', step: 4 },
    { name: 'export_step5', step: 5 }
];

async function capture() {
    const browser = await chromium.launch({
        channel: 'chrome',
        headless: true
    });

    const themes = ['dark', 'light'];
    const viewports = [
        { width: 1440, height: 900, suffix: '_1440' },
        { width: 390, height: 844, suffix: '_390' }
    ];

    for (const theme of themes) {
        for (const vp of viewports) {
            const context = await browser.newContext({
                viewport: { width: vp.width, height: vp.height }
            });
            const page = await context.newPage();

            await page.goto('http://localhost:8000');
            await page.waitForTimeout(1800); // wait for loading screen dismiss

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

            await page.waitForTimeout(500);

            // Capture each step
            for (const s of SCREENS) {
                await page.evaluate((item) => {
                    if (item.wizardStage && window.state) {
                        window.state.wizardStage = item.wizardStage;
                    }
                    if (typeof window.navigateToStep === 'function') {
                        window.navigateToStep(item.step);
                    }
                    if (item.wizardStage && typeof window.renderWizardStep === 'function') {
                        window.renderWizardStep();
                    }
                }, s);
                await page.waitForTimeout(600);

                const outPath = path.join('ui_audit', theme, `${s.name}${vp.suffix}.png`);
                await page.screenshot({ path: outPath, fullPage: false });
                console.log(`Saved: ${outPath}`);
            }

            // Capture Console State
            await page.evaluate(() => {
                if (typeof window.navigateToStep === 'function') window.navigateToStep(1);
            });
            await page.waitForTimeout(300);
            const consoleEl = await page.$('.terminal-container, .console-panel');
            if (consoleEl) {
                const outPath = path.join('ui_audit', theme, `console${vp.suffix}.png`);
                await consoleEl.screenshot({ path: outPath });
                console.log(`Saved: ${outPath}`);
            }

            // Capture Modal (Preview modal)
            try {
                await page.evaluate(() => {
                    if (typeof window.openPreviewModal === 'function' && window.CURATED_SOURCES) {
                        window.openPreviewModal(window.CURATED_SOURCES[0]);
                    }
                });
                await page.waitForTimeout(500);
                const modalPath = path.join('ui_audit', theme, `modal_preview${vp.suffix}.png`);
                await page.screenshot({ path: modalPath });
                console.log(`Saved: ${modalPath}`);
                // Close modal
                await page.evaluate(() => {
                    if (typeof window.closePreviewModal === 'function') window.closePreviewModal();
                });
            } catch (e) {}

            // Capture Toast State
            try {
                await page.evaluate(() => {
                    if (typeof window.showToast === 'function') {
                        window.showToast('Test Toast: Settings synchronized successfully.', 'success');
                    }
                });
                await page.waitForTimeout(400);
                const toastPath = path.join('ui_audit', theme, `toast${vp.suffix}.png`);
                await page.screenshot({ path: toastPath });
                console.log(`Saved: ${toastPath}`);
            } catch (e) {}

            await context.close();
        }
    }

    await browser.close();
    console.log('--- ALL AUDIT SCREENSHOTS CAPTURED ---');
}

capture().catch(err => {
    console.error('Audit Capture Error:', err);
    process.exit(1);
});
