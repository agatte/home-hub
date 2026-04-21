// Weather — current conditions from NWS via /api/weather. Refreshed on
// init and every 5 minutes (the backend caches for 5 min too, so we don't
// pressure the NWS endpoint).
//
// Shape mirrors WeatherService.get_current():
//   { temp, feels_like, description, icon, humidity, wind_speed, city, ... }

import { writable } from 'svelte/store'
import { apiGet } from '$lib/api.js'

/** @type {import('svelte/store').Writable<any | null>} */
export const weather = writable(null)

/** @type {ReturnType<typeof setInterval> | null} */
let refreshTimer = null

async function refreshWeather() {
  try {
    const data = /** @type {any} */ (await apiGet('/api/weather'))
    if (data && data.weather) {
      weather.set(data.weather)
    } else if (data) {
      weather.set(data)
    }
  } catch {
    // leave stale value — UI falls back to "—"
  }
}

export function startWeatherPolling() {
  if (refreshTimer) return
  refreshWeather()
  refreshTimer = setInterval(refreshWeather, 5 * 60 * 1000)
}

export function stopWeatherPolling() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}
