"""
Process name lists for activity detection.

Add game or media player process names to the appropriate set.
Process names are case-insensitive during matching. Steam games are also
discovered from installed library manifests so newly installed games can
promote the PC agent to gaming mode without a code change.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

try:
    import winreg
except ImportError:  # pragma: no cover - Windows-only API
    winreg = None

# League of Legends process binaries — subset of GAME_PROCESSES, used by
# the activity detector to gate the localhost Live Client Data API poll
# so non-LoL gaming sessions don't burn a per-tick HTTPS GET.
LOL_PROCESSES: set[str] = {
    "leagueclient.exe",
    "leagueoflegends.exe",
    "league of legends.exe",
}

# Game processes — any of these running = "gaming" mode
# No Discord dependency: user uses in-game voice chat (League, etc.) with headset
GAME_PROCESSES: set[str] = {
    # Riot Games — client + in-game (not RiotClientServices.exe which is always running)
    "leagueclient.exe",
    "leagueoflegends.exe",
    "league of legends.exe",
    "valorant.exe",
    "valorant-win64-shipping.exe",
    # Jagex / OSRS — javaw.exe is too generic (matches every JVM process:
    # JetBrains IDEs, Gradle, build tools, etc.), so rely on the specific
    # Jagex client binaries instead.
    "runelite.exe",
    "osclient.exe",
    # Rocket League
    "rocketleague.exe",
    # Steam / common games
    "csgo.exe",
    "cs2.exe",
    "dota2.exe",
    "gtav.exe",
    "gta5.exe",
    "fortniteclient-win64-shipping.exe",
    "overwatch.exe",
    "minecraft.exe",
    "minecraftlauncher.exe",
    "apex_legends.exe",
    "r5apex.exe",
    "eldenring.exe",
    "witcher3.exe",
    "baldursgate3.exe",
    "bg3.exe",
    "palworld-win64-shipping.exe",
    "helldivers2.exe",
    "oxygennotincluded.exe",
    # Planet Zoo
    "planetzoo.exe",
    # Rust (Facepunch Studios) — via Steam
    "rustclient.exe",
    # Epic / launchers (only count if a game is also running)
    # Not included: epicgameslauncher.exe, steam.exe (launcher != gaming)
}

STEAM_DISCOVERY_TTL_SECONDS = 1800.0
STEAM_MANIFEST_RE = re.compile(r'"(?P<key>[^"]+)"\s+"(?P<value>(?:\\.|[^"])*)"')
STEAM_EXE_EXCLUDE_PARTS: tuple[str, ...] = (
    "benchmark",
    "crash",
    "crashhandler",
    "crashpad",
    "dxsetup",
    "editor",
    "install",
    "installer",
    "redist",
    "redistributable",
    "renderinfo",
    "restarter",
    "setup",
    "steamerrorreporter",
    "steaminterface",
    "unins",
    "uninstall",
    "unitycrashhandler",
    "vc_redist",
    "vcredist",
)
STEAM_APP_NAME_EXCLUDE_PARTS: tuple[str, ...] = (
    "common redistributables",
    "crosshair overlay",
    "hudsight",
    "proton",
    "runtime",
    "sdk",
    "server",
    "spacewar",
)

_steam_game_process_cache: set[str] = set()
_steam_game_process_cache_at: float = 0.0

# Canonical game-name resolution for per-game lighting profiles. Maps a
# specific game binary to a stable slug the backend keys profiles off (e.g.
# the Rust "Rusted Ember" profile in light_state_calculator.GAME_LIGHT_PROFILES).
# Only games with a dedicated lighting profile need an entry; every other game
# falls through to the generic saturated gaming palette + color screen-sync.
# Process names are lowercased before lookup (matching is case-insensitive).
GAME_NAME_BY_PROCESS: dict[str, str] = {
    "rustclient.exe": "rust",
}


def get_game_processes() -> set[str]:
    """Return static game processes plus cached Steam library discovery.

    Discovery is best-effort and intentionally conservative about launchers:
    ``steam.exe`` never counts, while executables inside installed game
    directories do. This lets newly installed Steam games participate in
    generic gaming lighting after the cache refreshes.
    """
    return GAME_PROCESSES | discover_steam_game_processes()


def discover_steam_game_processes(now: float | None = None) -> set[str]:
    """Discover likely game executables from installed Steam libraries."""
    global _steam_game_process_cache_at
    now = time.time() if now is None else now
    if (now - _steam_game_process_cache_at) < STEAM_DISCOVERY_TTL_SECONDS:
        return set(_steam_game_process_cache)

    processes: set[str] = set()
    for steam_root in _candidate_steam_roots():
        for library in _steam_library_paths(steam_root):
            processes.update(_steam_game_processes_from_library(library))

    _steam_game_process_cache.clear()
    _steam_game_process_cache.update(processes)
    _steam_game_process_cache_at = now
    return set(_steam_game_process_cache)


def _candidate_steam_roots() -> set[Path]:
    roots: set[Path] = set()

    if winreg is not None:
        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        ):
            try:
                with winreg.OpenKey(hive, key) as reg_key:
                    for value_name in ("SteamPath", "InstallPath"):
                        try:
                            value, _ = winreg.QueryValueEx(reg_key, value_name)
                        except OSError:
                            continue
                        if isinstance(value, str) and value:
                            roots.add(Path(value))
            except OSError:
                continue

    roots.update({
        Path("C:/Program Files (x86)/Steam"),
        Path("C:/Program Files/Steam"),
    })
    return {root for root in roots if root.exists()}


def _steam_library_paths(steam_root: Path) -> set[Path]:
    libraries = {steam_root}
    libraryfolders = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        text = libraryfolders.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return libraries

    for match in STEAM_MANIFEST_RE.finditer(text):
        if match.group("key") != "path":
            continue
        path = _unescape_vdf_string(match.group("value"))
        if path:
            libraries.add(Path(path))
    return {library for library in libraries if (library / "steamapps").exists()}


def _steam_game_processes_from_library(library: Path) -> set[str]:
    processes: set[str] = set()
    steamapps = library / "steamapps"
    for manifest in steamapps.glob("appmanifest_*.acf"):
        app_dir = _steam_app_dir_from_manifest(manifest, steamapps)
        if app_dir is None:
            continue
        processes.update(_likely_game_exes(app_dir))
    return processes


def _steam_app_dir_from_manifest(manifest: Path, steamapps: Path) -> Path | None:
    try:
        text = manifest.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    values = {
        match.group("key").lower(): _unescape_vdf_string(match.group("value"))
        for match in STEAM_MANIFEST_RE.finditer(text)
    }
    name = values.get("name", "").lower()
    if any(part in name for part in STEAM_APP_NAME_EXCLUDE_PARTS):
        return None

    install_dir = values.get("installdir")
    if not install_dir:
        return None
    app_dir = steamapps / "common" / install_dir
    return app_dir if app_dir.exists() else None


def _likely_game_exes(app_dir: Path) -> set[str]:
    processes: set[str] = set()
    try:
        candidates = app_dir.rglob("*.exe")
        for exe in candidates:
            try:
                rel_parts = {part.lower() for part in exe.relative_to(app_dir).parts}
            except ValueError:
                rel_parts = {part.lower() for part in exe.parts}
            if "_commonredist" in rel_parts or "redistributable" in rel_parts:
                continue
            name = exe.name.lower()
            stem = exe.stem.lower()
            if any(part in stem for part in STEAM_EXE_EXCLUDE_PARTS):
                continue
            processes.add(name)
    except OSError:
        return processes
    return processes


def _unescape_vdf_string(value: str) -> str:
    return value.replace(r"\\", "\\").replace(r"\"", '"')


# Media player processes — any of these running = "watching" mode
MEDIA_PROCESSES: set[str] = {
    "vlc.exe",
    "plex.exe",
    "plexmediaplayer.exe",
    "plex htpc.exe",
    "mpc-hc64.exe",
    "mpc-hc.exe",
    "mpv.exe",
    "kodi.exe",
    "wmplayer.exe",
    "stremio.exe",
    "stremio service.exe",
    "stremio-runtime.exe",   # Modern Stremio shell (5.x+)
    "stremio-shell-ng.exe",  # Modern Stremio main window
}

# Browser processes — used for "working" detection (late night + no game)
BROWSER_PROCESSES: set[str] = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
}

# Window-title keywords that mark a focused browser tab as "watching".
# Matched case-insensitively against the foreground window title — Firefox,
# Chrome, etc. all surface the active page title in their window title bar.
# Kept conservative on purpose: only video-watching sites belong here, not
# music sites (Spotify, SoundCloud) since music shouldn't flip the mode.
WATCHING_TITLE_KEYWORDS: tuple[str, ...] = (
    "youtube",
    "twitch",
    "netflix",
    "hulu",
    "disney+",
    "hbo max",
    "max | stream",  # HBO Max rebrand — page title pattern "Movie Title | Stream on Max"
    "plex",
    "prime video",
)

# Dev/terminal processes — also count as "working"
WORK_PROCESSES: set[str] = {
    "windowsterminal.exe",
    "powershell.exe",
    "pwsh.exe",          # PowerShell 7+
    "cmd.exe",
    "bash.exe",          # Git Bash / WSL
    "wsl.exe",           # Windows Subsystem for Linux
    "code.exe",          # VS Code
    "cursor.exe",        # Cursor IDE
    "claude.exe",        # Claude Code
    "devenv.exe",        # Visual Studio
    "sublime_text.exe",
    "notepad++.exe",
    "rider64.exe",       # JetBrains Rider
    "idea64.exe",        # JetBrains IntelliJ
    "pycharm64.exe",     # JetBrains PyCharm
    "webstorm64.exe",    # JetBrains WebStorm
    "datagrip64.exe",    # JetBrains DataGrip
    "wezterm-gui.exe",   # WezTerm
    "alacritty.exe",     # Alacritty
    "hyper.exe",         # Hyper terminal
    "tabby.exe",         # Tabby terminal
    "warp.exe",          # Warp terminal
    "mintty.exe",        # MinTTY (Git Bash default)
}
