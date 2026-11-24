import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { tick } from 'svelte'
import { render, fireEvent, cleanup } from '@testing-library/svelte'
import { brightnessAcceptanceFeedback } from '../../src/lib/quietAtlas/brightnessAcceptanceFeedback.js'
import BrightnessSuggestionCard from '../../src/lib/components/BrightnessSuggestionCard.svelte'
import { apiPost } from '../../src/lib/api.js'
import { addError } from '../../src/lib/stores/errors.js'
import { brightnessSuggestion } from '../../src/lib/stores/brightnessSuggestion.js'

vi.mock('../../src/lib/api.js',()=>({apiGet:vi.fn(async()=>({suggestions:[]})),apiPost:vi.fn()}))
vi.mock('../../src/lib/stores/errors.js',()=>({addError:vi.fn()}))
const receipt = {status:'partial_failure',preference_saved:['1','2'],preference_uncertain:[],preference_not_attempted:[],applied_now:[{light_id:'1',bri:100}],blocked:['2'],unavailable:[],uncertain:[],not_attempted:[]}
beforeEach(()=>{
  vi.resetAllMocks()
  brightnessSuggestion.set({id:17,kind:'brightness',confidence:80,sample_count:5,payload:{light_id:'1',mode:'working',period:'day',weather_class:'rain',suggested_bri:100,sample_count:5}})
})
afterEach(()=>{cleanup();brightnessSuggestion.set(null)})
describe('guarded brightness response consumer',()=>{
  it('surfaces partial physical outcomes after the suggestion disappears',async()=>{
    vi.mocked(apiPost).mockResolvedValue(receipt)
    const v=render(BrightnessSuggestionCard)
    await fireEvent.click(v.getByRole('button',{name:'Apply automatically'}))
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/api/rules/brightness-suggestion/accept/17',undefined,{timeout:20000})
    expect(v.queryByRole('button',{name:'Apply automatically'})).toBeNull()
    expect(v.getByRole('status').textContent).toContain('2 saved, 0 uncertain')
    expect(v.getByRole('status').textContent).toContain('1 acknowledged, 1 blocked')
    expect(addError).toHaveBeenCalledOnce()
  })
  it('distinguishes partial preference persistence from unattempted light requests',async()=>{
    vi.mocked(apiPost).mockResolvedValue({...receipt,preference_saved:['1'],preference_uncertain:['2'],applied_now:[],blocked:[],not_attempted:['1','2']})
    const v=render(BrightnessSuggestionCard)
    await fireEvent.click(v.getByRole('button',{name:'Apply automatically'}))
    expect(v.getByRole('status').textContent).toContain('1 saved, 1 uncertain')
    expect(v.getByRole('status').textContent).toContain('0 acknowledged, 0 blocked, 0 unavailable, 0 uncertain, 2 not attempted')
    expect(apiPost).toHaveBeenCalledOnce()
    expect(addError).toHaveBeenCalledOnce()
  })
  it('keeps earlier partial receipts identified until explicitly closed',async()=>{
    vi.mocked(apiPost).mockResolvedValueOnce(receipt).mockResolvedValueOnce({...receipt,preference_saved:['1'],preference_uncertain:['2'],applied_now:[],blocked:[],not_attempted:['1','2']})
    const v=render(BrightnessSuggestionCard)
    await fireEvent.click(v.getByRole('button',{name:'Apply automatically'}))
    const first=v.getByRole('status',{name:'Brightness suggestion #17'})
    expect(first.textContent).toContain('1 acknowledged, 1 blocked')
    brightnessSuggestion.update(current=>current ?? {id:18,kind:'brightness',confidence:80,sample_count:5,payload:{light_id:'2',mode:'working',period:'day',weather_class:'rain',suggested_bri:120,sample_count:5}})
    await tick()
    await fireEvent.click(v.getByRole('button',{name:'Apply automatically'}))
    expect(v.getByRole('status',{name:'Brightness suggestion #17'}).textContent).toContain('1 acknowledged, 1 blocked')
    expect(v.getByRole('status',{name:'Brightness suggestion #18'}).textContent).toContain('1 saved, 1 uncertain')
    await fireEvent.click(v.getByRole('button',{name:'Close suggestion #17 result'}))
    expect(v.queryByRole('status',{name:'Brightness suggestion #17'})).toBeNull()
    expect(v.getByRole('status',{name:'Brightness suggestion #18'})).toBeTruthy()
    expect(apiPost).toHaveBeenCalledTimes(2)
  })
  it('does not retry an attempted ID even if a stale report reappears',async()=>{
    vi.mocked(apiPost).mockResolvedValue(receipt)
    const v=render(BrightnessSuggestionCard)
    await fireEvent.click(v.getByRole('button',{name:'Apply automatically'}))
    brightnessSuggestion.set({id:17,kind:'brightness',confidence:80,sample_count:5,payload:{light_id:'1',mode:'working',period:'day',weather_class:'rain',suggested_bri:100,sample_count:5}})
    await tick()
    expect(v.getByRole('button',{name:'Apply automatically'}).hasAttribute('disabled')).toBe(true)
    expect(apiPost).toHaveBeenCalledOnce()
  })
  it('does not claim success for missing, inconsistent, or legacy receipts',()=>{
    for(const r of [null,{status:'ok',applied_now:[]},{...receipt,status:'ok'},{...receipt,blocked:['1']}]) expect(brightnessAcceptanceFeedback(r).message).toContain('unconfirmed')
    const good=brightnessAcceptanceFeedback({...receipt,status:'ok',blocked:[],applied_now:[{light_id:'1',bri:100},{light_id:'2',bri:120}]})
    expect(good.incomplete).toBe(false)
    expect(good.message).toContain('acknowledgement is not physical confirmation')
  })
})
