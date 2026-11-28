import { describe,it,expect,vi,beforeEach,afterEach } from 'vitest'
import { render,fireEvent,cleanup } from '@testing-library/svelte'
import { tick } from 'svelte'
import { receiveAmbientContext, resetAmbientContext } from '../../src/lib/quietAtlas/ambient.js'
import Off from '../../src/lib/components/QuietAtlasAllOff.svelte'
import Suggestions from '../../src/lib/components/QuietAtlasHomeSuggestions.svelte'
import { apiPost } from '../../src/lib/api.js'
import { connected,deviceStatus } from '../../src/lib/stores/connection.js'
import { automation,initialAutomationState } from '../../src/lib/stores/automation.js'
import { modeSuggestion } from '../../src/lib/stores/modeSuggestion.js'
import { brightnessSuggestion } from '../../src/lib/stores/brightnessSuggestion.js'
import { musicSuggestion } from '../../src/lib/stores/music.js'
import { playFavorite } from '../../src/lib/stores/init.js'
vi.mock('../../src/lib/api.js',()=>({apiGet:vi.fn(async()=>({suggestions:[]})),apiPost:vi.fn(async()=>({status:'ok'}))}))
vi.mock('../../src/lib/stores/init.js',()=>({playFavorite:vi.fn(async()=>{})}))
beforeEach(()=>{vi.resetAllMocks();vi.mocked(apiPost).mockResolvedValue({status:'ok',applied_mode:'gaming'});connected.set(true);deviceStatus.set({hue:true,sonos:true,light_command_results:true});automation.set({...initialAutomationState,house_state:'home'});receiveAmbientContext({house_state:'home'});modeSuggestion.set(null);brightnessSuggestion.set(null);musicSuggestion.set(null)})
afterEach(()=>{cleanup();resetAmbientContext();connected.set(false);deviceStatus.set({hue:false,sonos:false});automation.set(initialAutomationState);modeSuggestion.set(null);brightnessSuggestion.set(null);musicSuggestion.set(null)})
describe('Home parity actions',()=>{
  it('All Off never sends on mount or first tap, uses only existing bulk endpoint, and reports partial outcomes',async()=>{
    vi.mocked(apiPost).mockResolvedValueOnce({status:'partial_failure',updated:['1'],blocked:['2'],unavailable:['3'],uncertain:['4']})
    const v=render(Off)
    await fireEvent.click(v.getByRole('button',{name:'All Off'}))
    expect(apiPost).not.toHaveBeenCalled()
    await fireEvent.click(v.getByRole('button',{name:'Confirm All Off'}))
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/api/lights/all',{on:false},{timeout:20000})
    expect(v.getByText(/1 protected, 1 unavailable, 1 uncertain/)).toBeTruthy()
  })
  it('keeps a complete All Off acknowledgement quiet without asserting a physical result',async()=>{
    vi.mocked(apiPost).mockResolvedValueOnce({status:'ok',updated:['1'],blocked:[],unavailable:[],uncertain:[]})
    const v=render(Off)
    await fireEvent.click(v.getByRole('button',{name:'All Off'}))
    await fireEvent.click(v.getByRole('button',{name:'Confirm All Off'}))
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/api/lights/all',{on:false},{timeout:20000})
    expect(v.queryByRole('status')).toBeNull()
  })
  it('revokes All Off confirmation on disconnect',async()=>{
    const v=render(Off);await fireEvent.click(v.getByRole('button',{name:'All Off'}))
    connected.set(false);await tick()
    expect(v.queryByRole('button',{name:'Confirm All Off'})).toBeNull()
    expect(apiPost).not.toHaveBeenCalled()
  })
  it('addresses the exact shown suggestion, does not dispatch mode writes on render',async()=>{
    modeSuggestion.set({suggestion_id:17,rule_id:3,predicted_mode:'gaming',confidence:80,sample_count:12,message:''})
    const v=render(Suggestions);expect(apiPost).not.toHaveBeenCalled()
    await fireEvent.click(v.getByRole('button',{name:'Switch'}))
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/api/rules/suggestion/accept/17')
  })
  it('does not surface suggestion actions while Sleeping or Away',async()=>{
    modeSuggestion.set({suggestion_id:17,rule_id:3,predicted_mode:'gaming',confidence:80,sample_count:12,message:''})
    musicSuggestion.set({mode:'gaming',title:'Favorite'})
    automation.set({...initialAutomationState,house_state:'sleeping'});receiveAmbientContext({house_state:'sleeping'})
    const v=render(Suggestions);await tick()
    expect(v.queryByRole('button',{name:'Switch'})).toBeNull()
    expect(v.queryByRole('button',{name:'Play'})).toBeNull()
    expect(apiPost).not.toHaveBeenCalled();expect(playFavorite).not.toHaveBeenCalled()
  })
  const lightSuggestion=(id=12)=>({id,kind:'brightness',confidence:80,sample_count:8,payload:{mode:'working',period:'day',weather_class:'clear',light_id:'1',suggested_bri:100,sample_count:8}})
  it('hides malformed brightness suggestions rather than offering an invalid action',()=>{
    brightnessSuggestion.set({...lightSuggestion(),payload:{...lightSuggestion().payload,light_targets:{'999':100}}})
    const v=render(Suggestions)
    expect(v.queryByRole('button',{name:'Save preference'})).toBeNull()
    expect(apiPost).not.toHaveBeenCalled()
  })
  it('requires guarded Hue capability for brightness acceptance',()=>{
    brightnessSuggestion.set(lightSuggestion())
    deviceStatus.set({hue:true,sonos:true,light_command_results:false})
    const v=render(Suggestions)
    expect(v.getByRole('button',{name:'Save preference'}).hasAttribute('disabled')).toBe(true)
    expect(apiPost).not.toHaveBeenCalled()
  })
  it('uses the reviewed exact-ID brightness action and preserves partial receipts',async()=>{
    const receipt={status:'partial_failure',preference_saved:['1','2'],preference_uncertain:[],preference_not_attempted:[],applied_now:[{light_id:'1',bri:100}],blocked:['2'],unavailable:[],uncertain:[],not_attempted:[]}
    vi.mocked(apiPost).mockResolvedValueOnce(receipt)
    brightnessSuggestion.set(lightSuggestion())
    const v=render(Suggestions)
    await fireEvent.click(v.getByRole('button',{name:'Save preference'}))
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/api/rules/brightness-suggestion/accept/12',undefined,{timeout:20000})
    expect(v.getByRole('status',{name:'Brightness suggestion #12'}).textContent).toContain('1 acknowledged, 1 blocked')
    brightnessSuggestion.set(lightSuggestion(13));await tick()
    vi.mocked(apiPost).mockResolvedValueOnce({...receipt,preference_saved:['1'],preference_uncertain:['2'],applied_now:[],blocked:[],not_attempted:['1','2']})
    await fireEvent.click(v.getByRole('button',{name:'Save preference'}))
    expect(v.getByRole('status',{name:'Brightness suggestion #12'}).textContent).toContain('1 acknowledged, 1 blocked')
    expect(v.getByRole('status',{name:'Brightness suggestion #13'}).textContent).toContain('1 saved, 1 uncertain')
    brightnessSuggestion.set(lightSuggestion(12));await tick()
    expect(v.getByRole('button',{name:'Save preference'}).hasAttribute('disabled')).toBe(true)
    expect(apiPost).toHaveBeenCalledTimes(2)
  })
  it('does not arm All Off outside awake house state',async()=>{
    receiveAmbientContext({house_state:'sleeping'})
    const v=render(Off)
    expect(v.getByRole('button',{name:'All Off'}).hasAttribute('disabled')).toBe(true)
    await fireEvent.click(v.getByRole('button',{name:'All Off'}))
    expect(apiPost).not.toHaveBeenCalled()
  })
  it('does not enable actions before a fresh house-state report',()=>{
    resetAmbientContext()
    modeSuggestion.set({suggestion_id:17,rule_id:3,predicted_mode:'gaming',confidence:80,sample_count:12,message:''})
    const v=render(Suggestions)
    expect(v.queryByRole('button',{name:'Switch'})).toBeNull()
    expect(apiPost).not.toHaveBeenCalled()
  })
  it('does not dismiss a newer suggestion when an older response arrives',async()=>{
    /** @type {(value:any)=>void} */
    let finish = () => { throw new Error('Expected pending request') }
    vi.mocked(apiPost).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}))
    modeSuggestion.set({suggestion_id:17,rule_id:3,predicted_mode:'gaming',confidence:80,sample_count:12,message:''})
    const v=render(Suggestions)
    await fireEvent.click(v.getByRole('button',{name:'Switch'}))
    modeSuggestion.set({suggestion_id:18,rule_id:3,predicted_mode:'working',confidence:85,sample_count:14,message:''})
    finish({status:'ok',applied_mode:'gaming'});await tick()
    expect(v.getByText('Switch to Working?')).toBeTruthy()
  })
})
