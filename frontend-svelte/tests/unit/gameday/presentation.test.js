import { describe, expect, it } from 'vitest'

import {
  buildPrototypePresentation,
  buildViewerSyncPendingPresentation,
  formatGamePeriod,
} from '$lib/gameday/presentation.js'

describe('formatGamePeriod', () => {
  it('labels regulation and overtime periods truthfully', () => {
    expect(formatGamePeriod('in-progress', 1)).toBe('1ST QUARTER')
    expect(formatGamePeriod('in-progress', 4)).toBe('4TH QUARTER')
    expect(formatGamePeriod('in-progress', 5)).toBe('OVERTIME')
    expect(formatGamePeriod('in-progress', 6)).toBe('2OT')
  })

  it('lets lifecycle status override a stale quarter value', () => {
    expect(formatGamePeriod('pregame', 0)).toBe('PREGAME')
    expect(formatGamePeriod('final', 4)).toBe('FINAL')
  })
})

describe('buildPrototypePresentation', () => {
  it('uses verified schedule data instead of fabricating a no-game score', () => {
    const view = buildPrototypePresentation(null, [
      { opponent: 'Houston Texans', kickoff_utc: '2026-09-20T17:00:00Z' },
    ], true)

    expect(view.isLive).toBe(false)
    expect(view.opponent).toBe('HOUSTON TEXANS')
    expect(view.scoreColts).toBe('--')
    expect(view.scoreOpp).toBe('--')
    expect(view.periodLabel).toBe('NEXT GAME')
    expect(view.sideLabel).toBe('UP NEXT')
    expect(view.sidePrimary).toBe('HOUSTON TEXANS')
    expect(view.sideSecondary).toContain('SEP 20')
  })

  it('shows an explicit no-game state when the schedule is empty', () => {
    const view = buildPrototypePresentation(null, [], true)

    expect(view.periodLabel).toBe('NO GAME')
    expect(view.sidePrimary).toBe('NO ACTIVE GAME')
    expect(view.sideSecondary).toBe('NO GAME SCHEDULED')
    expect(view.scoreColts).toBe('--')
    expect(view.scoreOpp).toBe('--')
  })

  it('preserves authoritative live score, clock, possession, and drive data', () => {
    const drive = { plays: 6, yards: 48, elapsed: '2:11' }
    const view = buildPrototypePresentation({
      status: 'in-progress', opponent: 'Ravens', score_colts: 14,
      score_opp: 10, quarter: 3, clock: '4:26', possession: 'colts',
      current_drive: drive,
    }, [], true)
    expect(view.isLive).toBe(true)
    expect(view.opponent).toBe('RAVENS')
    expect(view.scoreColts).toBe(14)
    expect(view.scoreOpp).toBe(10)
    expect(view.periodLabel).toBe('3RD QUARTER')
    expect(view.clock).toBe('4:26')
    expect(view.subline).toBe('COLTS POSSESSION')
    expect(view.drive).toBe(drive)
  })

  it('does not describe a drive before kickoff or after final', () => {
    const pregame = buildPrototypePresentation({
      status: 'pregame', opponent: 'Texans', quarter: 0,
    }, [], true)
    expect(pregame.sideLabel).toBe('GAME STATUS')
    expect(pregame.sidePrimary).toBe('KICKOFF PENDING')
    expect(pregame.sideSecondary).toBe('NO ACTIVE DRIVE')

    const final = buildPrototypePresentation({
      status: 'final', opponent: 'Texans', quarter: 4,
      score_colts: 24, score_opp: 20,
    }, [], true)
    expect(final.periodLabel).toBe('FINAL')
    expect(final.sideLabel).toBe('GAME STATUS')
    expect(final.sidePrimary).toBe('FINAL')
    expect(final.sideSecondary).toBe('DRIVE CLOSED')
  })
})


describe('buildViewerSyncPendingPresentation', () => {
  it('shows a truthful no-spoiler placeholder while the first viewer state catches up', () => {
    const view = buildViewerSyncPendingPresentation({ opponent: 'Ravens' })

    expect(view.isLive).toBe(true)
    expect(view.opponent).toBe('RAVENS')
    expect(view.scoreColts).toBe('--')
    expect(view.scoreOpp).toBe('--')
    expect(view.periodLabel).toBe('SYNCING TO LIVE TV')
    expect(view.subline).toBe('ALIGNING WITH HULU LIVE')
    expect(view.sideSecondary).toBe('NO SPOILERS')
  })
})
