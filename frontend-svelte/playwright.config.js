import { defineConfig, devices } from '@playwright/test'

// Smoke tests run against a live dashboard. By default they hit the
// production-style URL the FastAPI backend serves on; override with
// PLAYWRIGHT_BASE_URL when the dev server is on :3001 instead.
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:8000'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium-desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
  ],
})
