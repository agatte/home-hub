import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import route from '../../src/routes/quiet-atlas/insights/+page.svelte?raw'
import context from '../../src/lib/components/InsightsContextReadout.svelte?raw'

describe('Quiet Atlas phone-native Insights activity review (#461)', () => {
  it('keeps the only two source-qualified reads and their stale/disconnect lifecycle', () => {
    expect(route).toContain("fetch('/api/events/activity?days=1&limit=6&offset=0'")
    expect(route).toContain('invalidateRecentActivity(activityLog)')
    expect(route).toContain('recentActivityPresentation(activityLog, nowMs)')
    expect(route).toContain("cache: 'no-store'")
    expect(route).toContain('document.visibilityState')
    expect(context).toContain("fetch('/api/automation/status'")
    expect(context).toContain('invalidateHomeContextRead(snapshot)')
    expect(context).toContain('homeContextPresentation(snapshot, nowMs)')
    expect(context).toContain("cache: 'no-store'")
    expect(route).not.toMatch(/\b(apiPost|apiPut|activateScene|setLight|hueWrite)\s*\(/)
    expect(context).not.toMatch(/\b(apiPost|apiPut|activateScene|setLight|hueWrite)\s*\(/)
  })

  it('prioritizes a readable recent activity record without inventing live causal proof', () => {
    expect(route).toContain('aria-labelledby="record-title"')
    expect(route).toContain('aria-label="Recent recorded activities"')
    expect(route).toContain('Receipt freshness applies to this request')
    expect(route).toContain('What was observed?')
    expect(route).toContain('Why that state?')
    expect(route).toContain('What actually changed?')
    expect(route).toContain('not source-qualified in this preview')
    expect(route).toContain('DESIGN STUDY · NOT A LIVE FUSION OR DECISION TRACE')
    expect(route).toContain('href="/analytics?shell=quiet-atlas"')
  })

  it('places unverified decision explanation behind an accessible disclosure at every width', () => {
    expect(route).toContain('let studyOpen = false')
    expect(route).toContain('aria-controls="insights-study-content"')
    expect(route).toContain('aria-expanded={studyOpen}')
    expect(route).toContain('on:click={() => studyOpen = !studyOpen}')
    expect(route).toContain('class:phone-collapsed={!studyOpen}')
    expect(route).toContain('id="insights-study-content"')
    expect(route).toContain('.study-content.phone-collapsed {display:none;}')
    expect(route).toContain('.phone-study-toggle:focus-visible')
    expect(route).toContain('min-height:52px')
    expect(route).not.toContain('.phone-study-toggle {display:none;}')
  })

  it('keeps context source and stale uncertainty readable on a small screen', () => {
    expect(context).toContain('REST receipt is not source-sensor freshness')
    expect(context).toContain('CONTEXT NOT VERIFIED')
    expect(context).toContain('data-status={report.status}')
    expect(context).toContain('.context-readout {margin:0 0 22px;padding:14px 0 16px;}')
    expect(context).toContain('.context-note {font-size:12px;line-height:1.55;}')
    expect(route).toContain('env(safe-area-inset-bottom, 0px)')
    expect(route).toContain('white-space:normal')
    expect(route).toContain('.event time {font-size:14px;}')
  })

  it('compiles the two modified Svelte views with zero warnings', () => {
    for (const [filename, source] of [
      ['QuietAtlasMobileInsights.svelte', route],
      ['InsightsContextReadout.svelte', context],
    ]) {
      const compiled = compile(source, { filename, generate: 'dom', css: 'external' })
      expect(compiled.warnings, filename).toEqual([])
    }
  })
})
