import { writable } from 'svelte/store'

export const musicPlayerOpen = writable(false)

export function openMusicPlayer() {
  musicPlayerOpen.set(true)
}

export function closeMusicPlayer() {
  musicPlayerOpen.set(false)
}
