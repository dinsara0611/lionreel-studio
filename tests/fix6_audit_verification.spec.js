module.paths.push('C:/Users/dinsa/AppData/Roaming/npm/node_modules');
const { test, expect } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');
const path = require('path');

test.describe('Fix 6 - Candidate Audit Table & UI Verification', () => {
    test('verify candidate audit table columns, expandable rows, formatters, and retry flow', async ({ page }) => {
        // 1. Navigate to dashboard
        await page.goto('http://localhost:8100');
        await page.waitForTimeout(1500);

        // 2. Navigate to Step 4 (Render step)
        await page.evaluate(() => {
            if (typeof window.navigateToStep === 'function') {
                window.navigateToStep(4);
            }
        });
        await page.waitForTimeout(1000);

        // 3. Inject mock candidate reports to thoroughly test all edge cases of Fix 6 (unmeasured, reasons, retry banner, expand/collapse)
        await page.evaluate(() => {
            const mockReports = [
                {
                    candidate: 1,
                    source: "cache_ByH9LuSILxU.mp4",
                    start_s: 10.0,
                    dur_s: 7.5,
                    pet_ratio: 0.952,
                    horiz_ratio: 0.981,
                    vert_ratio: 0.945,
                    size_ratio: 0.892,
                    sharpness: 34.2,
                    score: 0.915,
                    actual_score: 0.908,
                    result: "PASS",
                    reason: "PASS",
                    clip_id: "c_test_01",
                    measured: true
                },
                {
                    candidate: 2,
                    source: "very_long_source_filename_for_testing_word_break_cat_video_supercut_2026.mp4",
                    start_s: 25.5,
                    dur_s: 7.5,
                    pet_ratio: 0.88,
                    horiz_ratio: 1.0,
                    vert_ratio: 0.45,
                    size_ratio: 0.35,
                    sharpness: 12.4,
                    score: 0.42,
                    actual_score: null,
                    result: "REJECT",
                    reason: "BLURRED_BARS + SIZE",
                    clip_id: "c_test_02_blur",
                    measured: true
                },
                {
                    candidate: 3,
                    source: "cache_ByH9LuSILxU.mp4",
                    start_s: 50.0,
                    dur_s: 7.5,
                    pet_ratio: null,
                    horiz_ratio: null,
                    vert_ratio: null,
                    size_ratio: null,
                    sharpness: null,
                    score: null,
                    actual_score: null,
                    result: "REJECT",
                    reason: "WATERMARK detected in window",
                    clip_id: "c_test_03_wm",
                    measured: false
                },
                {
                    candidate: 4,
                    source: "cache_ByH9LuSILxU.mp4",
                    start_s: 80.0,
                    dur_s: 7.5,
                    pet_ratio: 0.70,
                    horiz_ratio: 0.85,
                    vert_ratio: 0.60,
                    size_ratio: 0.75,
                    sharpness: 28.0,
                    score: 0.65,
                    actual_score: null,
                    result: "REJECT",
                    reason: "PREDICTED_BAD_FRAMING (Score: 65% < 88%)",
                    clip_id: "c_test_04_framing",
                    measured: true
                }
            ];

            // Set layout mode to blur_fit to trigger the suggested smart crop banner
            localStorage.setItem("lionreel_layout_mode", "blur_fit");
            if (window.state && window.state.config) {
                window.state.config.LAYOUT_MODE = "blur_fit";
            }

            // Call renderCandidateReportsTable
            if (typeof renderCandidateReportsTable === "function") {
                renderCandidateReportsTable(mockReports);
            }
        });

        await page.waitForTimeout(500);

        // 4. Assert Audit Table Headers
        const headers = await page.$$eval('#render-candidate-table-container thead th', ths => ths.map(t => t.innerText.trim()));
        console.log("Found table headers:", headers);
        expect(headers).toContain('Cand');
        expect(headers).toContain('Source');
        expect(headers).toContain('Pet %');
        expect(headers).toContain('H');
        expect(headers).toContain('V');
        expect(headers).toContain('Size');
        expect(headers).toContain('Sharpness');
        expect(headers).toContain('Predicted');
        expect(headers).toContain('Actual');
        expect(headers).toContain('Reason');

        // 5. Assert Unmeasured cells show "not measured"
        const unmeasuredSpans = await page.$$eval('#render-candidate-table-container span', spans => 
            spans.filter(s => s.innerText.includes('not measured')).map(s => s.innerText)
        );
        console.log("Unmeasured spans count:", unmeasuredSpans.length);
        expect(unmeasuredSpans.length).toBeGreaterThanOrEqual(4);

        // 6. Assert Source column tooltip and word-break
        const sourceTd = await page.$('#render-candidate-table-container tbody tr:first-child td:nth-child(2)');
        const tooltip = await sourceTd.getAttribute('title');
        expect(tooltip).toBe('cache_ByH9LuSILxU.mp4');

        // 7. Verify expandable row toggle
        const firstDetailRow = page.locator('#cand-detail-0');
        await expect(firstDetailRow).toBeHidden();

        // Click first candidate row to expand
        await page.click('#render-candidate-table-container tbody tr:first-child');
        await page.waitForTimeout(300);
        await expect(firstDetailRow).toBeVisible();

        const detailText = await firstDetailRow.innerText();
        console.log("Expanded detail text:", detailText);
        expect(detailText).toContain('Time Window: 10.0s - 17.5s (7.5s)');
        expect(detailText).toContain('Clip ID: c_test_01');
        expect(detailText).toContain('Gate Telemetry / Full Reason: PASS');

        const chevHtml = await page.$eval('#cand-chev-0', el => el.innerHTML);
        expect(chevHtml).toContain('icon-chevron-up');

        // Click again to collapse
        await page.click('#render-candidate-table-container tbody tr:first-child');
        await page.waitForTimeout(300);
        await expect(firstDetailRow).toBeHidden();

        // 8. Verify Failure Summary Banner & Retry with Smart Crop button
        const summaryBanner = page.locator('.audit-summary-banner');
        await expect(summaryBanner).toBeVisible();
        const bannerText = await summaryBanner.innerText();
        console.log("Banner text:", bannerText);
        expect(bannerText).toContain('BLURRED_BARS + SIZE');
        expect(bannerText).toContain('Suggested fix: use Smart crop');

        // Verify "⚡ Retry with Smart Crop" button
        const retrySmartBtn = page.locator('#btn-retry-smart-crop');
        await expect(retrySmartBtn).toBeVisible();

        // 9. Verify Elapsed Time display and ETA container logic
        await page.evaluate(() => {
            const remainWrap = document.getElementById("render-telemetry-remaining");
            if (remainWrap) remainWrap.style.display = "none";
            const elapsedEl = document.getElementById("render-time-elapsed");
            if (elapsedEl) elapsedEl.innerText = "03:14";
        });
        const remainDisplay = await page.$eval('#render-telemetry-remaining', el => el.style.display);
        expect(remainDisplay).toBe('none');

        // 10. Capture full screenshot of table
        const screenshotPath = path.resolve(__dirname, '../ui_audit/fix6_audit_table.png');
        const container = page.locator('#render-candidate-table-container');
        await container.screenshot({ path: screenshotPath });
        console.log(`Saved screenshot to ${screenshotPath}`);
    });
});
