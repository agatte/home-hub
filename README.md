# HomeHub

HomeHub is a personal apartment automation system. It coordinates Philips Hue
lighting, Sonos audio, presence and activity context, routines, and a custom
dashboard for one home.

The project is intentionally specific to my apartment and habits. It is not a
general-purpose smart-home platform, but the repository may still be useful as
an example of a small, local-first automation system.

## How it is arranged

The current always-on host/server is a Dell Latitude running Ubuntu. It runs the
FastAPI backend, scheduling and automation services, Hue and Sonos connections,
and the SvelteKit dashboard in a Firefox kiosk. Its camera can contribute
living-room/couch presence context; it is not a bedroom or bed-zone sensor.

A Windows desktop can run optional companion agents for desk presence, process
activity, screen colour, ambient audio, and monitor or peripheral integration.
Those signals enrich the system but are not required for the server, dashboard,
or core Hue and Sonos controls to run. When a source is absent or stale, its
authority should degrade explicitly rather than being treated as current truth.
They report observations to the HomeHub backend over HTTP; they are not imported
into or run inside the server process.

HomeHub has ordinary activity modes such as Working, Gaming, Watching, Relax,
Cooking, Social, Sleeping, and Game Day. Travel is different: it is a
persistent HOME/TRAVEL host-lifecycle state above activity modes, not another
activity classification. That lifecycle design is tracked separately from the
open work to remove the portable Latitude and apartment DNS as single points of
failure.

At a high level:

```text
optional desktop context ----\
Latitude context -------------+--> FastAPI automation/services --> Hue + Sonos
time, weather, history -------/               |
                                                +--> WebSocket/API --> dashboard
```

## What it does

- Adaptive Hue lighting with per-mode and time-of-day states, curated scenes,
  protected-light rules, smooth transitions, external-change reconciliation,
  and selected preference learning.
- Presence- and context-aware automation that combines physical observations,
  activity, time, weather, explicit overrides, away state, and source
  freshness. Where the current authority gate is supported, fresh physical-room
  evidence outranks software guesses; broader consumer adoption remains an
  active rollout.
- Sonos playback, favorites, mode-to-playlist mapping, text-to-speech,
  contextual music selection, and optional weather ambience.
- A Colts-focused Game Day experience with schedule and play data, automatic
  mode timing, scoring celebrations, lighting and TTS choreography, and a 3D
  field view.
- A responsive SvelteKit dashboard and always-on kiosk with live WebSocket
  updates, mode-aware visuals, controls, analytics, journal, guest, settings,
  and Game Day views.
- Optional contextual and ML layers, including fused confidence signals,
  adaptive lighting, music selection, screen-colour extraction, and shadow-mode
  predictors. These lanes have different authority levels; code presence alone
  does not establish that a lane is configured, healthy, or effective live.

## Architecture

- Backend: Python, FastAPI, async services, WebSockets, SQLAlchemy, and SQLite.
- Frontend: SvelteKit 2, Svelte 4, Vite, Three.js, and Threlte.
- Device integrations: Philips Hue v1/v2 APIs and Sonos through SoCo.
- Optional context: MediaPipe camera observations, desktop process and screen
  agents, audio classification, weather, geofence events, and local routines.
- Production: Ubuntu on the Latitude, with systemd user services and a locally
  served static frontend on port 8000.

The backend is the composition and policy boundary. It owns automation state,
device writes, event logging, and WebSocket broadcasts. The frontend is a live
control and explanation surface; optional agents report observations rather
than becoming independent automation authorities.

## Local development

CI currently uses Python 3.13 and Node.js 22. Copy the example environment file
and provide only the integrations you intend to use; do not commit `.env`.

```bash
Copy-Item .env.example .env  # PowerShell; use `cp .env.example .env` on macOS/Linux

python -m venv .venv
python -m pip install -r requirements.txt

cd frontend-svelte
npm ci
npm run build
cd ..

python run.py
```

The backend serves the built frontend at `http://localhost:8000`.
Local Hue, Sonos, and other integrations require their corresponding `.env`
values.

For frontend development, run the backend and Vite separately:

```bash
cd frontend-svelte
npm run dev
```

Vite listens on `http://localhost:3001` and proxies API and WebSocket traffic to
port 8000.

Operational notes: Hue v2 bridge HTTPS uses the bridge's self-signed
certificate, and time-sensitive behavior uses the
`America/Indiana/Indianapolis` timezone.

Useful checks:

```bash
python -m ruff check backend
python -m pytest tests -v

cd frontend-svelte
npm run check
npm run test:unit
npm run build
```

Hardware-dependent behavior should normally be exercised with tests or fakes
unless a live-device check is explicitly intended.

## Documentation

- [Project specification](docs/PROJECT_SPEC.md) — authoritative cross-system
  product direction, current architecture, status boundaries, and roadmap.
- [Documentation index](docs/README.md) — subsystem specs, design notes,
  historical audits, and operational references.
- [Game Day specification](docs/GAMEDAY_SPEC.md) — detailed Game Day behavior
  and implementation contract.

Dated audits and incident notes are evidence from a point in time, not the
current architecture by themselves.

## Developer tooling

The repository includes supporting automation for development and operations,
including Codex-oriented guidance and an MCP integration for inspecting or
controlling a configured HomeHub instance. These are developer conveniences,
not the product's central feature or an independent source of automation
policy.

## Project note

This is a personal project and is not affiliated with or endorsed by Philips
Hue, Sonos, Apple, ESPN, the Indianapolis Colts, or the NFL. The repository does
not currently include a license file.
