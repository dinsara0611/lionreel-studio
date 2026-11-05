module.paths.push('C:/Users/dinsa/AppData/Roaming/npm/node_modules');
const { defineConfig } = require('C:/Users/dinsa/AppData/Roaming/npm/node_modules/@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  timeout: 30000,
  use: {
    channel: 'chrome',
    baseURL: 'http://localhost:8100',
    headless: true,
  },
});
