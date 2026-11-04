import { defineConfig } from 'vitest/config'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import path from 'node:path'

export default defineConfig({
  plugins: [svelte({ hot: false })],
  resolve: {
    // Svelte 4's default SSR export makes onMount a no-op. Unit tests mount
    // components in jsdom and must resolve the browser runtime instead.
    conditions: ['browser'],
    alias: {
      // Match the SvelteKit alias so imports like '$lib/foo' resolve in tests.
      $lib: path.resolve('./src/lib'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/unit/setup.js'],
    include: ['tests/unit/**/*.test.{js,ts,svelte.test.js}'],
    // Don't try to scan the e2e folder.
    exclude: ['tests/e2e/**', 'node_modules/**', 'build/**', '.svelte-kit/**'],
  },
})
