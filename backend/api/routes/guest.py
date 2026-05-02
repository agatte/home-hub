"""
Guest endpoints — credentials and assets surfaced for the /guest landing
page and the home dashboard's GuestWifiWidget.
"""
import logging

from fastapi import APIRouter

from backend.config import settings

logger = logging.getLogger("home_hub.guest")

router = APIRouter(prefix="/api/guest", tags=["guest"])


_WIFI_ESCAPE = str.maketrans({
    "\\": "\\\\",
    ";": "\\;",
    ",": "\\,",
    '"': '\\"',
    ":": "\\:",
})


def _wifi_uri(ssid: str, password: str, security: str) -> str:
    """Build the WIFI: URI per the de-facto QR spec.

    Special chars (`\\;,":`) must be escaped inside SSID/password fields.
    """
    return (
        f"WIFI:T:{security};"
        f"S:{ssid.translate(_WIFI_ESCAPE)};"
        f"P:{password.translate(_WIFI_ESCAPE)};"
        f"H:false;;"
    )


@router.get("/wifi")
async def get_guest_wifi() -> dict:
    """Return the guest WiFi QR payload + display fields.

    Returns `{configured: false}` if SSID/password aren't set, so the
    frontend can render a quiet "not configured" state instead of erroring.
    Password never leaves the LAN — same trust boundary as every other GET.
    """
    ssid = settings.GUEST_WIFI_SSID
    password = settings.GUEST_WIFI_PASSWORD
    security = settings.GUEST_WIFI_SECURITY or "WPA"

    if not ssid or not password:
        return {"status": "ok", "configured": False}

    return {
        "status": "ok",
        "configured": True,
        "ssid": ssid,
        "password": password,
        "security": security,
        "qr_payload": _wifi_uri(ssid, password, security),
    }
