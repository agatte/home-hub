// Test-only resolution target for SvelteKit navigation. Tests must mock goto.
export function goto() {
  throw new Error('Mock goto before mounting a SvelteKit route in Vitest')
}
