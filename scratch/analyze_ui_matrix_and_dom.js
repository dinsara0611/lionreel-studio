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
    console.log('--- Running Deep DOM & Control Matrix Analysis ---');

    const browser = await chromium.launch({ channel: 'chrome', headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

    await page.goto(`${BASE_URL}/#step1`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#app-loading-screen', { state: 'hidden', timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(500);

    async function goToStep(s) {
        await page.evaluate((step) => {
            if (window.navigateToStep) {
                window.navigateToStep(step);
            } else if (window.switchWorkflowStep) {
                window.switchWorkflowStep(step);
            }
        }, s);
        await page.waitForTimeout(400);
    }

    // 1. Capture screenshots for dark & light at 1440 and 390
    for (const theme of ['dark', 'light']) {
        await page.evaluate((th) => window.applyTheme ? window.applyTheme(th) : document.documentElement.setAttribute('data-theme', th), theme);
        await page.waitForTimeout(300);

        for (const width of [1440, 390]) {
            const height = (width === 1440) ? 900 : 844;
            await page.setViewportSize({ width, height });
            const sub = `${theme}/${width}`;
            console.log(`\nCapturing distinct views for ${sub}...`);

            // Step 1: Create
            await goToStep(1);
            await page.waitForSelector('#view-dashboard', { state: 'visible' });
            await page.waitForTimeout(300);
            await page.screenshot({ path: path.join(OUT_DIR, sub, 'step1_create.png') });
            await page.screenshot({ path: path.join(OUT_DIR, sub, 'state_idle.png') });

            // Step 2: Sources
            await goToStep(2);
            await page.waitForSelector('#view-wizard', { state: 'visible' });
            await page.waitForTimeout(300);
            await page.screenshot({ path: path.join(OUT_DIR, sub, 'step2_sources.png') });

            // Step 3: Configure/Edit
            await goToStep(3);
            await page.waitForSelector('#view-editor', { state: 'visible' });
            await page.waitForTimeout(300);
            await page.screenshot({ path: path.join(OUT_DIR, sub, 'step3_edit.png') });

            // Step 4: Render
            await goToStep(4);
            await page.waitForSelector('#view-render', { state: 'visible' });
            await page.waitForTimeout(300);
            await page.screenshot({ path: path.join(OUT_DIR, sub, 'step4_render.png') });

            // State: Running (Step 4 running simulation)
            await page.evaluate(() => {
                const pbar = document.getElementById('render-progress-bar');
                const ptext = document.getElementById('render-progress-text');
                const stitle = document.getElementById('current-stage-title');
                if (pbar) pbar.style.width = '62%';
                if (ptext) ptext.textContent = '62%';
                if (stitle) stitle.textContent = 'Stage 4: Subject-Tracking Pet Reframing (62%)';
                const term = document.getElementById('terminal-body');
                if (term) term.innerHTML += '<div class="log-line info">[SEQ:42] [12:34:56] [INFO] Processing Clip 2/4: cache_SB-qEYVdvXA.mp4 (Tracking: 95.2%)</div>';
            });
            await page.waitForTimeout(200);
            await page.screenshot({ path: path.join(OUT_DIR, sub, 'state_running.png') });

            // State: Failed (Step 4 failure simulation)
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
            await page.waitForTimeout(200);
            await page.screenshot({ path: path.join(OUT_DIR, sub, 'state_failed.png') });

            // Step 5: Export / Success
            await goToStep(5);
            await page.waitForSelector('#view-export', { state: 'visible' });
            await page.waitForTimeout(300);
            await page.screenshot({ path: path.join(OUT_DIR, sub, 'step5_export.png') });
            await page.screenshot({ path: path.join(OUT_DIR, sub, 'state_success.png') });

            // State: Empty pool
            await goToStep(1);
            await page.waitForSelector('#view-dashboard', { state: 'visible' });
            await page.evaluate(() => {
                const alert = document.getElementById('low-pool-alert');
                if (alert) alert.style.display = 'block';
                const bar = document.getElementById('pool-usage-bar');
                if (bar) { bar.style.width = '2%'; bar.style.background = '#EF4444'; }
                const txt = document.getElementById('pool-clips-used');
                if (txt) txt.textContent = '0 / 12 Active (Pool Empty)';
            });
            await page.waitForTimeout(200);
            await page.screenshot({ path: path.join(OUT_DIR, sub, 'state_empty_pool.png') });

            // State: Toast
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
            await page.waitForTimeout(300);
            await page.screenshot({ path: path.join(OUT_DIR, sub, 'state_toast.png') });

            // Modals: Preview modal
            await page.evaluate(() => {
                const m = document.getElementById('modal-video-preview');
                if (m) { m.classList.add('active'); m.style.display = 'flex'; }
            });
            await page.waitForTimeout(200);
            await page.screenshot({ path: path.join(OUT_DIR, sub, 'modal_preview.png') });

            // Modals: Shortcuts modal
            await page.evaluate(() => {
                const m1 = document.getElementById('modal-video-preview');
                if (m1) { m1.classList.remove('active'); m1.style.display = 'none'; }
                const m2 = document.getElementById('modal-shortcuts');
                if (m2) { m2.classList.add('active'); m2.style.display = 'flex'; }
            });
            await page.waitForTimeout(200);
            await page.screenshot({ path: path.join(OUT_DIR, sub, 'modal_shortcuts.png') });

            // Reset modal state
            await page.evaluate(() => {
                const m2 = document.getElementById('modal-shortcuts');
                if (m2) { m2.classList.remove('active'); m2.style.display = 'none'; }
            });
        }
    }

    // 2. Comprehensive Interactive Elements Inventory
    console.log('\n--- Extracting All Interactive Controls Across Views ---');
    await page.setViewportSize({ width: 1440, height: 900 });
    await goToStep(1);

    const controlInventory = await page.evaluate(() => {
        const results = [];
        const views = [
            { step: 'Global Header', id: 'app-header', sel: '.app-header *' },
            { step: 'Step 1: Create', id: 'view-dashboard', sel: '#view-dashboard *' },
            { step: 'Step 2: Sources', id: 'view-wizard', sel: '#view-wizard *' },
            { step: 'Step 3: Configure', id: 'view-editor', sel: '#view-editor *' },
            { step: 'Step 4: Render', id: 'view-render', sel: '#view-render *' },
            { step: 'Step 5: Export', id: 'view-export', sel: '#view-export *' },
            { step: 'Modals', id: 'modals', sel: '.modal *' }
        ];

        const seen = new Set();

        views.forEach(v => {
            const container = v.id === 'modals' ? document.body : (v.id === 'app-header' ? document.querySelector('.app-header') : document.getElementById(v.id));
            if (!container) return;

            const elements = container.querySelectorAll('button, input, select, textarea, .chip, [role="button"], a[href]');
            elements.forEach(el => {
                const id = el.id || el.getAttribute('data-id') || el.className;
                const key = `${v.step}::${id}::${el.tagName}`;
                if (seen.has(key)) return;
                seen.add(key);

                const tag = el.tagName.toLowerCase();
                const type = el.type || tag;
                const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || el.title || '').trim().replace(/\n+/g, ' ').slice(0, 50);
                const isVisible = el.offsetParent !== null;
                const name = el.name || '';
                const onclick = el.getAttribute('onclick') || '';

                results.push({
                    step: v.step,
                    tag,
                    type,
                    id: el.id || '',
                    className: el.className || '',
                    text,
                    onclick,
                    name,
                    value: el.value || '',
                    checked: el.checked || false,
                    disabled: el.disabled || false,
                    isVisible
                });
            });
        });

        return results;
    });

    console.log(`Extracted ${controlInventory.length} controls.`);
    fs.writeFileSync(path.join(OUT_DIR, 'controls_raw.json'), JSON.stringify(controlInventory, null, 2));

    // 3. Visual and Typography Audit
    console.log('\n--- Checking Typography, Alignment & Contrast ---');
    const visualAudit = await page.evaluate(() => {
        const smallFonts = [];
        const all = document.querySelectorAll('*');

        all.forEach(el => {
            if (el.children.length === 0 && el.innerText && el.innerText.trim().length > 0) {
                const style = window.getComputedStyle(el);
                const fontSize = parseFloat(style.fontSize);
                if (fontSize < 12) {
                    smallFonts.push({
                        tag: el.tagName,
                        id: el.id,
                        className: el.className,
                        text: el.innerText.trim().slice(0, 30),
                        fontSize: `${fontSize}px`,
                        parent: el.parentElement ? el.parentElement.className : ''
                    });
                }
            }
        });

        const stepper = document.querySelector('.workflow-stepper');
        let stepperCollision = null;
        if (stepper) {
            const sRect = stepper.getBoundingClientRect();
            const headings = document.querySelectorAll('h1, h2, h3');
            const colliding = [];
            headings.forEach(h => {
                const hRect = h.getBoundingClientRect();
                if (hRect.top < sRect.bottom && hRect.bottom > sRect.top && hRect.left < sRect.right && hRect.right > sRect.left) {
                    colliding.push(h.innerText.trim());
                }
            });
            stepperCollision = {
                stepperRect: { top: sRect.top, bottom: sRect.bottom, height: sRect.height },
                collidingHeadings: colliding
            };
        }

        return {
            smallFontsCount: smallFonts.length,
            smallFonts: smallFonts.slice(0, 30),
            stepperCollision
        };
    });

    fs.writeFileSync(path.join(OUT_DIR, 'visual_audit.json'), JSON.stringify(visualAudit, null, 2));

    await browser.close();
    console.log('--- Deep DOM Analysis Finished Successfully ---');
}

run().catch(e => {
    console.error('Error during deep analysis:', e);
    process.exit(1);
});
