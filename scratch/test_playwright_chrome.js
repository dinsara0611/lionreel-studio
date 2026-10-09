const { chromium } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');

(async () => {
  const browser = await chromium.launch({
    channel: 'chrome',
    headless: true
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 }
  });
  await page.goto('http://localhost:8000/#step1', { waitUntil: 'networkidle' });
  console.log('Title:', await page.title());
  await browser.close();
  console.log('Playwright test passed!');
})();
