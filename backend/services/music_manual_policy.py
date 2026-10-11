"""Read-only admission for operator music intent; never grants auto-play authority."""

EXPLICIT_VOLUME_CEILINGS = {"day": 30, "evening": 25, "night": 18, "late_night": 18}


def manual_music_reason(state, lifecycle_state):
    """Synchronous fence shared by Prepare, Play and the verification boundary."""
    try:
        lifecycle = lifecycle_state()
        if lifecycle.get("travel"):
            return "travel_mode_active"
        if lifecycle.get("returning_home"):
            return "returning_home_active"
        # Occupancy is independent of detector activity. Require both authorities
        # explicitly, including the engine's hard Away hold via house_state.
        if state.away_manager.away is not False:
            return "apartment_away"
        house = state.automation.house_state
        mode = str(state.automation.current_mode or "").strip().casefold()
        if house == "sleeping" or mode == "sleeping":
            return "sleeping_active"
        if house == "away" or mode == "away":
            return "apartment_away"
        if house != "home":
            return "house_authority_unavailable"
        if state.automation.is_dnd_active():
            return "dnd_active"
        if state.tts.is_speaking:
            return "tts_active"
        ambient = state.ambient_sound.get_state()
        if any(ambient.get(key) for key in (
            "playing", "sonos_ambient_active", "sonos_ambient_pending",
        )):
            return "ambient_playback_owned"
        if not state.sonos.connected or state.sonos.breaker_open:
            return "sonos_unavailable"
    except Exception:
        return "authority_unavailable"
    return None


def manual_volume_policy(automation):
    """Unknown clock authority abstains; frontend consumes this same decision."""
    try:
        period = automation._get_time_period()
        ceiling = EXPLICIT_VOLUME_CEILINGS[period]
    except Exception:
        return {"reason": "volume_policy_unavailable", "volume_ceiling": None}
    return {"reason": None, "time_period": period, "volume_ceiling": ceiling}
