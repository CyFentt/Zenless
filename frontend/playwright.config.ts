import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 20000,
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:5193', headless: true, trace: 'retain-on-failure' },
  webServer: {
    command: 'VITE_RUBRA_MOCK=true npm run dev -- --host 127.0.0.1 --port 5193',
    url: 'http://127.0.0.1:5193',
    reuseExistingServer: false,
  },
});
