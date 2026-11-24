import { describe,it,expect,vi,beforeEach,afterEach } from 'vitest'
import { render,fireEvent,cleanup } from '@testing-library/svelte'
import { tick } from 'svelte'
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
beforeEach(()=>{vi.clearAllMocks();connected.set(true);deviceStatus.set({hue:true,sonos:true,light_command_results:true});automation.set({...initialAutomationState,house_state:'home'});modeSuggestion.set(null);brightnessSuggestion.set(null);musicSuggestion.set(null)})
afterEach(()=>{cleanup();connected.set(false);deviceStatus.set({hue:false,sonos:false});automation.set(initialAutomationState);modeSuggestion.set(null);brightnessSuggestion.set(null);musicSuggestion.set(null)})
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
    automation.set({...initialAutomationState,house_state:'sleeping'})
    const v=render(Suggestions);await tick()
    expect(v.queryByRole('button',{name:'Switch'})).toBeNull()
    expect(v.queryByRole('button',{name:'Play'})).toBeNull()
    expect(apiPost).not.toHaveBeenCalled();expect(playFavorite).not.toHaveBeenCalled()
  })
})
