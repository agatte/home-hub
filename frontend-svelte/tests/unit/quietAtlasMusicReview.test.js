import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import music from '../../src/routes/quiet-atlas/music/+page.svelte?raw'
import legacy from '../../src/routes/music/+page.svelte?raw'
import workspace from '../../src/lib/components/MusicWorkspace.svelte?raw'
import player from '../../src/lib/components/QuietAtlasNowPlaying.svelte?raw'
import approved from '../../src/lib/components/ApprovedAppleMusicEntry.svelte?raw'
import { activeQuietAtlasSection, isQuietAtlasReadOnlyPreview, shouldShowGlobalErrorToast, shouldUseQuietAtlasShell } from '../../src/lib/quietAtlas/navigation.js'
import { musicPlaybackReport, recentPlaybackReport } from '../../src/lib/quietAtlas/musicPlaybackReport.js'

describe('Functional redesigned Music (#461)', () => {
  it('uses one workspace for canonical Music and existing bookmarks, with visible functional failures', () => {
    for (const source of [music, legacy]) expect(source).toContain('<MusicWorkspace />')
    for (const route of ['/music','/quiet-atlas/music']) {
      expect(activeQuietAtlasSection(route)).toBe('music')
      expect(shouldUseQuietAtlasShell(route,new URLSearchParams())).toBe(true)
      expect(isQuietAtlasReadOnlyPreview(route)).toBe(false)
      expect(shouldShowGlobalErrorToast(route,new URLSearchParams())).toBe(true)
    }
    expect(isQuietAtlasReadOnlyPreview('/quiet-atlas/music/artist-review')).toBe(true)
    expect(workspace).not.toContain("withQuietAtlasShell('/music')")
  })
  it('retains every existing music tool and separate exact track review, not automatic playback', () => {
    for (const component of ['ShadowDiscoveryPanel','ApprovedAppleMusicEntry','PrepareSonosAction','TasteProfileCard','ModePlaylistMapper','MusicBanditDiagnostics','QuietAtlasNowPlaying']) expect(workspace).toContain('<'+component)
    expect(workspace).toContain('selectedAppleTrack = { provider_id: providerId }')
    expect(workspace).toContain('before separately approving or starting playback')
    expect(approved).toContain('id="approved-apple-track"')
    expect(workspace).toContain('href="#approved-apple-track"')
    expect(workspace).not.toContain('apiPost(')
    expect(workspace).not.toContain('sonosCommand(')
  })
  it('prioritizes one player and discovery before secondary tools on both aliases', () => {
    expect(workspace.match(/<QuietAtlasNowPlaying \/>/g)).toHaveLength(1)
    expect(workspace.match(/<ListeningChoices \/>/g)).toHaveLength(1)
    expect(workspace.indexOf('<QuietAtlasNowPlaying />')).toBeLessThan(workspace.indexOf('<ListeningChoices />'))
    expect(workspace.indexOf('<ListeningChoices />')).toBeLessThan(workspace.indexOf('id="music-tools"'))
    expect(workspace).toContain('let toolsOpen = false')
    expect(workspace).toContain('bind:open={toolsOpen}')
    expect(player).not.toContain('role="progressbar"')
  })
  it('validates speaker reports and neutralizes disconnected, stale or invalid status', () => {
    const value = {state:'PLAYING',track:'Reported track',artist:'Artist',album:'Album',art_url:'/art.jpg',volume:24}
    const report = musicPlaybackReport(value)
    expect(report).toEqual(value)
    expect(recentPlaybackReport(report,1000,2000,true)).toEqual(report)
    expect(recentPlaybackReport(report,1000,31001,true)).toBeNull()
    expect(recentPlaybackReport(report,1000,2000,false)).toBeNull()
    expect(recentPlaybackReport(report,null,2000,true)).toBeNull()
    for (const patch of [{state:'error'},{state:'disconnected'},{volume:101},{track:null}]) expect(musicPlaybackReport({...value,...patch})).toBeNull()
    expect(musicPlaybackReport({...value,art_url:'javascript:bad'})?.art_url).toBe('')
    expect(player).toContain("sonosCommand(action, params)")
    expect(player).toContain('sonosLiveReport.subscribe')
    expect(player).not.toContain('sonos.subscribe')
    expect(player).toContain('input.value = String(current.volume)')
    expect(player).toContain("fetch('/api/sonos/status'")
    expect(player).toContain('pending?.abort()')
    expect(player).toContain('disabled={!current}')
    expect(player).not.toContain('apiPost(')
    expect(player).not.toContain('sonos.set(')
  })
  it('compiles native routes and workspace without warnings', () => {
    for(const source of [music,legacy,workspace,player]) expect(compile(source,{generate:'dom',css:'external'}).warnings).toEqual([])
  })
})
