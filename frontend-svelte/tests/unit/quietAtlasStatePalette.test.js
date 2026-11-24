import { describe, expect, it } from 'vitest'
import { houseTone, activityTone, modeTone } from '../../src/lib/quietAtlas/widgetTone.js'
import { roomColorBackground } from '../../src/lib/quietAtlas/homeRoomLightSummary.js'
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
  it('keeps disconnected, partial, off or unknown color states neutral', () => {
    expect(roomColorBackground(['1'],{'1':warm},false)).toBe('')
    expect(roomColorBackground(['1','2'],{'1':warm},true)).toBe('')
    for(const fixture of [{...warm,reachable:false},{...warm,on:false},{...warm,bri:0},{...warm,colormode:'xy'},{...warm,ct:999}])
      expect(roomColorBackground(['1'],{'1':fixture},true)).toBe('')
  })
})
