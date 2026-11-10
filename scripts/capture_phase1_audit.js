const { chromium } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');
const fs = require('fs');
const path = require('path');

const UI_AUDIT_DIR = path.join(__dirname, '..', 'ui_audit');

async function runAuditCapture() {
    ['dark', 'light'].forEach(t => {
        const d = path.join(UI_AUDIT_DIR, t);
        if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
    });

    const browser = await chromium.launch({ channel: 'chrome', headless: true });

    for (const theme of ['dark', 'light']) {
        for (const vp of [{ name: '1440', w: 1440, h: 900 }, { name: '390', w: 390, h: 844 }]) {
            console.log(`Capturing ${theme} theme @ ${vp.name}px...`);
            const context = await browser.newContext({
                viewport: { width: vp.w, height: vp.h }
            });
            const page = await context.newPage();

            await page.goto('http://localhost:8000', { waitUntil: 'domcontentloaded' });
            await page.waitForTimeout(1000);

            // Set Theme
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
                localStorage.setItem('lionreel_theme', th);
            }, theme);
            await page.waitForTimeout(400);

            const outDir = path.join(UI_AUDIT_DIR, theme);

            // 1. Header & Theme Toggle
            const header = await page.$('.app-header');
            if (header) {
                await header.screenshot({ path: path.join(outDir, `header_theme_${vp.name}.png`) });
            }

            // 2. Step 1: Create Dashboard (Animal Cards, Hero, Recent Compilations)
            await page.evaluate(() => window.navigateToStep(1));
            await page.waitForTimeout(400);
            await page.screenshot({ path: path.join(outDir, `step1_create_animal_cards_${vp.name}.png`) });

            // 3. Step 2: Sources Screen (Discovery & Candidate clips)
            await page.evaluate(() => {
                window.state.wizardStage = 2;
                window.navigateToStep(2);
                window.renderWizardStep();
            });
            await page.waitForTimeout(500);
            await page.screenshot({ path: path.join(outDir, `step2_sources_${vp.name}.png`) });

            // 4. Step 3: Configure Video (4 sections, 11 Quality filters, Summary Bar)
            await page.evaluate(() => {
                window.state.wizardStage = 3;
                window.navigateToStep(2);
                window.renderWizardStep();
            });
            await page.waitForTimeout(500);
            await page.screenshot({ path: path.join(outDir, `step3_edit_config_${vp.name}.png`) });

            // Summary Bar element
            const sumBar = await page.$('#wizard-dynamic-summary');
            if (sumBar) {
                await sumBar.screenshot({ path: path.join(outDir, `step3_summary_bar_${vp.name}.png`) });
            }

            // 5. Step 4: Review Reel & Launch / Render Screen
            await page.evaluate(() => {
                window.state.wizardStage = 4;
                window.navigateToStep(2);
                window.renderWizardStep();
            });
            await page.waitForTimeout(500);
            await page.screenshot({ path: path.join(outDir, `step4_review_reel_${vp.name}.png`) });

            // Render view (Step 4 in top stepper)
            await page.evaluate(() => window.navigateToStep(4));
            await page.waitForTimeout(500);
            await page.screenshot({ path: path.join(outDir, `step4_render_progress_${vp.name}.png`) });

            // Render with candidate audit table
            await page.evaluate(() => {
                if (window.renderCandidateReportsTable) {
                    window.renderCandidateReportsTable([
                        { candidate: 1, source: 'cache_ByH9LuSILxU.mp4', pet_ratio: 0.5, horiz_ratio: 1.0, vert_ratio: 1.0, size_ratio: 0.8, sharpness: 608.8, score: 0.80, actual_score: null, result: 'REJECT', reason: 'PREDICTED_BAD_FRAMING (Score: 80.0% < 88%)', measured: true, start_s: 119.4, dur_s: 10.0, clip_id: 'c1' },
                        { candidate: 2, source: 'cache_ByH9LuSILxU.mp4', pet_ratio: 1.0, horiz_ratio: 1.0, vert_ratio: 1.0, size_ratio: 0.9, sharpness: 1456.9, score: 0.90, actual_score: null, result: 'PASS', reason: 'PREDICT_PASS', measured: true, start_s: 94.4, dur_s: 10.0, clip_id: 'c2' },
                        { candidate: 3, source: 'cache_ByH9LuSILxU.mp4', pet_ratio: 1.0, horiz_ratio: 1.0, vert_ratio: 1.0, size_ratio: 1.0, sharpness: 2232.5, score: 0.90, actual_score: null, result: 'PASS', reason: 'PREDICT_PASS', measured: true, start_s: 189.4, dur_s: 10.0, clip_id: 'c3' },
                        { candidate: 6, source: 'cache_ByH9LuSILxU.mp4', pet_ratio: null, horiz_ratio: null, vert_ratio: null, size_ratio: null, sharpness: null, score: null, actual_score: null, result: 'REJECT', reason: 'WATERMARK (bottom_left: WOA Network logo)', measured: false, start_s: 0.0, dur_s: 10.0, clip_id: 'c6' }
                    ]);
                }
            });
            await page.waitForTimeout(400);
            await page.screenshot({ path: path.join(outDir, `step4_render_failed_audit_${vp.name}.png`) });

            // 6. Step 5: Export View (Ready for Upload, social links, credits)
            await page.evaluate(() => window.navigateToStep(5));
            await page.waitForTimeout(500);
            await page.screenshot({ path: path.join(outDir, `step5_export_${vp.name}.png`) });

            // 7. Modals
            // Shortcuts Modal
            await page.evaluate(() => {
                const sm = document.getElementById('shortcuts-modal');
                if (sm) sm.classList.add('active');
            });
            await page.waitForTimeout(200);
            await page.screenshot({ path: path.join(outDir, `modal_shortcuts_${vp.name}.png`) });
            await page.evaluate(() => {
                const sm = document.getElementById('shortcuts-modal');
                if (sm) sm.classList.remove('active');
            });

            // Confirm Modal
            await page.evaluate(() => {
                const cm = document.getElementById('confirm-modal');
                if (cm) cm.classList.add('active');
            });
            await page.waitForTimeout(200);
            await page.screenshot({ path: path.join(outDir, `modal_confirm_${vp.name}.png`) });
            await page.evaluate(() => {
                const cm = document.getElementById('confirm-modal');
                if (cm) cm.classList.remove('active');
            });

            // Toast notification
            await page.evaluate(() => {
                if (window.showToast) {
                    window.showToast('LionReel Studio: Workspace synchronization complete', 'success');
                }
            });
            await page.waitForTimeout(200);
            await page.screenshot({ path: path.join(outDir, `toast_notification_${vp.name}.png`) });

            await context.close();
        }
    }

    await browser.close();
    console.log('Phase 1 Screenshots successfully captured into ui_audit/dark and ui_audit/light!');
}

runAuditCapture().catch(err => {
    console.error('Audit Capture Error:', err);
    process.exit(1);
});
