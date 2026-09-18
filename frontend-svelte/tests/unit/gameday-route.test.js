import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/svelte'

import { gameday } from '$lib/stores/gameday.js'
import GameDayPage from '../../src/routes/gameday/+page.svelte'
import GameDayPrototypePage from '../../src/routes/gameday/prototype/+page.svelte'

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
