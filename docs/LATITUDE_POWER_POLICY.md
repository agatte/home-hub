# Latitude HOME/TRAVEL power and update policy

Prepared after the 2026-10-10 read-only Latitude audit. This is an opt-in policy;
deployment alone does not change system power or update settings. House State
Away is not Travel and never changes these laptop settings.

- HOME and RETURNING_HOME: keep sleep/suspend blocked and ignore lid closure.
- TRAVEL, after HomeHub services stop: allow sleep, suspend on lid closure except
  when docked/using an external monitor, dim/blank and lock after 5 minutes,
  suspend after 15 minutes on battery or 30 minutes on AC.
- Return Home blocks sleep before booting the backend and restores the exact
  desktop preferences captured before the trip. Failed Return Home retains that
  baseline for rollback/retry. Failed power transitions are reported explicitly.
- Security update attempts and package-list refreshes run daily. Automatic
  reboot is explicitly disabled. Existing allowed update repositories are kept.
- Routine Ubuntu update notices can be reduced separately. This does not claim
  to suppress Firefox/Snap, firmware, or crash-dialog prompts; identify those
  separately if they persist. Schedule regular manual review for non-security
  updates and required restarts after reducing routine notices.

## Reviewed installation after approved deployment

In the Latitude terminal, from `~/home-hub`:

```bash
sudo /usr/bin/python3 -I scripts/install-homehub-power-policy.py install
/usr/bin/python3 scripts/homehub-desktop-power.py quiet-updates
```

The first command installs a root-owned fixed-action helper and a sudo rule
allowing Anthony only its exact `home` and `travel` actions without repeated
password prompts. No arbitrary command or path is accepted. Initial installation
applies HOME policy; it does not suspend, reboot, upgrade packages, change DNS,
or restart HomeHub. logind receives a configuration-reload signal.

Root rollback evidence is retained at `/var/lib/homehub-power-policy`. Existing
logind/apt configuration files are not rewritten. The root installer refuses
pre-existing managed artifact paths rather than overwriting them. Desktop
baselines are stored under `~/.local/state/home-hub/`.

## Restore original policy

First stop using TRAVEL and return HOME so the desktop baseline is restored.
Then, from the reviewed deployment checkout:

```bash
/usr/bin/python3 scripts/homehub-desktop-power.py restore-updates
sudo /usr/bin/python3 -I scripts/install-homehub-power-policy.py restore
```

Restore checks managed content before removing only the four exact installed
files, and reconstructs the four recorded sleep/suspend mask locations. Backups
are retained. The hostctl hook is inactive whenever the root helper is absent.

## Acceptance still required on the real Latitude

Local tests use disposable fixtures and mocked system commands. They do not
prove real suspend/resume, logind reload, sudo policy, or GNOME effects. After
approved installation, verify HOME settings and health first. Test a full
TRAVEL/lid-close/resume/Return Home cycle when a short HomeHub outage is acceptable.
