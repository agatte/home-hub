"""
Process name lists for activity detection.

Add game or media player process names to the appropriate set.
Process names are case-insensitive during matching.
"""

# Game processes — any of these running = "gaming" mode
# No Discord dependency: user uses in-game voice chat (League, etc.) with headset
GAME_PROCESSES: set[str] = {
    # Riot Games — client + in-game (not RiotClientServices.exe which is always running)
    "leagueclient.exe",
    "leagueoflegends.exe",
    "league of legends.exe",
    "valorant.exe",
    "valorant-win64-shipping.exe",
    # Jagex / OSRS
    "javaw.exe",
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
    # Epic / launchers (only count if a game is also running)
    # Not included: epicgameslauncher.exe, steam.exe (launcher ≠ gaming)
}

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
