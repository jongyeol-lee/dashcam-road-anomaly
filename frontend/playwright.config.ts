import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  outputDir: '../outputs/playwright/part6_3_1_mock',
  use: {
    baseURL: 'http://127.0.0.1:5177',
    browserName: 'chromium',
    channel: 'msedge',
  },
  webServer: {
    command: 'npm run build && npm run preview -- --host 127.0.0.1 --port 5177 --strictPort',
    url: 'http://127.0.0.1:5177',
    reuseExistingServer: false,
  },
})
