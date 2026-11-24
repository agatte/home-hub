import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import journal from '../../src/routes/journal/+page.svelte?raw'
import personality from '../../src/routes/personality/+page.svelte?raw'
import journalRoute from '../../src/routes/quiet-atlas/journal/+page.svelte?raw'
import personalizationRoute from '../../src/routes/quiet-atlas/personalization/+page.svelte?raw'
import { MORE_DESTINATIONS, activeQuietAtlasSection, shouldUseQuietAtlasShell, isQuietAtlasReadOnlyPreview, shouldShowGlobalErrorToast } from '../../src/lib/quietAtlas/navigation.js'
import { rootRuntimeTargets } from '../../src/lib/quietAtlas/runtimeRoutePolicy431.js'

describe('Functional Journal and Personalization (#461)', () => {
  it('uses one implementation per feature, and both native and bookmarked paths use the redesigned owner shell', () => {
    expect(journalRoute).toContain('<JournalWorkspace />')
    expect(personalizationRoute).toContain('<PersonalizationWorkspace />')
    expect(MORE_DESTINATIONS.find(x=>x.id==='journal')).toMatchObject({href:'/quiet-atlas/journal',shell:false})
    expect(MORE_DESTINATIONS.find(x=>x.id==='personality')).toMatchObject({href:'/quiet-atlas/personalization',shell:false})
    for (const path of ['/journal','/personality','/quiet-atlas/journal','/quiet-atlas/personalization']) {
      expect(shouldUseQuietAtlasShell(path,new URLSearchParams())).toBe(true)
      expect(activeQuietAtlasSection(path)).toBe('more')
      expect(isQuietAtlasReadOnlyPreview(path)).toBe(false)
      expect(shouldShowGlobalErrorToast(path,new URLSearchParams())).toBe(true)
      expect(rootRuntimeTargets(path)).toEqual({general:true,gameday:false})
    }
  })
  it('keeps Journal date reads, generated summaries, escaping and explicit generation actions', () => {
    for (const token of ["apiGet('/api/journal/entries')","apiGet(`/api/journal/${date}`)","apiPost(`/api/journal/generate/${activeDate}`)","apiPost(`/api/journal/generate/${iso}`)","escapeHtml(s)","{@html renderMarkdown(markdown)}","on:click={regenerateActive}","on:click={generateYesterday}","on:change={(event) => selectDate(event.currentTarget.value)}","disabled={loading || regenerating}"]) expect(journal).toContain(token)
    expect(journal).toContain('No entries loaded')
  })
  it('retains explicit calibration and settings actions and distinguishes missing reports from disabled or empty', () => {
    for (const token of ["apiGet('/api/personality/mood/current')","apiPost('/api/personality/settings', body)","apiPost('/api/personality/calibration', payload)","on:click={submitCalibration}","on:click={snapToDetected}","personality_enabled","emotion_enabled","desktop_emotion_enabled","mood_ring_enabled","No mood report available","No history report available"]) expect(personality).toContain(token)
    expect(personality).toContain('not proof of how you feel')
    expect(personality).toContain('not a physical lighting reading')
  })
  it('compiles all redesigned pages and wrappers without warnings', () => {
    for(const source of [journal,personality,journalRoute,personalizationRoute]) expect(compile(source,{generate:'dom',css:'external'}).warnings).toEqual([])
  })
})
