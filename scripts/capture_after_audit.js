const { chromium } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');
const fs = require('fs');
const path = require('path');

const UI_AUDIT_DIR = path.join(__dirname, '..', 'ui_audit');
const BEFORE_AFTER_DIR = path.join(UI_AUDIT_DIR, 'BEFORE_AFTER');

async function runAfterCapture() {
    ['dark', 'light'].forEach(t => {
        const dBefore = path.join(BEFORE_AFTER_DIR, 'before', t);
        const dAfter = path.join(BEFORE_AFTER_DIR, 'after', t);
        if (!fs.existsSync(dBefore)) fs.mkdirSync(dBefore, { recursive: true });
        if (!fs.existsSync(dAfter)) fs.mkdirSync(dAfter, { recursive: true });
        
        // Copy initial Phase 1 audit captures into before directory
        const origDir = path.join(UI_AUDIT_DIR, t);
        if (fs.existsSync(origDir)) {
            const files = fs.readdirSync(origDir);
            for (const f of files) {
                if (f.endsWith('.png')) {
                    fs.copyFileSync(path.join(origDir, f), path.join(dBefore, f));
                }
            }
        }
    });

    const browser = await chromium.launch({ channel: 'chrome', headless: true });

    const capturedKeys = [];

    for (const theme of ['dark', 'light']) {
        for (const vp of [{ name: '1440', w: 1440, h: 900 }, { name: '390', w: 390, h: 844 }]) {
            console.log(`Capturing polished ${theme} theme @ ${vp.name}px...`);
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

            const outDir = path.join(BEFORE_AFTER_DIR, 'after', theme);

            // 1. Header & Theme Toggle
            const header = await page.$('.app-header');
            if (header) {
                const fn = `header_theme_${vp.name}.png`;
                await header.screenshot({ path: path.join(outDir, fn) });
                if (!capturedKeys.includes(`header_theme_${vp.name}`)) capturedKeys.push(`header_theme_${vp.name}`);
            }

            // 2. Step 1: Create Dashboard
            await page.evaluate(() => window.navigateToStep(1));
            await page.waitForTimeout(400);
            const fnStep1 = `step1_create_animal_cards_${vp.name}.png`;
            await page.screenshot({ path: path.join(outDir, fnStep1) });
            if (!capturedKeys.includes(`step1_create_animal_cards_${vp.name}`)) capturedKeys.push(`step1_create_animal_cards_${vp.name}`);

            // 3. Step 2: Sources Screen
            await page.evaluate(() => {
                window.state.wizardStage = 2;
                window.navigateToStep(2);
                window.renderWizardStep();
            });
            await page.waitForTimeout(500);
            const fnStep2 = `step2_sources_${vp.name}.png`;
            await page.screenshot({ path: path.join(outDir, fnStep2) });
            if (!capturedKeys.includes(`step2_sources_${vp.name}`)) capturedKeys.push(`step2_sources_${vp.name}`);

            // 4. Step 3: Configure Video & Summary Bar
            await page.evaluate(() => {
                window.state.wizardStage = 3;
                window.navigateToStep(2);
                window.renderWizardStep();
            });
            await page.waitForTimeout(500);
            const fnStep3 = `step3_edit_config_${vp.name}.png`;
            await page.screenshot({ path: path.join(outDir, fnStep3) });
            if (!capturedKeys.includes(`step3_edit_config_${vp.name}`)) capturedKeys.push(`step3_edit_config_${vp.name}`);

            const sumBar = await page.$('#wizard-dynamic-summary');
            if (sumBar) {
                const fnSum = `step3_summary_bar_${vp.name}.png`;
                await sumBar.screenshot({ path: path.join(outDir, fnSum) });
                if (!capturedKeys.includes(`step3_summary_bar_${vp.name}`)) capturedKeys.push(`step3_summary_bar_${vp.name}`);
            }

            // 5. Step 4: Render Screen
            await page.evaluate(() => window.navigateToStep(4));
            await page.waitForTimeout(500);
            const fnRender = `step4_render_progress_${vp.name}.png`;
            await page.screenshot({ path: path.join(outDir, fnRender) });
            if (!capturedKeys.includes(`step4_render_progress_${vp.name}`)) capturedKeys.push(`step4_render_progress_${vp.name}`);

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
            const fnAudit = `step4_render_failed_audit_${vp.name}.png`;
            await page.screenshot({ path: path.join(outDir, fnAudit) });
            if (!capturedKeys.includes(`step4_render_failed_audit_${vp.name}`)) capturedKeys.push(`step4_render_failed_audit_${vp.name}`);

            // 6. Step 5: Export View
            await page.evaluate(() => window.navigateToStep(5));
            await page.waitForTimeout(500);
            const fnExport = `step5_export_${vp.name}.png`;
            await page.screenshot({ path: path.join(outDir, fnExport) });
            if (!capturedKeys.includes(`step5_export_${vp.name}`)) capturedKeys.push(`step5_export_${vp.name}`);

            // 7. Modals & Toasts
            await page.evaluate(() => {
                const sm = document.getElementById('modal-shortcuts');
                if (sm) sm.style.display = 'flex';
            });
            await page.waitForTimeout(200);
            const fnShortcuts = `modal_shortcuts_${vp.name}.png`;
            await page.screenshot({ path: path.join(outDir, fnShortcuts) });
            if (!capturedKeys.includes(`modal_shortcuts_${vp.name}`)) capturedKeys.push(`modal_shortcuts_${vp.name}`);
            await page.evaluate(() => {
                const sm = document.getElementById('modal-shortcuts');
                if (sm) sm.style.display = 'none';
            });

            await page.evaluate(() => {
                const cm = document.getElementById('modal-confirm');
                if (cm) cm.style.display = 'flex';
            });
            await page.waitForTimeout(200);
            const fnConfirm = `modal_confirm_${vp.name}.png`;
            await page.screenshot({ path: path.join(outDir, fnConfirm) });
            if (!capturedKeys.includes(`modal_confirm_${vp.name}`)) capturedKeys.push(`modal_confirm_${vp.name}`);
            await page.evaluate(() => {
                const cm = document.getElementById('modal-confirm');
                if (cm) cm.style.display = 'none';
            });

            await page.evaluate(() => {
                if (window.showToast) {
                    window.showToast('LionReel Studio: Workspace synchronization complete', 'success');
                }
            });
            await page.waitForTimeout(200);
            const fnToast = `toast_notification_${vp.name}.png`;
            await page.screenshot({ path: path.join(outDir, fnToast) });
            if (!capturedKeys.includes(`toast_notification_${vp.name}`)) capturedKeys.push(`toast_notification_${vp.name}`);

            await context.close();
        }
    }

    await browser.close();

    // Generate BEFORE_AFTER HTML visual gallery
    const galleryHtml = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>LionReel Studio — Visual Polish Before &amp; After Gallery</title>
    <style>
        :root {
            --bg: #07130c;
            --surface: #0c1f14;
            --border: #143823;
            --text: #e6f4ec;
            --accent: #18e87a;
            --text-muted: #84a993;
            --font: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        body {
            margin: 0;
            padding: 32px 24px;
            background: var(--bg);
            color: var(--text);
            font-family: var(--font);
        }
        .header {
            max-width: 1400px;
            margin: 0 auto 32px auto;
            border-bottom: 1px solid var(--border);
            padding-bottom: 20px;
        }
        h1 { margin: 0 0 8px 0; font-size: 1.8rem; color: #fff; }
        h1 span { color: var(--accent); }
        p { margin: 0; color: var(--text-muted); font-size: 0.95rem; }
        .gallery-grid {
            max-width: 1400px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 40px;
        }
        .comparison-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
        }
        .card-title {
            font-size: 1.15rem;
            font-weight: 700;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .badge {
            background: rgba(24, 232, 122, 0.15);
            color: var(--accent);
            border: 1px solid rgba(24, 232, 122, 0.3);
            border-radius: 9999px;
            padding: 2px 10px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .side-by-side {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }
        .col {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .col-label {
            font-size: 0.8rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
        }
        .col-label.after {
            color: var(--accent);
        }
        .img-wrap {
            background: #000;
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        img {
            max-width: 100%;
            height: auto;
            display: block;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>LionReel <span>Studio</span> — Visual Consistency &amp; Icon Polish Gallery</h1>
        <p>Comprehensive side-by-side comparison across desktop (1440×900) and mobile (390×844) in both Dark and Light themes. Zero emojis in interface chrome; vendored Lucide SVG icons; unified design tokens.</p>
    </div>

    <div class="gallery-grid">
        ${capturedKeys.map(key => {
            const label = key.replace(/_/g, ' ').toUpperCase();
            return `
            <div class="comparison-card">
                <div class="card-title">
                    <span>${label}</span>
                    <span class="badge">Dark &amp; Light Audited</span>
                </div>
                <h4 style="margin: 0 0 10px 0; color: var(--text-muted); font-size: 0.9rem;">Dark Theme</h4>
                <div class="side-by-side">
                    <div class="col">
                        <span class="col-label">Before (Audit Baseline)</span>
                        <div class="img-wrap">
                            <img src="before/dark/${key}.png" alt="Before ${key} Dark" loading="lazy" onerror="this.parentElement.innerHTML='<span style=\\'padding:20px;color:#888;\\'>Baseline not present</span>'">
                        </div>
                    </div>
                    <div class="col">
                        <span class="col-label after">After (Polished Unified Lucide Icons &amp; Tokens)</span>
                        <div class="img-wrap">
                            <img src="after/dark/${key}.png" alt="After ${key} Dark" loading="lazy">
                        </div>
                    </div>
                </div>

                <h4 style="margin: 24px 0 10px 0; color: var(--text-muted); font-size: 0.9rem;">Light Theme</h4>
                <div class="side-by-side">
                    <div class="col">
                        <span class="col-label">Before (Audit Baseline)</span>
                        <div class="img-wrap">
                            <img src="before/light/${key}.png" alt="Before ${key} Light" loading="lazy" onerror="this.parentElement.innerHTML='<span style=\\'padding:20px;color:#888;\\'>Baseline not present</span>'">
                        </div>
                    </div>
                    <div class="col">
                        <span class="col-label after">After (Polished Unified Lucide Icons &amp; Tokens)</span>
                        <div class="img-wrap">
                            <img src="after/light/${key}.png" alt="After ${key} Light" loading="lazy">
                        </div>
                    </div>
                </div>
            </div>
            `;
        }).join('\n')}
    </div>
</body>
</html>
`;

    fs.writeFileSync(path.join(BEFORE_AFTER_DIR, 'index.html'), galleryHtml, 'utf-8');
    console.log('BEFORE_AFTER Gallery successfully generated at ui_audit/BEFORE_AFTER/index.html!');
}

runAfterCapture().catch(err => {
    console.error('After Capture Error:', err);
    process.exit(1);
});
