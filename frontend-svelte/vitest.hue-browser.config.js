// L6 browser-only mounted component regression coverage.
// Do not change global Vitest resolution: legacy component tests depend on
// Svelte 4's default SSR export, while recovery uses browser onMount.
import { defineConfig } from 'vitest/config'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import path from 'node:path'

export default defineConfig({
  plugins: [svelte({ hot: false })],
  resolve: {
    conditions: ['browser'],
    alias: {
      $lib: path.resolve('./src/lib'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/unit/setup.js'],
    include: ['tests/unit/components/HueAppHold.test.js'],
  },
})
