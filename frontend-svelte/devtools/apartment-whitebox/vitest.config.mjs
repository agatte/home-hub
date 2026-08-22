import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { defineConfig } from 'vitest/config'

const root = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  root,
  test: {
    environment: 'node',
    include: ['adapter.test.js'],
  },
})
