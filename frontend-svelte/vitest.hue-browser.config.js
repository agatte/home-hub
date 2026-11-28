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
      // SvelteKit is not installed as a Vite plugin in this mounted-test config.
      '$app/navigation': path.resolve('./tests/unit/mocks/kitNavigation.js'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/unit/setup.js'],
    include: ['tests/unit/components/HueAppHold.test.js', 'tests/unit/quietAtlasSceneTools.test.js', 'tests/unit/quietAtlasCustomSceneEditor.test.js', 'tests/unit/quietAtlasSettingsDisclosure.test.js', 'tests/unit/guestOwnerReturn.test.js', 'tests/unit/listeningChoices.test.js', 'tests/unit/classicBookmark.test.js', 'tests/unit/householdAppAccess.test.js'],
  },
})
