// Vitest setup — registers @testing-library/jest-dom matchers and cleans up
// rendered Svelte components between tests so DOM state doesn't leak.
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/svelte'

afterEach(() => {
  cleanup()
})
