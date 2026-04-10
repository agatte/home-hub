<script>
  import { onMount, onDestroy } from 'svelte'
  import { apiGet } from '$lib/api.js'

  /** @type {{ temp: number, feels_like: number, temp_min: number, temp_max: number, description: string, icon: string, humidity: number, wind_speed: number, city: string } | null} */
  let weather = null
  let error = false
  let refreshInterval

  // OWM icon code → simple weather icon SVG path
  const ICON_MAP = {
    '01d': 'M12 2v2m0 16v2m8-10h2M2 12h2m13.66-5.66 1.41-1.41M4.93 19.07l1.41-1.41m0-11.32L4.93 4.93m14.14 14.14-1.41-1.41M12 6a6 6 0 1 0 0 12 6 6 0 0 0 0-12Z',  // clear day
    '01n': 'M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79Z',  // clear night
    '02d': 'M12 2v2m0 16v2m8-10h2M2 12h2m13.66-5.66 1.41-1.41M12 6a6 6 0 0 0-3 11.2A4 4 0 0 0 13 20h5a3 3 0 0 0 .5-5.96A6 6 0 0 0 12 6Z',  // few clouds
    '02n': 'M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79ZM13 20h5a3 3 0 0 0 0-6',  // few clouds night
    '03d': 'M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10Z',  // clouds
    '03n': 'M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10Z',
    '04d': 'M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10Z',  // overcast
    '04n': 'M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10Z',
    '09d': 'M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10ZM8 22v-2m4 2v-2m4 2v-2',  // rain
    '09n': 'M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10ZM8 22v-2m4 2v-2m4 2v-2',
    '10d': 'M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10ZM8 22v-2m4 2v-2m4 2v-2',
    '10n': 'M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10ZM8 22v-2m4 2v-2m4 2v-2',
    '11d': 'M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10ZM13 16l-2 4h4l-2 4',  // thunderstorm
    '11n': 'M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10ZM13 16l-2 4h4l-2 4',
    '13d': 'M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10ZM8 16h.01M12 16h.01M16 16h.01M10 20h.01M14 20h.01',  // snow
    '13n': 'M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10ZM8 16h.01M12 16h.01M16 16h.01M10 20h.01M14 20h.01',
    '50d': 'M4 14h16M4 10h16M6 18h12M8 6h8',  // mist/fog
    '50n': 'M4 14h16M4 10h16M6 18h12M8 6h8',
  }

  function getIconPath(code) {
    return ICON_MAP[code] || ICON_MAP['03d']
  }

  async function fetchWeather() {
    try {
      const resp = await apiGet('/api/weather')
      weather = resp.weather
      error = false
    } catch {
      error = true
    }
  }

  onMount(() => {
    fetchWeather()
    refreshInterval = setInterval(fetchWeather, 600000) // 10 min
  })

  onDestroy(() => {
    clearInterval(refreshInterval)
  })

  $: showFeelsLike = weather && Math.abs(weather.temp - weather.feels_like) >= 5
</script>

{#if weather}
  <div class="weather-content">
    <div class="weather-main">
      <div class="weather-icon">
        <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d={getIconPath(weather.icon)} />
        </svg>
      </div>
      <div class="weather-temp">{weather.temp}°</div>
    </div>
    <div class="weather-desc">{weather.description}</div>
    {#if showFeelsLike}
      <div class="weather-feels">Feels like {weather.feels_like}°</div>
    {/if}
    <div class="weather-details">
      <span class="weather-detail">
        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z" /></svg>
        {weather.humidity}%
      </span>
      <span class="weather-detail">
        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.59 4.59A2 2 0 1 1 11 8H2m10.59 11.41A2 2 0 1 0 14 16H2m15.73-8.27A2.5 2.5 0 1 1 19.5 12H2" /></svg>
        {weather.wind_speed} mph
      </span>
      <span class="weather-detail">
        H:{weather.temp_max}° L:{weather.temp_min}°
      </span>
    </div>
  </div>
{:else if error}
  <div class="weather-empty">Weather unavailable</div>
{:else}
  <div class="weather-empty">Loading...</div>
{/if}

<style>
  .weather-content {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .weather-main {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .weather-icon {
    color: var(--text-secondary);
    flex-shrink: 0;
  }

  .weather-temp {
    font-family: var(--font-display);
    font-size: 42px;
    font-weight: 400;
    line-height: 1;
    color: var(--text-primary);
    letter-spacing: 0.02em;
  }

  .weather-desc {
    font-family: var(--font-body);
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary);
    text-transform: capitalize;
  }

  .weather-feels {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-secondary);
  }

  .weather-details {
    display: flex;
    gap: 12px;
    margin-top: 4px;
  }

  .weather-detail {
    display: flex;
    align-items: center;
    gap: 4px;
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
  }

  .weather-empty {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
    padding: 8px 0;
  }
</style>
