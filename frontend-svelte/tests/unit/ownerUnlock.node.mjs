import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

const source = fs.readFileSync(new URL('../../src/lib/components/OwnerUnlock.svelte', import.meta.url), 'utf8')
const script = source.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/import \{ onMount \} from 'svelte'/, '')
test('fake browser login clears input and reloads after success', async () => {
  let payload, clearedAtSend, reloads = 0
  const context = vm.createContext({ onMount: () => {}, fetch: async (url, options) => {
    assert.equal(url, '/api/owner/session')
    payload = JSON.parse(options.body)
    clearedAtSend = vm.runInContext('password', context)
    return { ok: true }
  }, window: { location: { reload: () => reloads++ } } })
  vm.runInContext(script, context)
  vm.runInContext("password = 'fake passphrase'", context)
  await vm.runInContext('unlock()', context)
  assert.deepEqual(payload, { password: 'fake passphrase' })
  assert.equal(clearedAtSend, '')
  assert.equal(reloads, 1)
  assert.doesNotMatch(source, /localStorage|sessionStorage|[?&]password=/)
})

test('owner unlock controls keep finger-sized hit targets and keyboard focus', () => {
  assert.match(source, /button, input \{[^}]*min-height: 44px/)
  assert.match(source, /button:focus-visible, input:focus-visible/)
})

test('locking a trusted browser requires deliberate confirmation', async () => {
  let calls = 0, reloads = 0
  const context = vm.createContext({ onMount: () => {}, fetch: async (url, options) => {
    assert.equal(url, '/api/owner/session')
    assert.equal(options.method, 'DELETE')
    calls++
    return { ok: true }
  }, window: { location: { reload: () => reloads++ } } })
  vm.runInContext(script, context)
  vm.runInContext('authenticated = true', context)
  await vm.runInContext('lock()', context)
  assert.equal(calls, 0)
  vm.runInContext('confirmLock = true', context)
  await vm.runInContext('lock()', context)
  assert.equal(calls, 1)
  assert.equal(reloads, 1)
})
test('redesigned owner actions are in More, not a fixed page overlay', () => {
  const shell = fs.readFileSync(new URL('../../src/lib/components/QuietAtlasShell.svelte', import.meta.url), 'utf8')
  const layout = fs.readFileSync(new URL('../../src/routes/+layout.svelte', import.meta.url), 'utf8')
  assert.match(shell, /\{#if moreOpen\}[\s\S]*<OwnerUnlock \/>/)
  assert.doesNotMatch(layout, /classic-owner-access|<OwnerUnlock\s*\/>/)
  assert.doesNotMatch(source, /position:\s*fixed/)
})
