module.paths.push('C:/Users/dinsa/AppData/Roaming/npm/node_modules');
const { test, expect } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');

test('load home page', async ({ page }) => {
    await page.goto('http://localhost:8000');
    await page.waitForTimeout(2000);
    const title = await page.title();
    expect(title).toContain('LionReel');
});
