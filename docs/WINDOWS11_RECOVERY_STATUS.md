# Home Hub Windows 11 Recovery Status

Updated: 2026-09-20

This file is the canonical checklist for recovery and reorientation of the Windows-side Home Hub environment after the failed Windows 10 SSD and clean Windows 11 rebuild. It records what is verified, what was reconstructed, what remains to investigate, and what must not be blindly restored from stale Windows 10 assumptions.

**Recovery closeout:** all currently recoverable/actionable Windows and Home Hub recovery items are complete, including physical verification of the Epson projector's 30-minute Sleep Mode. The only unchecked item below is an explicitly optional future offsite-backup design; it is new infrastructure, not unfinished recovery.

## Safety / recovery rules

- Do not expose `.env` values, SSH private-key contents, tokens, passwords, or other secrets.
- Do not overwrite the canonical Git tree with damaged recovered source.
- Do not recreate obsolete per-agent Scheduled Tasks or old one-time deploy/probe tasks.
- Use the checked-in unified supervisor setup/recovery path only; it now targets the validated AppData launcher + repo `.venv` layout. Do not recreate obsolete per-agent tasks.
- Preserve the committed `AGENTS.md` guarded-worktree-removal rule.
- Retire any future worktrees only through `C:\RecoveryTools\Safe-RemoveGitWorktree.ps1` after proving they are registered, clean, and not carrying unique work.
- Prefer verified current Windows 11 state over historical Windows 10 documentation when they conflict.

## Verified baseline

- [x] Canonical Windows repo is `C:\Users\Anthony\Documents\home-hub-project\main`.
- [x] Windows `master`, `origin/master`, Latitude `master`, Latitude `origin/master`, and Latitude `.last-deployed-sha` match commit `40713d21566a055da774547765c8609ef0f304aa`.
- [x] Latitude production checkout is clean; `home-hub.service` and `home-hub-latitude-streaming.service` are active and healthy. The backend currently reports runtime `build_id=af12523` because commits after `af12523` were script/docs/skill-only releases and correctly did not restart the backend.
- [x] Core Home Hub health reports Hue, Sonos, Pi-hole, automation, and overnight jobs healthy.
- [x] One permanent Windows task, `Home Hub Agent Supervisor`, is enabled and firing on logon plus every 5 minutes.
- [x] The supervisor now manages six agents: activity detector, ambient monitor, screen sync, sleep watcher, emotion capture, and monitor brightness. Peripheral RGB was retired on 2026-09-20.
- [x] The six retained agents are the supported Windows supervisor fleet and actively reach Latitude.
- [x] No obsolete per-agent Home Hub tasks, Run-key entries, Startup-folder entries, or separate Home Hub Windows service were found.
- [x] Samsung G50F DDC/CI brightness control is operational with `screen-brightness-control 0.24.1`.
- [x] OpenRGB 1.0.0 was recovered successfully, then retired from Home Hub on 2026-09-20; the Windows service is disabled as part of that retirement.
- [x] PawnIO 2.2.0.0 is installed and its driver/device are healthy.
- [x] The former OpenRGB SDK/peripheral agent path is no longer part of the supported runtime; mouse/keyboard/GPU lighting are not Home Hub-owned.
- [x] `main` is the sole registered worktree. The four temporary recovery worktrees were retired only after proving they were clean and had zero unique commits; their local and remote branch refs remain preserved.
- [x] The no-drift invariant is restored: Windows Git, GitHub `origin/master`, Latitude Git, and `.last-deployed-sha` are synchronized at the current recovery closeout commit.

## Active investigations

### Emotion / FaceLandmarker lane

- [x] Determine why FaceLandmarker repeatedly reported `produced no usable face confidence ... recycling model state`.
- [x] Anthony confirmed on 2026-09-20 that he had been continuously visible in the webcam view during the audit; the warning was not dismissed as a no-person interval.
- [x] Verified the emotion agent is using the only present camera device, Logitech Brio 101 via `cv2.VideoCapture(0, CAP_DSHOW)`.
- [x] Verified live frames were valid 640x480 images with healthy brightness/contrast; exclusive diagnostics also produced 13 visible PoseLandmarker landmarks without saving images.
- [x] Identified two defects: the desktop path treated the strongest non-neutral expression blendshape as face-detection confidence, and FaceLandmarker itself is intermittent as a primary face detector in the desk/profile geometry.
- [x] Verified threshold/resolution changes alone were not sufficient: FaceLandmarker missed at 640x480, 1280x720, and 1920x1080 even with 0.30 detection/presence/tracking thresholds while pose remained visible.
- [x] Verified the existing full-range BlazeFace model detects the same Brio geometry reliably (diagnostic score 0.6602) and that FaceLandmarker succeeds on the BlazeFace-guided crop.
- [x] Corrected desktop semantics so expression intensity is no longer used as face-detection confidence; added full-range BlazeFace fallback and crop retry only when full-frame FaceLandmarker misses.
- [x] Genuine no-face intervals no longer count as semantic-health failures when the fallback detector is healthy; a visible face with missing blendshapes still triggers bounded recovery.
- [x] Added regression coverage for a neutral face below the old 0.30 expression proxy and for full-range fallback/crop recovery.
- [x] Validation: focused recovery suite 9/9 passed; adjacent emotion/presence suites 136/136 passed; Python compile and `git diff --check` clean.
- [x] Live verification after supervisor restart: 20 consecutive derived backend samples reported `face_present=true`, `detection_source=face`, `zone=desk`, with 13-23 visible pose landmarks and no new semantic-recycle warning during the validation window. At 16:15:54 the fallback initialized naturally after a full-frame miss; the next live desktop reading remained `face_present=true`/`zone=desk` with BlazeFace confidence 0.5399 and 13 visible pose landmarks, proving the fallback path works in the running supervisor.

**2026-09-20 resolution:** The webcam and MediaPipe installation were not dead. The principal false-negative mechanism was an invalid confidence contract (expression magnitude used as presence confidence), compounded by FaceLandmarker's intermittent full-frame detection at Anthony's normal desk angle. Raw frames were kept in memory only; no diagnostic webcam images were saved.

### Sleep / display / projector behavior

- [x] Traced the current sleep-watcher decision logic end to end.
- [x] Verified Windows 11 power policy on AC: Balanced plan, display timeout 1800s (30 minutes), automatic system sleep disabled (0 / Never), with S3 available.
- [x] Verified Home Hub monitor control is brightness/color only. `monitor_brightness` sets the Samsung G50F to a 5% target in `sleeping` mode but does not power the monitor off and does not call Windows `SetThreadExecutionState` / display-required APIs.
- [x] Verified Windows display blanking is therefore owned by Windows/media execution requests, not Home Hub. Home Hub itself does not suppress the 30-minute display timeout. A live `powercfg /requests` snapshot could not be read from the non-elevated shell, so current per-process display requests were not asserted.
- [x] Verified PC sleep is Home Hub-owned on AC: `sleep_watcher` arms only while backend mode is `sleeping`, waits 3600s, then calls `SetSuspendState(False, False, False)` for S3. Any mode change cancels the timer.
- [x] Verified the final local-input safety gate: if keyboard/mouse idle time is under 600s when the 60-minute timer fires, suspend is vetoed and the watcher re-arms for another 60 minutes.
- [x] Verified active use / active watching do not arm the S3 timer because their effective mode is not `sleeping`. Qualified fresh Desktop interaction can also wake Home Hub out of an existing Sleeping state.
- [x] Verified the historical automatic `watching -> sleeping` guard is currently dormant: it still requires `zone=bed + posture=reclined`, while the current Desktop path supplies Bed location without inferring sleeping/reclined posture and Latitude no longer owns bedroom-bed geometry. Do **not** weaken this to “Bed means asleep.”
- [x] Verified the canonical repo contains no live Epson/Kasa/RS-232 projector power-control path. Windows currently enumerates `EPSON PJ` as a connected monitor; Home Hub's projector references are lighting/context policy only.
- [x] External model verification: H421A is the Epson PowerLite Home Cinema 3010 family. Epson documents projector Sleep Mode as shutting the projector off after loss of video signal with 5/10/30-minute choices; 30 minutes is the factory default.
- [x] Manually verified the physical Epson's `Extended -> Operation` menu on 2026-09-20: `Direct Power On = Off`, `Sleep Mode = 30 min`, `Illumination = On`, `High Altitude Mode = Off`. This confirms the projector itself will power down after 30 minutes without video signal; Home Hub does not need a separate projector power command.
- [x] Keep Windows automatic system sleep disabled on AC while retaining the 30-minute display timeout. This avoids generic inactivity suspending the PC during watching/long-running activity; Home Hub's mode-aware watcher remains the deliberate S3 path.

**2026-09-20 conclusion:** screen dimming, Windows display-off, PC S3, and projector power are four separate layers. Home Hub dims the Samsung; Windows may remove video after its display-idle policy; Home Hub only suspends the PC after sustained `sleeping`; and the Epson currently relies on its own no-signal Sleep Mode rather than a Home Hub command. Automatic “fell asleep while watching” shutdown remains intentionally unavailable until trustworthy sleep/posture authority exists.
## Recovery debt

- [x] Corrected stale `C:\Users\antho` references where they incorrectly described the current rebuilt machine; retained old-profile paths only when explicitly historical.
- [x] Updated `docs/LOCAL_WORKSPACE.md` to describe the verified Windows 11 checkout, runtime launchers, temporary recovery worktrees and their later retirement, deployment skill, SSH client, and historical-vs-current boundaries.
- [x] Made the checked-in supervisor install/recovery path reproduce the known-good Windows 11 architecture: stable launchers under `%LOCALAPPDATA%\home-hub`, canonical repo working directory, and `.venv\Scripts\pythonw.exe`.
- [x] Removed the obsolete hard-coded `C:\Python313\pythonw.exe` / `venv` recovery assumptions. The Python 3.13 launcher+interpreter process pair is documented as expected rather than treated as a duplicate supervisor.
- [x] Updated supervisor documentation/setup to reflect the supported six-agent fleet after peripheral RGB retirement.
- [x] Retired the obsolete standalone ambient/detector setup and detector-restart scripts as fail-closed shims; they can no longer recreate unmanaged per-agent tasks.
- [x] Preserved and committed the `AGENTS.md` guarded-worktree-removal rule; current-path corrections remain in the present recovery batch.
- [x] Validated supervisor recovery changes before closeout; the later peripheral-RGB retirement preserves the same unified-supervisor recovery path for the remaining six agents.
- [x] Removed `openrgb-python` from the supported Home Hub dependency set when peripheral RGB was retired on 2026-09-20.
- [x] Deliberately standardized Home Hub Windows SSH on `C:\Program Files\Git\usr\bin\ssh.exe`. Inbox OpenSSH is present but exits 255 even for `-V` and Home Hub connection attempts; Git SSH 10.3 authenticates successfully with the existing key.
- [x] Do not rotate/recreate the Home Hub SSH key merely because Windows OpenSSH is broken; the existing key is verified working through Git SSH.
- [x] Determined backup state: the historical Windows `HomeHubBackups`/restic installation, secrets, verifier runbook, and task did not survive the rebuild and are not cleanly reconstructable from current sources. Do not recreate that offsite layer from stale documentation.
- [x] Restored and verified the intended Latitude-local SQLite backup. The surviving 4:00 AM cron had been failing with `Permission denied` because the tracked script was mode 644; it is now tracked/deployed executable, uses an atomic `.partial` target, verifies `PRAGMA quick_check`, and restores backend health before success.
  - The first live online-backup attempt exposed a second real defect: under the active 3.1 GB DELETE-journal workload, SQLite `.backup` repeatedly restarted/thrashed instead of completing efficiently. That attempt was terminated and its scratch residue removed.
  - The verified design now briefly quiesces **only** `home-hub.service`, copies and checks the DB, restores the service, and requires `/health` before exit 0. A lock file prevents overlapping runs and the EXIT trap restores the backend on failure.
  - Live proof on 2026-09-20: `home_hub_20260920_171701.db` = **3,230,666,752 bytes**, script-reported `quick_check=ok`, independent post-run `PRAGMA quick_check` = `ok`, no `.partial` residue, and Home Hub returned healthy at build `af12523`.
  - Cron is now normalized to **04:30 daily**, avoiding the backend's own 04:00 ML training job; raw crontab bytes end in a normal LF with no stray Windows carriage-return text.
- [ ] Optional future work: define a new offsite backup strategy separately if desired. The lost Windows 10 restic configuration is not recoverable from clean sources, so any new offsite design must be labeled as new infrastructure rather than “restored” old state.

## Deferred cleanup

- [x] Retired the four recovery-time worktrees after verifying each was clean, 7-12 commits behind `master`, and had **zero unique commits**. Removal used the guarded `C:\RecoveryTools\Safe-RemoveGitWorktree.ps1` path; local branch refs and matching `origin/*` branches were preserved.
- [x] Did **not** recreate the historical `projector-kasa` worktree. Current workspace documentation explicitly records it as absent/historical.
- [x] Reviewed stale current-vs-historical documentation. Live surfaces now point to the Windows 11 profile, repo-local deployment skill, Git-for-Windows SSH, and sole `main` worktree. Remaining Windows 10 / Claude-Code paths occur only in explicitly historical context.
- [x] Classified the historical durable flag queue as unrecovered: `C:\Users\antho\.codex\data\home-hub-flags.jsonl` and the old `.codex` root are absent. The current flag-queue skill now fails closed rather than inventing old rows or silently creating a replacement.

## Completion standard

A recovery item is not complete merely because a file, process, task, or MFT record exists. Mark an item complete only when the intended behavior or content has been verified. For reconstructed items, record what was reconstructed and the evidence used to validate it. For unrecoverable historical items, state that explicitly rather than repeatedly retrying known TRIM-zeroed sources.

When an item above is completed, add a short dated note beneath it describing the change and the verification evidence. Keep this file current until the Windows 11 Home Hub recovery/reorientation is fully closed.
