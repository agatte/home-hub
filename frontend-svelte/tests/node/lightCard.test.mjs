import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

// Execute the component's actual handlers without a Svelte/DOM installation.
// Template binding assertions below keep this harness tied to the event paths.
const source = readFileSync(new URL('../../src/lib/components/LightCard.svelte', import.meta.url), 'utf8')
function card(on = true, inline = false) {
  const writes = [], timers = new Map()
  let listener, next = 0, now = 1000
  const script = source.split('<script>')[1].split('</script>')[0]
    .replace(/^\s*import .*$/gm, '').replace(/export let light/g, 'let light = initialLight')
    .replace(/export let /g, 'let ')
    .replace('optimisticStore = true', `optimisticStore = ${!inline}`)
  const context = vm.createContext({ initialLight: { light_id: '2', on, bri: 80, reachable: true },
    $lightCommandResults: {}, setLight: (id, state) => writes.push({ id, ...state }),
    subscribeLightControl: (fn) => { listener = fn; return () => {} }, onDestroy: () => {},
    LIGHT_CT_PRESETS: [], hueToHsl: () => '', ctToColor: () => '',
    setTimeout: (fn) => { timers.set(++next, fn); return next }, clearTimeout: (id) => timers.delete(id),
    Date: { now: () => now },
  })
  vm.runInContext(script + '\ncardEl = { getBoundingClientRect: () => ({left:0,width:254}), setPointerCapture() {}, releasePointerCapture() {} };', context)
  return { writes, timers, run: (s) => vm.runInContext(s, context),
    notify: (...args) => listener(...args), advance: (ms) => { now += ms } }
}
const key = "onKeydown({key:'ArrowRight',preventDefault(){}}); onKeyup({key:'ArrowRight',preventDefault(){}})"
const down = "onPointerDown({pointerId:1,pointerType:'mouse',clientX:0})"
const move = (x) => `onPointerMove({pointerId:1,clientX:${x}})`
const end = (type) => `onPointerEnd({pointerId:1,type:'${type}'})`

test('actual keyboard and power handlers compose rapid targets without changing observed light', () => {
  const c = card()
  c.run(key); c.run(key)
  assert.deepEqual(c.writes.map(x => x.bri), [93,106])
  c.run('togglePower()'); c.run('togglePower()')
  assert.deepEqual(c.writes.slice(2).map(x => x.on), [false,true])
  assert.equal(c.run('light.bri'), 80)
  assert.equal(c.run('light.on'), true)
})
for (const kind of ['reset', 'observation']) test(`local composition resets on ${kind}`, () => {
  const c = card()
  c.run(key)
  if (kind === 'observation') c.run('light = {...light,bri:93}')
  c.notify('2', kind, { bri:93 })
  c.run(key)
  assert.equal(c.writes[1].bri, kind === 'reset' ? 93 : 106)
  c.notify(null, 'reset')
  c.run(key)
  assert.equal(c.writes[2].bri, kind === 'reset' ? 93 : 106)
})
test('off drag release carries power intent when repeated motions are previewed locally', () => {
  const c = card(false)
  c.run(down); c.run(move(40)); c.run(end('pointerup'))
  c.run(down); c.run(move(70)); c.run(move(110)); c.run(move(150))
  assert.equal(c.writes.length, 1)
  c.run(end('pointerup'))
  assert.equal(c.writes.length, 2)
  assert.equal(c.writes[1].on, true)
  assert.equal(c.writes[1].bri, 150)
  assert.equal(c.writes[1].transitiontime, undefined)
})
for (const type of ['pointercancel','lostpointercapture']) test(`${type} drops queued off drag with no final turn-on`, () => {
  const c = card(false)
  c.run(down); c.run(move(40)); c.run(end('pointerup'))
  c.run(down); c.run(move(100)); c.run(end(type))
  assert.equal(c.writes.length, 1)
  assert.equal(c.run('pendingBri'), null)
})
test('component binds the tested handlers to keyboard, click and pointer events', () => {
  for (const binding of ['on:keydown={onKeydown}', 'on:keyup={onKeyup}', 'on:blur={cancelGesture}', 'on:change={finishBrightnessDrag}', 'on:click|stopPropagation={togglePower}',
    'on:pointerup={onPointerEnd}', 'on:pointercancel={onPointerEnd}', 'on:lostpointercapture={onPointerEnd}']) {
    assert.ok(source.includes(binding))
  }
})

for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) test(`pending Off followed by drag: ${type}`, () => {
  const c = card()
  c.run('togglePower()')
  c.run(down); c.run(move(100)); c.run(move(150))
  assert.equal(c.writes.length, 1)
  c.run(end(type))
  if (type === 'pointerup') {
    assert.equal(c.writes.at(-1).on, true)
    assert.equal(c.writes.at(-1).bri, 150)
    assert.equal(c.writes.at(-1).transitiontime, undefined)
  } else {
    const count = c.writes.length
    for (const [id, fn] of [...c.timers]) { c.timers.delete(id); fn() }
    c.run(end('pointerup')); c.run(move(200))
    assert.equal(c.writes.length, count)
  }
})

for (const [direction, observed, expected] of [
  ['ArrowRight', 40, 53], ['ArrowLeft', 120, 107],
  ['ArrowRight', 85, 106], ['ArrowLeft', 75, 54],
  ['ArrowRight', 80, 106], ['ArrowLeft', 80, 54],
  ['ArrowRight', 93, 106], ['ArrowLeft', 67, 54],
]) test(`${direction} rebases only contradictory brightness (${observed})`, () => {
  const c = card()
  const press = `onKeydown({key:'${direction}',preventDefault(){}}); onKeyup({key:'${direction}',preventDefault(){}})`
  c.run(press)
  c.notify('2', 'observation', { bri: observed })
  c.run(`light = {...light,bri:${observed}}`)
  if (observed === 93 || observed === 67) assert.equal(c.run('controlTarget.bri'), undefined)
  c.run(press)
  assert.equal(c.writes.at(-1).bri, expected)
})

test('contradictory brightness cancels queued drag but preserves pending power', () => {
  const c = card()
  c.run('togglePower()'); c.run(key)
  c.run(down); c.run(move(100)); c.run(move(150))
  c.notify('2', 'observation', { bri: 40, on: false })
  assert.equal(c.run('controlTarget.bri'), undefined)
  assert.equal(c.run('controlTarget.on'), true)
  assert.equal(c.run('pendingBri'), null)
})

test('reversed rapid keys preserve earlier in-flight target range', () => {
  const c = card()
  c.run(key); c.run("onKeydown({key:'ArrowLeft',preventDefault(){}}); onKeyup({key:'ArrowLeft',preventDefault(){}})")
  c.notify('2', 'observation', { bri: 90 })
  c.run('light = {...light,bri:90}')
  c.run(key)
  assert.equal(c.writes.at(-1).bri, 93)
})

for (const type of ['pointercancel', 'lostpointercapture']) test(`${type} before movement cannot turn pending Off back on`, () => {
  const c = card()
  c.run('togglePower()'); c.run(down); c.run(end(type))
  c.run(move(150)); c.run(end('pointerup'))
  for (const [id, fn] of [...c.timers]) { c.timers.delete(id); fn() }
  assert.deepEqual(c.writes.map(x => x.on), [false])
})

for (const id of ['2', null]) test(`reset (${id}) clears brightness range and cancels queued actuation`, () => {
  const c = card()
  c.run('togglePower()'); c.run(down); c.run(move(100)); c.run(move(150))
  const count = c.writes.length
  c.notify(id, 'reset')
  assert.equal(c.run('controlTarget.on'), undefined)
  assert.equal(c.run('controlTarget.bri'), undefined)
  assert.equal(c.run('pendingBri'), null)
  c.run(end('pointerup'))
  for (const [timer, fn] of [...c.timers]) { c.timers.delete(timer); fn() }
  assert.equal(c.writes.length, count)
  c.run(key)
  assert.equal(c.writes.at(-1).bri, 93)
  c.notify('2', 'observation', { bri: 40 })
  c.run('light = {...light,bri:40}')
  c.run(key)
  assert.equal(c.writes.at(-1).bri, 53)
})

test('repeated baseline and partial observations preserve local pending intent', () => {
  const c = card()
  c.run('togglePower()'); c.run(key)
  for (const observed of [{ bri: 80 }, { bri: 85 }, { bri: 80 }, { on: false }]) {
    c.notify('2', 'observation', observed)
  }
  assert.equal(c.run('controlTarget.on'), true)
  c.run(key)
  assert.equal(c.writes.at(-1).bri, 106)
  assert.equal(c.run('light.bri'), 80)
  assert.equal(c.run('light.on'), true)
})

for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
  test(`inline Home drag previews without writes until explicit release: ${type}`, () => {
    const c = card(false, true)
    c.run(down); c.run(move(100)); c.run(move(150))
    assert.equal(c.writes.length, 0)
    c.run(end(type))
    assert.equal(c.writes.length, type === 'pointerup' ? 1 : 0)
    if (type === 'pointerup') assert.deepEqual(c.writes[0], { id: '2', on: true, bri: 150 })
    assert.equal(c.run('light.on'), false)
    assert.equal(c.run('light.bri'), 80)
  })
}

test('inline pending receipt blocks additional handlers without changing observations', () => {
  const c = card(true, true)
  c.run('commandPending = true')
  c.run(key); c.run('togglePower()'); c.run(down); c.run(move(100)); c.run(end('pointerup'))
  assert.equal(c.writes.length, 0)
  assert.equal(c.run('light.bri'), 80)
})

for (const linked of [false, true]) test(`Classic 12 motions over 500ms commit once per fixture; kitchen=${linked}`, () => {
  const c = card()
  if (linked) c.run("light = {...light,light_id:'3'}; linkedIds = ['4']")
  c.run(down)
  for (let i = 1; i <= 12; i++) {
    c.advance(500 / 12)
    c.run(move(10 * i))
    assert.equal(c.writes.length, 0)
    assert.equal(c.timers.size, 0)
    assert.equal(c.run('optimisticBri'), Math.round(10 * i / 254 * 253) + 1)
  }
  c.run(end('pointerup')); c.run('finishBrightnessDrag()'); c.run(end('pointerup'))
  assert.deepEqual(c.writes.map(w => w.id), linked ? ['3', '4'] : ['2'])
  assert.ok(c.writes.every(w => w.bri === 121 && w.transitiontime === undefined))
})

test('change before pointerup coalesces the same final gesture', () => {
  const c = card()
  c.run(down); c.run(move(150)); c.run('finishBrightnessDrag()'); c.run(end('pointerup'))
  assert.equal(c.writes.length, 1)
})

for (const inline of [false, true]) test(`held keyboard repeats preview until keyup; inline=${inline}`, () => {
  const c = card(false, inline)
  for (let i = 0; i < 12; i++) {
    c.advance(500 / 12)
    c.run("onKeydown({key:'ArrowRight',repeat:true,preventDefault(){}})")
    assert.equal(c.writes.length, 0)
  }
  assert.equal(c.run('optimisticBri'), 236)
  c.run("onKeyup({key:'ArrowRight',preventDefault(){}})")
  c.run("onKeyup({key:'ArrowRight',preventDefault(){}})")
  assert.deepEqual(c.writes, [{id:'2', on:true, bri:236}])
})

for (const boundary of ['cancelGesture()', "notify"]) test(`keyboard preview cancels on ${boundary}`, () => {
  const c = card()
  c.run("onKeydown({key:'End',preventDefault(){}})")
  if (boundary === 'notify') c.notify(null, 'reset')
  else c.run(boundary)
  c.run("onKeyup({key:'End',preventDefault(){}})")
  assert.equal(c.writes.length, 0)
})

for (const type of ['pointercancel', 'lostpointercapture']) test(`Classic Kitchen ${type} discards all 12 preview motions`, () => {
  const c = card(false)
  c.run("light = {...light,light_id:'3'}; linkedIds = ['4']")
  c.run(down)
  for (let i = 1; i <= 12; i++) { c.advance(500 / 12); c.run(move(i * 10)) }
  c.run(end(type)); c.run('finishBrightnessDrag()'); c.run(end('pointerup'))
  assert.equal(c.writes.length, 0)
  assert.equal(c.timers.size, 0)
  assert.equal(c.run('optimisticBri'), null)
})

for (const [keyName, bri] of [['Home', 1], ['End', 254], ['ArrowDown', 67], ['ArrowUp', 93]]) {
  test(`keyboard ${keyName} commits pending Off as on at keyup`, () => {
    const c = card()
    c.run('togglePower()')
    c.run(`onKeydown({key:'${keyName}',preventDefault(){}})`)
    assert.equal(c.writes.length, 1)
    c.run(`onKeyup({key:'${keyName}',preventDefault(){}})`)
    assert.deepEqual(c.writes[1], {id:'2', on:true, bri})
  })
}
