import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import ListeningChoices from '../../src/lib/components/ListeningChoices.svelte'
import { apiPost } from '../../src/lib/api.js'

vi.mock('../../src/lib/api.js', () => ({ apiPost: vi.fn() }))

const post = vi.mocked(apiPost)

beforeEach(() => vi.resetAllMocks())
afterEach(cleanup)

const album = {
  id: 'itunes_album:100', kind: 'album', title: 'Example Album', artist: 'Example Artist',
  familiarity: 'exploratory', matched_track: 'Example Track',
  apple_music_url: 'https://music.apple.com/us/album/example/100',
  sonos: 'not_verified',
}
const response = (choices, status = 'partial') => ({
  listening: { choices, status, actuation_allowed: false, session_playback_available: false },
})

it('requests a balanced mood preview only on deliberate selection and shows real destination', async () => {
  post.mockResolvedValue(response([album]))
  render(ListeningChoices)
  expect(apiPost).not.toHaveBeenCalled()
  await fireEvent.click(screen.getByRole('button', { name: 'Relaxing' }))
  expect(apiPost).toHaveBeenCalledExactlyOnceWith('/api/music/request/preview', {
    request: 'relaxing', listening: true, count: 6, tracks_per_artist: 3,
  }, { timeout: 30000 })
  const link = await screen.findByRole('link', { name: 'Open in Apple Music' })
  expect(link).toHaveAttribute('href', album.apple_music_url)
  expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  expect(screen.getByText('Example Album')).toBeInTheDocument()
  expect(screen.getByText(/Continuous listening is not connected yet/)).toBeInTheDocument()
})

it('submits a free-text mood and never offers an unverified external link or play command', async () => {
  post.mockResolvedValue(response([
    { ...album, apple_music_url: 'https://evil.example/us/album/example/100' },
    { id: 'artist_mix:21,22', kind: 'artist_mix', title: 'Example mix', tracks: [{ title: 'Song 1' }, { title: 'Song 2' }] },
    { id: 'sonos_favorite:123', kind: 'favorite', title: 'Example favorite' },
  ]))
  render(ListeningChoices)
  await fireEvent.input(screen.getByRole('textbox', { name: 'Describe your mood' }), { target: { value: 'Relaxing but upbeat' } })
  await fireEvent.click(screen.getByRole('button', { name: 'Find music' }))
  await screen.findByText('Example mix')
  expect(apiPost).toHaveBeenCalledExactlyOnceWith('/api/music/request/preview', expect.objectContaining({ request: 'Relaxing but upbeat' }), expect.anything())
  expect(screen.queryByRole('link', { name: 'Open in Apple Music' })).not.toBeInTheDocument()
  expect(screen.getByText('Mix playback unavailable for this selection')).toBeInTheDocument()
  expect(screen.getByText('Sonos favorite · session start not connected yet')).toBeInTheDocument()
})

it('renders honest empty results and does not reuse stale choices on error', async () => {
  post.mockResolvedValueOnce(response([album])).mockResolvedValueOnce(response([], 'unavailable')).mockRejectedValueOnce(new Error('offline'))
  render(ListeningChoices)
  await fireEvent.click(screen.getByRole('button', { name: 'Party' }))
  await screen.findByText('Example Album')
  await fireEvent.click(screen.getByRole('button', { name: 'Something new' }))
  await screen.findByText('No suitable choices yet. Try a different mood.')
  expect(screen.queryByText('Example Album')).not.toBeInTheDocument()
  await fireEvent.click(screen.getByRole('button', { name: 'Upbeat' }))
  await screen.findByRole('alert')
  expect(screen.queryByText('Example Album')).not.toBeInTheDocument()
})

it('blocks repeated requests while loading and fails closed on missing listening contract', async () => {
  /** @type {(value: any) => void} */
  let resolve = () => { throw new Error('request has not started') }
  post.mockImplementation(() => new Promise(r => { resolve = r }))
  render(ListeningChoices)
  await fireEvent.click(screen.getByRole('button', { name: 'Focus' }))
  expect(screen.getByRole('button', { name: 'Party' })).toBeDisabled()
  await fireEvent.click(screen.getByRole('button', { name: 'Party' }))
  expect(apiPost).toHaveBeenCalledTimes(1)
  resolve({ listening: { choices: [album] } })
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Listening choices are unavailable'))
  expect(screen.queryByText('Example Album')).not.toBeInTheDocument()
})

it('starts only the selected ticket once and reports confirmed playback', async () => {
  const mix = { id: 'artist_mix:21,22', kind: 'artist_mix', title: 'Example mix', tracks: [{ title: 'One' }, { title: 'Two' }] }
  post.mockResolvedValueOnce({
    ...response([mix]),
    listening_selection: { status: 'selection_available', token: 'test-ticket', choice_ids: [mix.id], actuation_allowed: false },
  }).mockResolvedValueOnce({ status: 'started' })
  render(ListeningChoices)
  await fireEvent.click(screen.getByRole('button', { name: 'Relaxing' }))
  const play = await screen.findByRole('button', { name: 'Play on Sonos' })
  await fireEvent.click(play)
  expect(post).toHaveBeenNthCalledWith(2, '/api/music/listening/start', { token: 'test-ticket', choice_id: mix.id }, { timeout: 120000 })
  await screen.findByText('Your mix started on Sonos.')
  expect(screen.queryByRole('button', { name: 'Play on Sonos' })).not.toBeInTheDocument()
})
