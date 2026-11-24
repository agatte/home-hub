import { describe, expect, it } from 'vitest'
import { homeRoomLightSummary } from '../../src/lib/quietAtlas/homeRoomLightSummary.js'

const live = (on) => ({ on, reachable: true })

describe('Home room lighting status is reported, not inferred', () => {
  it('summarizes each independent room without sending or implying an action', () => {
    expect(homeRoomLightSummary(['1'], { '1': live(true) }, true)).toEqual({ label: 'On', tone: 'on' })
    expect(homeRoomLightSummary(['1'], { '1': live(false) }, true)).toEqual({ label: 'All off', tone: 'off' })
    expect(homeRoomLightSummary(['2', '5'], { '2': live(true), '5': live(false) }, true))
      .toEqual({ label: '1 of 2 on', tone: 'on' })
    expect(homeRoomLightSummary(['3', '4'], { '3': live(true), '4': live(true) }, true))
      .toEqual({ label: 'All on', tone: 'on' })
  })

  it('never reports missing, unreachable or disconnected fixtures as off', () => {
    expect(homeRoomLightSummary(['2', '5'], { '2': live(true) }, true))
      .toEqual({ label: 'Checking lights', tone: 'unknown' })
    expect(homeRoomLightSummary(['2', '5'], { '2': live(false), '5': { on: true, reachable: false } }, true))
      .toEqual({ label: 'Light unavailable', tone: 'unknown' })
    expect(homeRoomLightSummary(['1'], { '1': { reachable: true } }, true))
      .toEqual({ label: 'Checking lights', tone: 'unknown' })
    expect(homeRoomLightSummary(['1'], { '1': live(true) }, false))
      .toEqual({ label: 'Disconnected', tone: 'offline' })
    expect(homeRoomLightSummary([], {}, true))
      .toEqual({ label: 'No lights', tone: 'unknown' })
  })
})
