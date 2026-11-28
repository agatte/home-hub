import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/svelte'

import { gameday } from '$lib/stores/gameday.js'
import GameDayPage from '../../src/routes/gameday/+page.svelte'
import GameDayPrototypePage from '../../src/routes/gameday/prototype/+page.svelte'
import GameDayNavigation from '$lib/components/gameday/GameDayNavigation.svelte'
import layout from '../../src/routes/+layout.svelte?raw'
import stadium from '../../src/lib/components/gameday/GameDayStadiumView.svelte?raw'

const EMPTY_STATE = {
  state: null,
  lastPlay: null,
  viewerState: null,
  viewerSync: null,
  viewerSyncLoaded: false,
  lastCelebration: null,
  schedule: [],
  scheduleLoaded: true,
}

beforeEach(() => {
  gameday.set({ ...EMPTY_STATE })
})

describe('Game Day route promotion', () => {
  it('renders the accepted stadium/fascia view on the canonical route', () => {
    render(GameDayPage)
    expect(screen.getByRole('img', { name: 'Futuristic Indianapolis Colts stadium scoreboard' }))
      .toHaveAttribute('src', '/gameday/futuristic-colts-clean-fascia.webp')
    expect(screen.getByRole('main', { name: 'Game Day stadium view' })).toBeInTheDocument()
  })

  it('keeps the old prototype URL as an alias to the same stadium view', () => {
    render(GameDayPrototypePage)
    expect(screen.getByRole('img', { name: 'Futuristic Indianapolis Colts stadium scoreboard' }))
      .toHaveAttribute('src', '/gameday/futuristic-colts-clean-fascia.webp')
    expect(screen.getByRole('main', { name: 'Game Day stadium view' })).toBeInTheDocument()
  })
})

describe('Game Day presentation and navigation polish', () => {
  it('links to the current owner workspaces without changing game state', () => {
    render(GameDayNavigation)
    for (const [name, href] of [
      ['Home', '/'], ['Control', '/quiet-atlas/control'], ['Music', '/quiet-atlas/music'],
      ['Insights', '/quiet-atlas/insights'], ['Settings', '/quiet-atlas/settings'], ['Game Day', '/gameday'],
    ]) expect(screen.getByRole('link', { name })).toHaveAttribute('href', href)
    expect(screen.getByRole('link', { name: 'Game Day' })).toHaveAttribute('aria-current', 'page')
    expect(layout).toContain('{#if isGamedayRoute}\n    <GameDayNavigation />')
    expect(layout).toContain('<NowPlayingChip />')
    expect(layout).toContain('<VitalStrip />')
  })

  it.each([GameDayPage, GameDayPrototypePage])('does not expose canonical future scores while viewer sync is pending (%s)', (Page) => {
    gameday.set({
      ...EMPTY_STATE,
      state: { status: 'in-progress', opponent: 'Ravens', score_colts: 31, score_opp: 17, clock: '1:11', quarter: 4 },
      viewerSyncLoaded: true,
      viewerSync: { enabled: true, presentation_active: true },
      viewerState: null,
    })
    render(Page)
    expect(screen.getByText('SYNCING TO LIVE TV')).toBeInTheDocument()
    expect(screen.getByText('NO SPOILERS')).toBeInTheDocument()
    expect(screen.queryByText('31')).not.toBeInTheDocument()
    expect(screen.queryByText('17')).not.toBeInTheDocument()
    expect(screen.queryByText('1:11')).not.toBeInTheDocument()
  })

  it('reflows existing scoreboard markup rather than adding a second score source', () => {
    expect(stadium).toContain('@media (max-aspect-ratio: 5/4)')
    expect(stadium.match(/\{view\.scoreColts\}/g)).toHaveLength(1)
    expect(stadium.match(/\{view\.scoreOpp\}/g)).toHaveLength(1)
    expect(stadium).toContain('buildPrototypePresentation(live, schedule, scheduleLoaded)')
  })
})
