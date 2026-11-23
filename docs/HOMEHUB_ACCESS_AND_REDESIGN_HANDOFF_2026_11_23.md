# HomeHub access, ports, naming, and redesign handoff — 2026-11-23

> **Status:** Dated verified/owner-reported operational checkpoint, not a new network or deployment proposal.
> **Primary user experience owner:** [#461](https://github.com/agatte/home-hub/issues/461), under [#157](https://github.com/agatte/home-hub/issues/157).
> **Policy/source of truth:** [PROJECT_SPEC.md](PROJECT_SPEC.md), the checked-in code and live issue evidence. This page summarizes what is deployed, what is still uncertain, and the safe resume point for UI work. It does not supersede the product spec, create host authority, or grant future deployment permission.

## Answer to the owner: why two ports and why no clean hostname?

There is **one HomeHub FastAPI process and one frontend build**, not two independently maintained websites. The app's `run.py` starts ordinary HTTP on port **8000** and, when its TLS cert/key are configured, adds a **second TLS socket** on port **8443**, sharing the same app, backend state, Hue/Sonos integrations and lifecycle. The second socket exists to provide private-LAN HTTPS/WSS for owner access on iPhone **without breaking the kiosk, companion agents, integrations, or existing localhost/API URLs**. It is not a new service, a port migration, or a new version of the interface.

| Entry | Purpose / current expectation | Important boundary |
| --- | --- | --- |
| `http://localhost:8000/` **on Latitude** | Existing Firefox kiosk startup; redesigned Home at `/`. | Same-machine loopback traffic. Kiosk launch/recycle config stays here. |
| `http://192.168.86.210:8000/` **on home LAN** | Legacy local HTTP access and existing companion/automation integrations; also serves redesigned Home. | Server binds `0.0.0.0:8000`; **not** exclusively localhost. Existing plain WS read behavior and some legacy private-IP auth bypasses are less strict than the TLS owner path. Preserve for compatibility; do not claim it is already fully locked down. |
| `https://192.168.86.210:8443/` **on home LAN** | Encrypted iPhone/owner UI and secure WSS; same redesigned Home. | TLS listener is restricted in code to an explicitly configured private/loopback address; WSS requires an authenticated owner session. Existing certificate trust setup on the iPhone is a separate requirement. Not a public Internet endpoint. |
| `/classic` **on either listener** | Preserved earlier functional dashboard as a rollback/fallback **route**, not a separate 8000-only old site. | Root `/` maps to the redesigned `quiet-atlas/home` page on both ports. A device showing old root content may have cached frontend assets. |
| `http://homehub-dashboard.local:8000` | Existing convenience hostname from Avahi/mDNS; avoids typing the numeric IP on clients that resolve mDNS. | Still requires a port and **does not automatically provide valid HTTPS**. Device-specific mDNS reachability must be checked when needed. |
| `homehub.lan` | Local DNS record in Pi-hole, along with other `.lan` records. | **Not a reliably usable Google Nest Wi-Fi client URL**: the router has returned authoritative NXDOMAIN for `.lan` rather than forwarding queries to Pi-hole. Works only for devices querying Pi-hole directly. Do **not** insert `.local` into Pi-hole; mDNS owns it. |

The network/DNS evidence and distinction between Google Wi-Fi router DNS, Pi-hole, Unbound, mDNS, and fallback are in [PROJECT_SPEC.md](PROJECT_SPEC.md), **Network & DNS**. This work does not change Google Wi-Fi, Pi-hole, DHCP/DNS, firewall rules, certs, or ports.

**Why there is no friendly, portless HTTPS URL yet:** no reliable, client-trusted local HTTPS hostname on standard port 443 has been completed. A future `https://home.gatte-home.com`-style address is only a *candidate*, not an existing endpoint or approved exposure. It would require careful local DNS routing, certificate/name matching and renewal, and a listener/reverse-proxy route on 443; verify Google Nest compatibility, private-only access and the interaction with existing public `gatte-home.com` services first. A hostname by itself neither removes a port nor establishes HTTPS. **Defer this optional polish** until after the redesign is genuinely usable; do not interrupt #461 with more network work.

## Kiosk and other client compatibility

- The **Latitude** kiosk autostart `~/.config/autostart/home-hub-kiosk.desktop` is documented to open **`http://localhost:8000`** fullscreen. Its `scripts/recycle-kiosk.sh` also defaults `KIOSK_URL` to `http://localhost:8000`. Neither was changed by the iPhone HTTPS release. It displays the *same redesigned root* as the phone, styled for the kiosk viewport.
- `deployment/home-hub.service` runs `venv/bin/python run.py`; both configured listeners share this process. No duplicate lighting automation, separate app database, or second scheduler arises from port 8443.
- Existing local Windows desktop/context agents and other integrations reference `:8000`. Arbitrarily closing/changing this listener could break observations, automation updates, monitoring and kiosk behavior. Later tightening belongs to an explicit inventory/migration, not a UI-redesign shortcut.
- Public **guest** access is a distinct invitation-scoped gateway (loopback `:8003` plus public guest ingress) and Google Guest Wi-Fi is separately isolated. Its Return Home activation regression remains [#540](https://github.com/agatte/home-hub/issues/540). The Alexa/Shortcut Cloudflare ingress is separately allowlisted through loopback tunnel proxy `:8002`. Neither should be casually pointed at owner `:8443` or made a wildcard proxy.
- Do not merge the unrelated [#287/#293](https://github.com/agatte/home-hub/issues/287) identity/systemd migration or host security program into #461 unless a real, demonstrated release blocker exists.

## Why every widget initially showed “disconnected” over HTTPS

This was **one lost WSS session**, not simultaneous failure of Hue, weather, history and sensors:

1. After [PR #541](https://github.com/agatte/home-hub/pull/541) deployed, read-only browser QA observed `GET /api/lights`, `/api/weather` and `/api/events/activity` returning HTTP 200 over both LAN HTTP and LAN HTTPS.
2. Plain `ws://192.168.86.210:8000/ws` connected and received live messages. Anonymous `wss://192.168.86.210:8443/ws` handshake returned **403**; the redesigned Home labeled most live panels “HomeHub disconnected.”
3. `backend/main.py` explicitly requires `valid_session()` before admitting secure WSS, while the earlier owner sessions lived only in the server process. Restarting the backend for deployment erased them, despite Safari retaining an old cookie.
4. The owner signed in using **Unlock** on HTTPS and live data returned. They then reported being logged out again much sooner than the original eight-hour timeout, making this a real UX failure beyond the first expected deploy restart.

**Status UI follow-up:** “Owner sign-in needed” must be distinguishable from “HomeHub offline” (and from actual stale/disconnected sensors), without turning off WSS auth.

## Trusted-device login fix — shipped and owner-tested

[PR #542](https://github.com/agatte/home-hub/pull/542), merged as **`b1e9db02`**, replaced the original eight-hour process-memory-only owner sessions with **365-day device-specific sessions persisted** in `data/owner_sessions.sqlite3`. The store contains SHA-256 hashes of random session tokens rather than bearer secrets. Cookies remain `Secure`, `HttpOnly`, `SameSite=Strict`; owner Origin/Host checks and WSS authorization remain. **Lock** revokes the durable record; the cookie lifetime is fixed, not indefinite.

- Exact-head [CI run #45286180062](https://github.com/agatte/home-hub/actions/runs/45286180062) passed Python lint, full Python tests and frontend checks. Dedicated tests cover restart persistence, expiration, origin enforcement and logout revocation.
- The owner ran `ssh homehub 'cd ~/home-hub && ./scripts/deploy.sh'`; the Latitude fast-forwarded `a2062bf` → `b1e9db0`, restarted `home-hub.service`, reported backend healthy after **13 seconds** and `✓ Deploy complete.`
- An independent LAN `GET :8000/health` returned **HTTP 200** with live `build_id=b1e9db02`. The owner signed in once and subsequently reported **Safari appears to stay unlocked** on return/open, which is positive physical iPhone evidence.
- **Not separately witnessed:** a later intentional backend restart *followed by* Safari persistence recheck, or long-term 365-day behavior. Do not call that proven by an isolated unit test. A user-initiated Lock, cookie/site-data deletion, expiration, or browser cookie loss can legitimately require another login.
- Do **not** publicly expose the owner dashboard, relax owner WSS reads or assume IP-range membership alone securely identifies the owner merely to eliminate sign-ins.

## Redesign rollout and the immediate UI handoff

- [PR #541](https://github.com/agatte/home-hub/pull/541) merged to `master` at `a2062bfa`. Operator deployment `04d4d4f` → `a2062bf` built the production frontend successfully, restarted the backend, returned healthy after 14 seconds and reported `✓ Deploy complete.` It delivered a phone-first redesigned root with compact status, mode choice/Auto, two-column room navigation, individually exposed fixture controls, compact weather/history and the preserved `/classic` route.
- Isolated Edge testing at 320/360/390/700/1440 CSS pixels and CI passed. These are **not substitutes** for live Safari/kiosk acceptance. The owner has now opened the actual iPhone redesign and said the interface is **“better”**, but has not declared the full UI/lighting/product experience finished. Keep **#461 open**.
- **Next active work: the redesign itself**. Review the *current deployed* iPhone Home and Control task flow with the owner: visual hierarchy/finish (not Classic-with-different-CSS), individual L1–L6 fixture usability/readback, modes and Return to Auto, helpful weather/activity information without diagnostics clutter, navigation and Settings, plus the kiosk-sized desktop composition. Fix real UI friction in bounded changes with compiled-browser evidence and actual phone/kiosk feedback. Preserve owner control, per-fixture Hue ownership and `/classic` throughout.
- **Separate work, not required to block the phone:** physically accurate apartment canvas [#192](https://github.com/agatte/home-hub/issues/192) and the broader #157 app-wide visual work; no invented geometry or sensors. Keep guest Return Home #540 and legacy 8000 security migration in their owning workstreams.

**Current operational recommendation:** Leave ports, kiosk URL, local naming, trusted-device session and guest/network setup untouched while returning to #461. A future portless HTTPS address and optional 8000 hardening deserve their own scoped technical decision after the primary dashboard design is accepted.

## Source and evidence links

- Application/listeners: [`run.py`](../run.py), [`backend/main.py`](../backend/main.py), [`backend/api/owner_session.py`](../backend/api/owner_session.py), [`frontend-svelte/src/routes/+page.svelte`](../frontend-svelte/src/routes/+page.svelte), [`frontend-svelte/src/routes/classic/+page.svelte`](../frontend-svelte/src/routes/classic/+page.svelte).
- Kiosk deployment/recycle: [`deployment/home-hub.service`](../deployment/home-hub.service), [`scripts/recycle-kiosk.sh`](../scripts/recycle-kiosk.sh), and the on-host XDG autostart path above.
- Operational and owner acceptance evidence: [#461](https://github.com/agatte/home-hub/issues/461), [#541](https://github.com/agatte/home-hub/pull/541), [#542](https://github.com/agatte/home-hub/pull/542), [#540](https://github.com/agatte/home-hub/issues/540).
