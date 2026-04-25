// Smoke tests against the live dashboard.
//
// Run locally with the FastAPI server up on :8000:
//   python run.py
// then in another shell:
//   cd frontend-svelte && npm run test:e2e
//
// Or point at a different host with PLAYWRIGHT_BASE_URL=http://192.168.1.210:8000.
//
// These tests are NOT in the GitHub Actions CI pipeline — running them
// requires a live backend, which CI doesn't currently spin up.

import { test, expect } from '@playwright/test'

test.describe('dashboard smoke', () => {
  test('home page loads and shows the floating nav', async ({ page }) => {
    await page.goto('/')
    // The floating nav is always rendered in the layout.
    const nav = page.locator('nav, [class*="floating-nav"], [class*="FloatingNav"]')
    await expect(nav.first()).toBeVisible({ timeout: 10_000 })
  })

  test('settings route renders', async ({ page }) => {
    await page.goto('/settings')
    // Settings has a stable heading.
    await expect(page.locator('body')).toContainText(/Settings|Devices|Schedule/i)
  })

  test('music route renders', async ({ page }) => {
    await page.goto('/music')
    await expect(page.locator('body')).toContainText(/Music|Playlist|Taste|Discover/i)
  })

  test('analytics route renders', async ({ page }) => {
    await page.goto('/analytics')
    await expect(page.locator('body')).toContainText(/Pipeline|Decision|Confidence|Analytics/i)
  })

  test('/health returns JSON with status: healthy', async ({ request }) => {
    const res = await request.get('/health')
    expect(res.ok()).toBe(true)
    const body = await res.json()
    expect(body.status).toBe('healthy')
    // New fields shipped in def9606 — verify they survived deploy.
    expect(body).toHaveProperty('event_logger_drops')
    expect(body).toHaveProperty('event_logger_overflow')
    expect(body).toHaveProperty('event_logger_queue_depth')
  })
})
