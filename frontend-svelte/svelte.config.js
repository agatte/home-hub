import adapter from '@sveltejs/adapter-static'
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte'

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    // Emit a fully static build that FastAPI mounts at /{path:path}.
    // SPA fallback via index.html is required because client-side routing
    // owns /music and /settings.
    adapter: adapter({
      pages: 'build',
      assets: 'build',
      fallback: 'index.html',
      precompress: false,
      strict: true,
    }),
    // All routes are client-rendered; no SSR needed for a LAN dashboard.
    prerender: { entries: [] },
  },
}

export default config
