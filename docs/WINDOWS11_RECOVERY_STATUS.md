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

- [ ] Trace the current sleep-watcher decision logic end to end.
- [ ] Determine exactly what Home Hub controls versus Windows power settings.
- [ ] Verify what causes monitor/display blanking.
- [ ] Verify what causes Windows PC sleep.
- [ ] Verify how active use and active watching suppress sleep.
- [ ] Verify the Epson projector sleep/off path and whether it is commanded directly or follows PC/system state.
- [ ] Decide whether Windows system sleep should remain disabled while display-off is set to 30 minutes.
## Recovery debt

- [ ] Correct stale `C:\Users\antho` references to `C:\Users\Anthony` where they describe the current rebuilt machine.
- [ ] Update `docs/LOCAL_WORKSPACE.md` to accurately describe the current Windows 11 environment.
- [ ] Make the supervisor installation/recovery path reproduce the known-good current setup.
- [ ] Update checked-in supervisor launch/setup scripts away from nonexistent `C:\Python313\pythonw.exe` and `venv` assumptions to the validated `.venv` layout or another deliberately documented equivalent.
- [ ] Ensure supervisor documentation/setup reflects all seven managed agents.
- [ ] Preserve and commit the existing `AGENTS.md` safe-worktree-removal rule after review.
- [ ] Validate and make durable the working `openrgb-python 0.3.7` requirement; `requirements.txt` still pins 0.3.6.
- [ ] Repair the Windows built-in OpenSSH Client or deliberately standardize Home Hub Windows tooling on Git-for-Windows SSH.
- [ ] Do not rotate/recreate the Home Hub SSH key merely because Windows OpenSSH is broken; Git SSH already proved the existing key authenticates successfully.
- [ ] Determine whether the historical HomeHub/restic backup workflow is still intended.
- [ ] If backups are still intended, restore from known-good configuration and validate a backup/restore path rather than reconstructing blindly from stale docs.

## Deferred cleanup

- [ ] Decide whether the four historical worktrees should be retired after recovery fixes/documentation are committed.
- [ ] Do not recreate the historical `projector-kasa` worktree merely because stale documentation mentions it.
- [ ] Remove or archive stale historical documentation only when its replacement/current truth is verified.

## Completion standard

A recovery item is not complete merely because a file, process, task, or MFT record exists. Mark an item complete only when the intended behavior or content has been verified. For reconstructed items, record what was reconstructed and the evidence used to validate it. For unrecoverable historical items, state that explicitly rather than repeatedly retrying known TRIM-zeroed sources.

When an item above is completed, add a short dated note beneath it describing the change and the verification evidence. Keep this file current until the Windows 11 Home Hub recovery/reorientation is fully closed.
