"""
Process name lists for activity detection.

Add game or media player process names to the appropriate set.
Process names are case-insensitive during matching.
"""

# Game processes — any of these running = "gaming" mode
# No Discord dependency: user uses in-game voice chat (League, etc.) with headset
GAME_PROCESSES: set[str] = {
    # Riot Games
    "leagueoflegends.exe",
    "league of legends.exe",
    "leagueclient.exe",
    "leagueclientux.exe",
    "riotclientservices.exe",
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
}

# Browser processes — used for "working" detection (browser + late night + no game)
BROWSER_PROCESSES: set[str] = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
}
