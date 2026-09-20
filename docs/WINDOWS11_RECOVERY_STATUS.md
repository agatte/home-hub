# Home Hub Windows 11 Recovery Status

Updated: 2026-09-20

This file is the canonical checklist for recovery and reorientation of the Windows-side Home Hub environment after the failed Windows 10 SSD and clean Windows 11 rebuild. It records what is verified, what was reconstructed, what remains to investigate, and what must not be blindly restored from stale Windows 10 assumptions.

## Safety / recovery rules

- Do not expose `.env` values, SSH private-key contents, tokens, passwords, or other secrets.
- Do not overwrite the canonical Git tree with damaged recovered source.
- Do not recreate obsolete per-agent Scheduled Tasks or old one-time deploy/probe tasks.
- Do not run the checked-in supervisor setup script until its stale Windows paths/runtime assumptions are corrected.
- Preserve the local `AGENTS.md` guarded-worktree-removal change.
- Retire worktrees only through `C:\RecoveryTools\Safe-RemoveGitWorktree.ps1` and only after the recovery baseline is committed.
- Prefer verified current Windows 11 state over historical Windows 10 documentation when they conflict.

## Verified baseline

- [x] Canonical Windows repo is `C:\Users\Anthony\Documents\home-hub-project\main`.
- [x] Windows `master`, `origin/master`, and live Latitude production match commit `a66d4dc10cd4307d5d46adb50db4b995c3a83f31`.
- [x] Latitude production checkout is clean and `home-hub.service` is healthy.
- [x] Core Home Hub health reports Hue, Sonos, Pi-hole, automation, and overnight jobs healthy.
- [x] One permanent Windows task, `Home Hub Agent Supervisor`, is enabled and firing on logon plus every 5 minutes.
- [x] The supervisor manages seven agents: activity detector, ambient monitor, screen sync, sleep watcher, emotion capture, monitor brightness, and peripheral RGB.
- [x] All seven agents are alive, have zero restarts in the audited supervisor lifetime, and are actively reaching Latitude.
- [x] No obsolete per-agent Home Hub tasks, Run-key entries, Startup-folder entries, or separate Home Hub Windows service were found.
- [x] Samsung G50F DDC/CI brightness control is operational with `screen-brightness-control 0.24.1`.
- [x] OpenRGB 1.0.0 is installed and running as an automatic Windows service.
- [x] PawnIO 2.2.0.0 is installed and its driver/device are healthy.
- [x] OpenRGB SDK is listening on `127.0.0.1:6742` with an established supervisor connection.
- [x] Glorious Model O / O- and Keychron Gaming Keyboard 1 are discovered and driven by the peripheral agent.
- [x] Four recovered secondary worktrees exist, are clean, registered correctly, and match their remote branches.
- [x] At the read-only audit baseline, Windows `master`, remote `master`, and Latitude had no deployed-code drift. Recovery fixes made after that baseline must be committed/synchronized before this invariant is considered restored.

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
- [ ] Manually verify the physical Epson's current `Extended -> Operation -> Sleep Mode` setting. HDMI does not expose that menu setting to Home Hub, so the rebuilt PC cannot prove whether it is still enabled or what timeout is selected.
- [x] Keep Windows automatic system sleep disabled on AC while retaining the 30-minute display timeout. This avoids generic inactivity suspending the PC during watching/long-running activity; Home Hub's mode-aware watcher remains the deliberate S3 path.

**2026-09-20 conclusion:** screen dimming, Windows display-off, PC S3, and projector power are four separate layers. Home Hub dims the Samsung; Windows may remove video after its display-idle policy; Home Hub only suspends the PC after sustained `sleeping`; and the Epson currently relies on its own no-signal Sleep Mode rather than a Home Hub command. Automatic “fell asleep while watching” shutdown remains intentionally unavailable until trustworthy sleep/posture authority exists.
## Recovery debt

- [x] Corrected stale `C:\Users\antho` references where they incorrectly described the current rebuilt machine; retained old-profile paths only when explicitly historical.
- [x] Updated `docs/LOCAL_WORKSPACE.md` to describe the verified Windows 11 checkout, runtime launchers, four surviving worktrees, deployment skill, SSH client, and historical-vs-current boundaries.
- [x] Made the checked-in supervisor install/recovery path reproduce the known-good Windows 11 architecture: stable launchers under `%LOCALAPPDATA%\home-hub`, canonical repo working directory, and `.venv\Scripts\pythonw.exe`.
- [x] Removed the obsolete hard-coded `C:\Python313\pythonw.exe` / `venv` recovery assumptions. The Python 3.13 launcher+interpreter process pair is documented as expected rather than treated as a duplicate supervisor.
- [x] Updated supervisor documentation/setup to reflect all seven managed agents.
- [x] Retired the obsolete standalone ambient/detector setup and detector-restart scripts as fail-closed shims; they can no longer recreate unmanaged per-agent tasks.
- [x] Preserved and committed the `AGENTS.md` guarded-worktree-removal rule; current-path corrections remain in the present recovery batch.
- [x] Validated supervisor recovery changes: all edited PowerShell files parse; repo fallback launcher exits cleanly through the live mutex; 57 supervisor/recovery tests pass; the live supervisor identity remained unchanged with seven agents at zero restarts.
- [x] Made the working `openrgb-python 0.3.7` version durable in `requirements.txt`; live `.venv` reports 0.3.7 and `pip check` reports no broken requirements.
- [x] Deliberately standardized Home Hub Windows SSH on `C:\Program Files\Git\usr\bin\ssh.exe`. Inbox OpenSSH is present but exits 255 even for `-V` and Home Hub connection attempts; Git SSH 10.3 authenticates successfully with the existing key.
- [x] Do not rotate/recreate the Home Hub SSH key merely because Windows OpenSSH is broken; the existing key is verified working through Git SSH.
- [x] Determined backup state: the historical Windows `HomeHubBackups`/restic installation, secrets, verifier runbook, and task did not survive the rebuild and are not cleanly reconstructable from current sources. Do not recreate that offsite layer from stale documentation.
- [ ] Restore and verify the still-intended Latitude-local daily SQLite backup from the clean tracked script. The 4 AM cron survived, but the deployed script is mode 664 and has been failing with `Permission denied`; the recovery batch changes it to tracked mode 755 and adds atomic partial-file handling plus `PRAGMA quick_check` verification.
- [ ] After local DB backup is proven, define a new offsite backup strategy separately if desired; do not label a newly designed restic setup as recovery of the lost Windows 10 configuration.

## Deferred cleanup

- [ ] Decide whether the four historical worktrees should be retired after recovery fixes/documentation are committed.
- [ ] Do not recreate the historical `projector-kasa` worktree merely because stale documentation mentions it.
- [ ] Remove or archive stale historical documentation only when its replacement/current truth is verified.

## Completion standard

A recovery item is not complete merely because a file, process, task, or MFT record exists. Mark an item complete only when the intended behavior or content has been verified. For reconstructed items, record what was reconstructed and the evidence used to validate it. For unrecoverable historical items, state that explicitly rather than repeatedly retrying known TRIM-zeroed sources.

When an item above is completed, add a short dated note beneath it describing the change and the verification evidence. Keep this file current until the Windows 11 Home Hub recovery/reorientation is fully closed.
