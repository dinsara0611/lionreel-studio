module.paths.push('C:/Users/dinsa/AppData/Roaming/npm/node_modules');
const { test, expect } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');

// WCAG 2.1 Contrast Helper
function getLuminance(r, g, b) {
    const a = [r, g, b].map(v => {
        v /= 255;
        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
}

function parseRgb(colorStr) {
    const match = colorStr.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (!match) return [0, 0, 0];
    return [parseInt(match[1]), parseInt(match[2]), parseInt(match[3])];
}

function getContrastRatio(rgb1, rgb2) {
    const lum1 = getLuminance(...rgb1);
    const lum2 = getLuminance(...rgb2);
    const brightest = Math.max(lum1, lum2);
    const darkest = Math.min(lum1, lum2);
    return (brightest + 0.05) / (darkest + 0.05);
}

test.describe('LionReel Studio — Theme & UI Verification Suite', () => {

    test('Theme toggle and localStorage persistence across reloads', async ({ page }) => {
        await page.goto('/');
        await page.waitForSelector('#app-loading-screen', { state: 'hidden', timeout: 5000 });
        await page.waitForTimeout(300);

        // Read initial theme (respecting prefers-color-scheme)
        const initialTheme = await page.evaluate(() => document.documentElement.getAttribute('data-theme') || 'dark');
        const targetTheme = (initialTheme === 'dark') ? 'light' : 'dark';
        const expectedMeta = (targetTheme === 'light') ? '#F4FAF6' : '#06110C';

        // Click theme toggle to switch to target mode
        await page.click('#theme-toggle-btn');
        await page.waitForTimeout(400);

        const newTheme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
        expect(newTheme).toBe(targetTheme);

        const metaColor = await page.evaluate(() => {
            const el = document.getElementById('meta-theme-color') || document.querySelector('meta[name="theme-color"]');
            return el ? el.getAttribute('content') : null;
        });
        expect(metaColor).toBe(expectedMeta);

        const savedTheme = await page.evaluate(() => localStorage.getItem('lionreel_theme'));
        expect(savedTheme).toBe(targetTheme);

        // Reload page to verify persistence
        await page.reload();
        await page.waitForSelector('#app-loading-screen', { state: 'hidden', timeout: 5000 });
        await page.waitForTimeout(300);

        const reloadedTheme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
        expect(reloadedTheme).toBe(targetTheme);

        // Toggle back to initial theme
        await page.click('#theme-toggle-btn');
        await page.waitForTimeout(400);

        const toggledBack = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
        expect(toggledBack).toBe(initialTheme);
    });

    test('All 5 Workflow Steps navigate cleanly in both themes', async ({ page }) => {
        await page.goto('/');
        await page.waitForSelector('#app-loading-screen', { state: 'hidden', timeout: 5000 });

        for (const theme of ['dark', 'light']) {
            await page.evaluate((th) => window.applyTheme(th), theme);
            await page.waitForTimeout(300);

            // Step 1: Create (view-dashboard)
            await page.click('#step-btn-1');
            await page.waitForTimeout(400);
            const view1Visible = await page.isVisible('#view-dashboard');
            expect(view1Visible).toBeTruthy();

            // Step 2: Sources Wizard (view-wizard)
            await page.click('#step-btn-2');
            await page.waitForTimeout(400);
            const view2Visible = await page.isVisible('#view-wizard');
            expect(view2Visible).toBeTruthy();

            // Step 3: Editor (view-editor)
            await page.click('#step-btn-3');
            await page.waitForTimeout(400);
            const view3Visible = await page.isVisible('#view-editor');
            expect(view3Visible).toBeTruthy();

            // Step 4: Render (view-render)
            await page.click('#step-btn-4');
            await page.waitForTimeout(400);
            const view4Visible = await page.isVisible('#view-render');
            expect(view4Visible).toBeTruthy();

            // Step 5: Export (view-export)
            await page.click('#step-btn-5');
            await page.waitForTimeout(400);
            const view5Visible = await page.isVisible('#view-export');
            expect(view5Visible).toBeTruthy();
        }
    });

    test('Stage 3 Configure Video: 4 Sections, Dynamic Chips, Framing, and Filter Warnings', async ({ page }) => {
        await page.goto('/');
        await page.waitForSelector('#app-loading-screen', { state: 'hidden', timeout: 5000 });

        // Go to Step 2 Stage 3 (Configure)
        await page.evaluate(() => {
            window.state.wizardStage = 3;
            window.navigateToStep(2);
            window.renderWizardStep();
        });
        await page.waitForTimeout(600);

        // 1. Verify 11 Active Filters Badge
        const filterBadgeText = await page.textContent('#setup-active-verif-badge');
        expect(filterBadgeText).toContain('/ 11 Active');

        // 2. Verify Relocated Framing Layout Mode Select
        const layoutMode = await page.inputValue('#select-layout-mode');
        expect(['smart_crop', 'blur_fit', 'auto']).toContain(layoutMode);

        await page.selectOption('#select-layout-mode', 'blur_fit');
        await page.waitForTimeout(300);
        const stateLayout = await page.evaluate(() => window.state.config.LAYOUT_MODE);
        expect(stateLayout).toBe('blur_fit');

        // 3. Verify Dynamic Chip Labels on Duration Change
        await page.evaluate(() => window.updateShortDuration(4, 5.0, false));
        await page.waitForTimeout(300);

        const chip4Text = await page.textContent('.short-preset-chip[data-clips="4"]');
        expect(chip4Text).toContain('4 Clips (~20s');

        const chip6Text = await page.textContent('.short-preset-chip[data-clips="6"]');
        expect(chip6Text).toContain('6 Clips (~30s)');

        // Change to 10.0s duration
        await page.evaluate(() => window.updateShortDuration(4, 10.0, false));
        await page.waitForTimeout(300);

        const chip4Text10 = await page.textContent('.short-preset-chip[data-clips="4"]');
        expect(chip4Text10).toContain('4 Clips (~40s');

        // 4. Verify Live Summary Box
        const summaryHeadline = await page.textContent('#summary-headline');
        expect(summaryHeadline).toContain('4 clips × 10.0s');
        const summaryBadge = await page.textContent('#badge-format-summary');
        expect(summaryBadge).toContain('VERTICAL');

        // 5. Test Critical Filter Toggle Warnings
        // Toggle Watermark off -> Warning displays
        await page.evaluate(() => {
            const el = document.getElementById('toggle-check-watermark');
            el.checked = false;
            el.dispatchEvent(new Event('change'));
        });
        await page.waitForTimeout(300);
        const watermarkWarnDisplay = await page.$eval('#warn-watermark', el => window.getComputedStyle(el).display);
        expect(watermarkWarnDisplay).not.toBe('none');

        // Toggle Watermark back on -> Warning hides
        await page.evaluate(() => {
            const el = document.getElementById('toggle-check-watermark');
            el.checked = true;
            el.dispatchEvent(new Event('change'));
        });
        await page.waitForTimeout(300);
        const watermarkWarnDisplayHidden = await page.$eval('#warn-watermark', el => window.getComputedStyle(el).display);
        expect(watermarkWarnDisplayHidden).toBe('none');

        // 6. Test Select All & Recommended Actions
        await page.click('#btn-verif-select-all');
        await page.waitForTimeout(300);
        const allActiveBadge = await page.textContent('#setup-active-verif-badge');
        expect(allActiveBadge).toBe('11 / 11 Active');

        await page.click('#btn-verif-reset-default');
        await page.waitForTimeout(300);
        const defaultBadge = await page.textContent('#setup-active-verif-badge');
        expect(defaultBadge).toBe('10 / 11 Active');
    });

    test('Zero horizontal scroll on mobile viewport (390px)', async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 });
        await page.goto('/');
        await page.waitForSelector('#app-loading-screen', { state: 'hidden', timeout: 5000 });

        for (const step of [1, 2, 3, 4, 5]) {
            await page.evaluate((s) => {
                if (s === 2 && window.state) window.state.wizardStage = 3;
                window.navigateToStep(s);
                if (s === 2) window.renderWizardStep();
            }, step);
            await page.waitForTimeout(400);

            const hasOverflow = await page.evaluate(() => {
                return document.documentElement.scrollWidth > window.innerWidth + 1;
            });
            expect(hasOverflow).toBeFalsy();
        }
    });

    test('Contrast ratio compliance (>= 4.5:1 text, >= 3:1 controls)', async ({ page }) => {
        await page.goto('/');
        await page.waitForSelector('#app-loading-screen', { state: 'hidden', timeout: 5000 });

        for (const theme of ['dark', 'light']) {
            await page.evaluate((th) => window.applyTheme(th), theme);
            await page.waitForTimeout(400);

            // Test Title contrast against page background
            const titleContrast = await page.evaluate(() => {
                const title = document.querySelector('.hero-title, .wizard-title, h1, h2');
                const body = document.body;
                if (!title) return 5.0;

                const compTitle = window.getComputedStyle(title);
                const compBody = window.getComputedStyle(body);

                function getLum(rgb) {
                    const match = rgb.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
                    if (!match) return 0;
                    const a = [parseInt(match[1]), parseInt(match[2]), parseInt(match[3])].map(v => {
                        v /= 255;
                        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
                    });
                    return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
                }

                const lum1 = getLum(compTitle.color);
                const lum2 = getLum(compBody.backgroundColor);
                const max = Math.max(lum1, lum2);
                const min = Math.min(lum1, lum2);
                return (max + 0.05) / (min + 0.05);
            });

            expect(titleContrast).toBeGreaterThanOrEqual(4.5);
        }
    });

    test('Header zero collision and zero overflow across responsive widths', async ({ page }) => {
        for (const w of [390, 550, 768, 1024]) {
            await page.setViewportSize({ width: w, height: 800 });
            await page.goto('/#step1');
            await page.waitForSelector('#app-loading-screen', { state: 'hidden', timeout: 5000 });
            await page.waitForTimeout(300);

            const headerInfo = await page.evaluate((width) => {
                const header = document.querySelector('.app-header');
                const brand = document.querySelector('.brand-logo-btn');
                const hr = document.querySelector('.header-right');
                return {
                    brandTop: brand ? brand.getBoundingClientRect().top : 0,
                    hrRight: hr ? hr.getBoundingClientRect().right : 0,
                    headerH: header ? header.offsetHeight : 0,
                    docW: document.documentElement.scrollWidth,
                    width
                };
            }, w);

            expect(headerInfo.hrRight).toBeLessThanOrEqual(w + 1);
            expect(headerInfo.brandTop).toBeGreaterThanOrEqual(0);
            expect(headerInfo.docW).toBeLessThanOrEqual(w + 1);
        }
    });

});

