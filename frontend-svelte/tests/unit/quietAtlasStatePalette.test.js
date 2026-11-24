import { describe, expect, it } from 'vitest'
import { houseTone, activityTone, modeTone } from '../../src/lib/quietAtlas/widgetTone.js'
import { roomColorBackground, homeSnapshotRoomColor } from '../../src/lib/quietAtlas/homeRoomLightSummary.js'
import { newReadOnlySnapshot, connectionChanged, beginLightRead, acceptLightRead, invalidateLightRead, failLightRead } from '../../src/lib/quietAtlas/lightSnapshot.js'
import overview from '../../src/lib/components/QuietAtlasLightingOverview.svelte?raw'
import experience from '../../src/lib/components/QuietAtlasLightingExperience.svelte?raw'
import home from '../../src/routes/quiet-atlas/home/+page.svelte?raw'
const warm = {on:true,reachable:true,bri:254,ct:454,colormode:'ct',hue:0,sat:254}
const blue = {on:true,reachable:true,bri:190,hue:46000,sat:230,colormode:'hs',ct:250}
describe('Reported HomeHub context colors', () => {
  it('keeps house states distinct and reuses activity colors for modes', () => {
    expect(['Home','Winding Down','Sleeping','Away','Unverified'].map(houseTone)).toEqual(['home','dusk','sleep','away','neutral'])
    expect(modeTone('Gaming',true)).toBe(activityTone('Gaming'))
    expect(modeTone('Relax',true)).toBe(activityTone('Relaxing'))
    expect(modeTone('Party',true)).toBe(activityTone('Social'))
    expect(modeTone('Sleeping',true)).toBe('sleep')
    expect(modeTone('Gaming',false)).toBe('neutral')
  })
  it('uses active color mode, both lit fixtures and brightness', () => {
    const both = roomColorBackground(['1','2'],{'1':warm,'2':blue},true)
    expect(both).toContain('rgb(')
    expect(both).toContain('hsl(')
    expect(both).toContain('100%')
    expect(roomColorBackground(['1'],{'1':{...warm,bri:30}},true)).not.toEqual(roomColorBackground(['1'],{'1':warm},true))
    expect(roomColorBackground(['1'],{'1':warm},true)).not.toContain('hsl(')
    expect(roomColorBackground(['2'],{'2':blue},true)).not.toContain('rgb(')
    expect(roomColorBackground(['1','2'],{'1':warm,'2':{...blue,on:false}},true)).toBe(roomColorBackground(['1'],{'1':warm},true))
  })
  it('uses the same fresh Control report for labels and room colors, not the global light store', () => {
    expect(experience).toContain('snapshotFixtures={snapshot.fixtures}')
    expect(overview).toContain('roomColorBackground(group.fixtureIds, snapshotFixtures,')
    expect(overview).not.toContain('$lights')
    expect(home).toContain('homeSnapshotRoomColor(group.fixtures, paletteSnapshot, contextNowMs, $lights, $connected && $deviceStatus.hue)')
  })
  it('requires a current agreeing report on Home and invalidates stale or mismatched colors', () => {
    const initial = connectionChanged(newReadOnlySnapshot(), true)
    const request = beginLightRead(initial)
    const live = {'1':warm,'2':blue}
    const snapshot = acceptLightRead(request.state, request.ticket, [{light_id:'1',...warm},{light_id:'2',...blue}], 1000)
    const palette = homeSnapshotRoomColor(['1','2'],snapshot,1000,live,true)
    expect(palette).toBe(roomColorBackground(['1','2'],live,true))
    expect(palette).not.toBe('')
    for (const state of [initial, connectionChanged(snapshot,false), connectionChanged(connectionChanged(snapshot,false),true), invalidateLightRead(snapshot), failLightRead(beginLightRead(snapshot).state,beginLightRead(snapshot).ticket)]) {
      expect(homeSnapshotRoomColor(['1','2'],state,1000,live,true)).toBe('')
    }
    expect(homeSnapshotRoomColor(['1','2'],snapshot,31001,live,true)).toBe('')
    expect(homeSnapshotRoomColor(['1','2'],snapshot,1000,live,false)).toBe('')
    expect(homeSnapshotRoomColor(['1','2'],snapshot,1000,{'1':warm,'2':{...blue,on:false}},true)).toBe('')
    expect(homeSnapshotRoomColor(['1','2'],snapshot,1000,{'1':warm,'2':{...blue,hue:100}},true)).toBe('')
    expect(homeSnapshotRoomColor(['1','2'],snapshot,1000,{'1':warm,'2':{...blue,bri:50}},true)).toBe('')
  })
  it('keeps disconnected, partial, off or unknown color states neutral', () => {
    expect(roomColorBackground(['1'],{'1':warm},false)).toBe('')
    expect(roomColorBackground(['1','2'],{'1':warm},true)).toBe('')
    for(const fixture of [{...warm,reachable:false},{...warm,on:false},{...warm,bri:0},{...warm,colormode:'xy'},{...warm,ct:999}])
      expect(roomColorBackground(['1'],{'1':fixture},true)).toBe('')
  })
})
