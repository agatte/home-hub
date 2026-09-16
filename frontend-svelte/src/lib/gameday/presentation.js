const KIOSK_TIME_ZONE = 'America/Indiana/Indianapolis'

export function formatGamePeriod(status, quarter) {
  if (status === 'final') return 'FINAL'
  if (status === 'pregame') return 'PREGAME'

  const period = Number(quarter)
  if (!Number.isFinite(period) || period <= 0) return 'GAME DAY'
  if (period === 1) return '1ST QUARTER'
  if (period === 2) return '2ND QUARTER'
  if (period === 3) return '3RD QUARTER'
  if (period === 4) return '4TH QUARTER'
  if (period === 5) return 'OVERTIME'
  return `${period - 4}OT`
}

function formatKickoff(iso) {
  if (!iso) return { date: 'TBD', time: 'KICKOFF TBD', full: 'KICKOFF TBD' }
  const kickoff = new Date(iso)
  if (Number.isNaN(kickoff.getTime())) {
    return { date: 'TBD', time: 'KICKOFF TBD', full: 'KICKOFF TBD' }
  }

  const date = kickoff.toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', timeZone: KIOSK_TIME_ZONE,
  }).toUpperCase()
  const time = kickoff.toLocaleTimeString('en-US', {
    weekday: 'short', hour: 'numeric', minute: '2-digit',
    timeZone: KIOSK_TIME_ZONE,
  }).toUpperCase()

  return { date, time, full: `${date} · ${time}` }
}

export function buildViewerSyncPendingPresentation(canonical) {
  const opponent = (canonical?.opponent || 'TBD').toUpperCase()
  return {
    isLive: true,
    opponent,
    scoreColts: '--',
    scoreOpp: '--',
    periodLabel: 'SYNCING TO LIVE TV',
    clock: '--',
    subline: 'ALIGNING WITH HULU LIVE',
    drive: null,
    sideLabel: 'VIEWER SYNC',
    sidePrimary: 'ALIGNING',
    sideSecondary: 'NO SPOILERS',
  }
}

export function buildPrototypePresentation(live, schedule = [], scheduleLoaded = false) {
  const isLive = Boolean(
    live && typeof live === 'object' && live.status !== 'no-game',
  )

  if (isLive) {
    const opponent = (live.opponent || 'TBD').toUpperCase()
    const possession = live.possession === 'colts'
      ? 'COLTS BALL'
      : live.possession === 'opp'
        ? `${opponent} BALL`
        : 'AWAITING DRIVE'
    const subline = live.status === 'final'
      ? 'FINAL'
      : live.status === 'pregame'
        ? 'KICKOFF PENDING'
        : live.possession === 'colts'
          ? 'COLTS POSSESSION'
          : live.possession === 'opp'
            ? `${opponent} POSSESSION`
            : 'GAME DAY'

    const drive = live.current_drive ?? null
    const side = live.status === 'final' && !drive
      ? { label: 'GAME STATUS', primary: 'FINAL', secondary: 'DRIVE CLOSED' }
      : live.status === 'pregame' && !drive
        ? { label: 'GAME STATUS', primary: 'KICKOFF PENDING', secondary: 'NO ACTIVE DRIVE' }
        : { label: 'CURRENT DRIVE', primary: possession, secondary: 'DRIVE DATA PENDING' }

    return {
      isLive: true,
      opponent,
      scoreColts: live.score_colts ?? 0,
      scoreOpp: live.score_opp ?? 0,
      periodLabel: formatGamePeriod(live.status, live.quarter),
      clock: live.clock || '--',
      subline,
      drive,
      sideLabel: side.label,
      sidePrimary: side.primary,
      sideSecondary: side.secondary,
    }
  }

  const nextGame = Array.isArray(schedule) && schedule.length > 0 ? schedule[0] : null
  const opponent = (nextGame?.opponent || 'TBD').toUpperCase()
  const kickoff = formatKickoff(nextGame?.kickoff_utc)

  return {
    isLive: false,
    opponent,
    scoreColts: '--',
    scoreOpp: '--',
    periodLabel: nextGame ? 'NEXT GAME' : scheduleLoaded ? 'NO GAME' : 'LOADING',
    clock: nextGame ? kickoff.date : '--',
    subline: nextGame ? kickoff.time : scheduleLoaded ? 'NO GAME SCHEDULED' : 'SCHEDULE LOADING',
    drive: null,
    sideLabel: nextGame ? 'UP NEXT' : 'GAME STATUS',
    sidePrimary: nextGame ? opponent : 'NO ACTIVE GAME',
    sideSecondary: nextGame
      ? kickoff.full
      : scheduleLoaded
        ? 'NO GAME SCHEDULED'
        : 'SCHEDULE LOADING',
  }
}
